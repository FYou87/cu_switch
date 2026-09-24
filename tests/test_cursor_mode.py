import base64
import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from witch.cursor_mode import (
    CursorModeError,
    apply_cursor_mode,
    installed_mode,
    sync_api_profile,
    transform_source,
)
from witch.store import create_provider, read_store

BUNDLE = """
var Gc={extensionIsDev:!1,developmentTooling:!1,enableTraceSpanCollection:!0,enableEmbeddingsModelToggle:!1,enableCPPControlTokenToggle:!1,cursorPredictionOptions:!1,localMode:!1};
function Ukb(){const e=Yi();return ue(yd,{hintText:"Log in to use Cursor AI features",children:"Log in"})}
get when(){return e.customBottomBar},get fallback(){return ue(yt,{get when(){return h()&&!NEb},get fallback(){return ue(Ukb,{})},get children(){return ue(j0b,{})}})}
if(!h()){t.cursorAuthenticationService.login(),t.commandService.executeCommand(hR,"general");return}
"""

AGENT_ROOT = """
var Rl={extensionIsDev:!1,developmentTooling:!1,enableTraceSpanCollection:!0,enableEmbeddingsModelToggle:!1,enableCPPControlTokenToggle:!1,cursorPredictionOptions:!1,localMode:!1};
children:"The best way to code with AI"
ye=F?Tf(jsT,{alertDialogStackSize:q,isPrivateInferenceHardStopActive:w,isWindowFullScreen:V,renderRootErrorFallback:ne,useOpaqueSplashBackground:z,workspace:r,workspaceCollectionService:s}):Tf(wHC,{})
"""

FLAG_ONLY = (
    "var Ns={extensionIsDev:!1,developmentTooling:!1,enableTraceSpanCollection:!0,"
    "enableEmbeddingsModelToggle:!1,enableCPPControlTokenToggle:!1,cursorPredictionOptions:!1,localMode:!1};"
)


def _digest(data: bytes) -> str:
    return base64.b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")


class CursorModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.data = root / "witch.json"
        self.user = root / "cursor-user"
        self.app = root / "app"
        os.environ["WITCH_DATA"] = str(self.data)
        os.environ["WITCH_CURSOR_USER_DATA"] = str(self.user)
        os.environ["WITCH_CURSOR_ROOT"] = str(self.app)
        os.environ["WITCH_CURSOR_NO_LAUNCH"] = "1"
        desktop = self.app / "out" / "vs" / "workbench" / "workbench.desktop.main.js"
        main = self.app / "out" / "main.js"
        desktop.parent.mkdir(parents=True)
        desktop.write_text(BUNDLE, encoding="utf-8")
        main.write_text(FLAG_ONLY, encoding="utf-8")
        product = {
            "version": "9.9.9",
            "commit": "abc123",
            "checksums": {
                "main.js": _digest(FLAG_ONLY.encode()),
                "vs/workbench/workbench.desktop.main.js": _digest(BUNDLE.encode()),
            },
        }
        (self.app / "product.json").write_text(json.dumps(product), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()
        for key in ("WITCH_DATA", "WITCH_CURSOR_USER_DATA", "WITCH_CURSOR_ROOT", "WITCH_CURSOR_NO_LAUNCH"):
            os.environ.pop(key, None)

    def test_transform_roundtrip(self):
        enabled = transform_source(BUNDLE, True)
        self.assertIn("localMode:!0", enabled)
        self.assertIn("(h()||Gc.localMode)&&!NEb", enabled)
        self.assertIn("if(!h()&&!Gc.localMode){t.cursorAuthenticationService.login()", enabled)
        self.assertEqual(transform_source(enabled, True), enabled)
        disabled = transform_source(enabled, False)
        self.assertIn("localMode:!1", disabled)
        self.assertIn("h()&&!NEb", disabled)
        self.assertNotIn("Gc.localMode", disabled)
        self.assertEqual(transform_source(disabled, True), enabled)
        agent = transform_source(AGENT_ROOT, True)
        self.assertIn("(F||Rl.localMode)?Tf(jsT,", agent)
        self.assertEqual(transform_source(agent, True), agent)
        self.assertEqual(transform_source(agent, False), AGENT_ROOT)
        headline_only = FLAG_ONLY + '\nsubtitle:"The best way to code with AI"\n'
        self.assertNotIn("||", transform_source(headline_only, True))
        flagged = transform_source(FLAG_ONLY, True)
        self.assertIn("localMode:!0", flagged)
        self.assertEqual(transform_source(flagged, False), FLAG_ONLY)

    def test_apply_api_then_login_restores_files(self):
        self.assertEqual(installed_mode(), "login")
        change = apply_cursor_mode("api", relaunch=False, quit_running=False, gateway=False)
        self.assertEqual(change.mode, "api")
        self.assertFalse(change.relaunched)
        desktop = (self.app / "out" / "vs" / "workbench" / "workbench.desktop.main.js").read_text(encoding="utf-8")
        main = (self.app / "out" / "main.js").read_text(encoding="utf-8")
        self.assertIn("localMode:!0", desktop)
        self.assertIn("localMode:!0", main)
        self.assertIn("(h()||Gc.localMode)&&!NEb", desktop)
        product = json.loads((self.app / "product.json").read_text(encoding="utf-8"))
        self.assertEqual(product["checksums"]["main.js"], _digest(main.encode()))
        self.assertEqual(
            product["checksums"]["vs/workbench/workbench.desktop.main.js"],
            _digest(desktop.encode()),
        )
        self.assertEqual(read_store()["cursorMode"], "api")
        database = self.user / "User" / "globalStorage" / "state.vscdb"
        connection = sqlite3.connect(database)
        base = connection.execute(
            "SELECT value FROM ItemTable WHERE key LIKE '%applicationUser'"
        ).fetchone()[0]
        payload = json.loads(base)
        self.assertTrue(payload["useOpenAIKey"])
        self.assertTrue(payload["openAIBaseUrl"].endswith("/v1"))
        self.assertIn("witch-echo", payload["aiSettings"]["userAddedModels"])
        self.assertEqual(payload["aiSettings"]["modelConfig"]["composer"]["modelName"], "witch-echo")
        key = connection.execute("SELECT value FROM ItemTable WHERE key=?", ("cursorAuth/openAIKey",)).fetchone()[0]
        self.assertTrue(key)
        self.assertNotIn("sk-", key)
        onboard = connection.execute(
            "SELECT value FROM ItemTable WHERE key LIKE '%firsttime'"
        ).fetchone()[0]
        self.assertEqual(onboard, "false")
        connection.close()

        apply_cursor_mode("login", relaunch=False, quit_running=False, gateway=False)
        self.assertEqual(
            (self.app / "out" / "vs" / "workbench" / "workbench.desktop.main.js").read_text(encoding="utf-8"),
            BUNDLE,
        )
        self.assertEqual((self.app / "out" / "main.js").read_text(encoding="utf-8"), FLAG_ONLY)
        self.assertEqual(installed_mode(), "login")
        self.assertEqual(read_store()["cursorMode"], "login")

    def test_relay_without_key_is_rejected(self):
        create_provider(
            {
                "name": "空站",
                "protocol": "openai",
                "authStyle": "bearer",
                "baseUrl": "https://example.invalid/v1",
                "apiKey": "",
                "models": [{"cursorName": "empty-model", "upstreamId": "m"}],
            }
        )
        with self.assertRaises(CursorModeError):
            apply_cursor_mode("api", relaunch=False, quit_running=False, gateway=False)

    def test_profile_keeps_existing_fields(self):
        database = self.user / "User" / "globalStorage" / "state.vscdb"
        database.parent.mkdir(parents=True)
        connection = sqlite3.connect(database)
        connection.execute("CREATE TABLE ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)")
        connection.execute(
            "INSERT INTO ItemTable(key, value) VALUES(?, ?)",
            (
                "src.vs.platform.reactivestorage.browser.reactiveStorageServiceImpl.persistentStorage.applicationUser",
                json.dumps({"cppEnabled": True, "aiSettings": {"userAddedModels": ["kept-model"]}}),
            ),
        )
        connection.commit()
        connection.close()
        sync_api_profile(self.user, "http://127.0.0.1:43187/v1", "witch_test_token", ["grok-4.7"])
        connection = sqlite3.connect(database)
        payload = json.loads(
            connection.execute(
                "SELECT value FROM ItemTable WHERE key LIKE '%applicationUser'"
            ).fetchone()[0]
        )
        connection.close()
        self.assertTrue(payload["cppEnabled"])
        self.assertEqual(payload["aiSettings"]["userAddedModels"], ["kept-model", "grok-4.7"])
        self.assertEqual(payload["localProviderModelIds"], ["grok-4.7"])


if __name__ == "__main__":
    unittest.main()

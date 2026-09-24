import os
import tempfile
import unittest
from pathlib import Path

from witch.store import (
    create_provider,
    duplicate_provider,
    move_provider,
    patch_provider,
    read_store,
    reorder_providers,
    to_public,
)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["WITCH_DATA"] = str(Path(self.tmp.name) / "witch.json")

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("WITCH_DATA", None)

    def test_reorder_and_move(self):
        create_provider(
            {
                "name": "A站",
                "protocol": "openai",
                "authStyle": "bearer",
                "baseUrl": "https://a.example/v1",
                "apiKey": "sk-aaaaaaaa",
                "models": [{"cursorName": "a-relay", "upstreamId": "a"}],
            },
            activate=False,
        )
        create_provider(
            {
                "name": "B站",
                "protocol": "openai",
                "authStyle": "bearer",
                "baseUrl": "https://b.example/v1",
                "apiKey": "sk-bbbbbbbb",
                "models": [{"cursorName": "b-relay", "upstreamId": "b"}],
            },
            activate=False,
        )
        ids = [item["id"] for item in to_public(read_store())["providers"]]
        self.assertGreaterEqual(len(ids), 3)
        reversed_ids = list(reversed(ids))
        reorder_providers(reversed_ids)
        self.assertEqual([item["id"] for item in to_public(read_store())["providers"]], reversed_ids)
        first = reversed_ids[0]
        move_provider(first, 1)
        moved = [item["id"] for item in to_public(read_store())["providers"]]
        self.assertEqual(moved[1], first)

    def test_website_and_copy_suffix(self):
        create_provider(
            {
                "name": "DeepSeek",
                "protocol": "openai",
                "authStyle": "bearer",
                "baseUrl": "https://api.deepseek.com/v1",
                "apiKey": "sk-deepseek",
                "models": [{"cursorName": "deepseek-chat-relay", "upstreamId": "deepseek-chat"}],
                "website": "https://platform.deepseek.com",
                "iconColor": "#4d6bfe",
            }
        )
        created = next(item for item in to_public(read_store())["providers"] if item["name"] == "DeepSeek")
        self.assertEqual(created["website"], "https://platform.deepseek.com")
        self.assertEqual(created["iconColor"], "#4d6bfe")
        duplicate_provider(created["id"])
        names = [item["name"] for item in to_public(read_store())["providers"]]
        self.assertIn("DeepSeek copy", names)

    def test_edit_persists_and_demo_becomes_relay(self):
        demo = next(item for item in read_store()["providers"] if item["id"] == "demo-echo")
        patch_provider(
            demo["id"],
            {
                "name": "改过的名字",
                "baseUrl": "https://api.example.com/v1",
                "apiKey": "sk-saved",
                "kind": "relay",
                "models": [{"cursorName": "relay-a", "upstreamId": "upstream-a"}],
            },
        )
        saved = next(item for item in read_store()["providers"] if item["id"] == "demo-echo")
        self.assertEqual(saved["name"], "改过的名字")
        self.assertEqual(saved["baseUrl"], "https://api.example.com/v1")
        self.assertEqual(saved["apiKey"], "sk-saved")
        self.assertEqual(saved["kind"], "relay")
        self.assertEqual(saved["models"][0]["cursorName"], "relay-a")
        patch_provider(saved["id"], {"name": "只改名字", "apiKey": ""})
        again = next(item for item in read_store()["providers"] if item["id"] == "demo-echo")
        self.assertEqual(again["name"], "只改名字")
        self.assertEqual(again["apiKey"], "sk-saved")


if __name__ == "__main__":
    unittest.main()

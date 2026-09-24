from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from witch.gateway import start_gateway
from witch.paths import data_file, gateway_base_url
from witch.store import get_active, read_store, write_store

APPLICATION_KEY = (
    "src.vs.platform.reactivestorage.browser.reactiveStorageServiceImpl.persistentStorage.applicationUser"
)
ONBOARD_KEY = "workbench.contrib.onboarding.browser.gettingStarted.contribution.ts.firsttime"
OPENAI_KEY = "cursorAuth/openAIKey"
SECRET_OPENAI_KEY = "secret://cursorAuth/openAIKey"
LOGIN_HINT = 'hintText:"Log in to use Cursor AI features"'
FLAG_MARK = "cursorPredictionOptions:!1,localMode:!"

_FLAG = re.compile(
    r"([A-Za-z_$][\w$]*)=\{([^{}]*cursorPredictionOptions:!1,localMode:!)([01])\}"
)
_SUBMIT = re.compile(
    r"if\(!([A-Za-z_$][\w$]*)\(\)(?:&&![A-Za-z_$][\w$]*\.localMode)?\)\{"
    r"([A-Za-z_$][\w$]*)\.cursorAuthenticationService\.login\(\),"
    r"\2\.commandService\.executeCommand\(([A-Za-z_$][\w$]*),\"general\"\);return\}"
)
_COND = (
    r"(?:[A-Za-z_$][\w$]*\(\)|\([A-Za-z_$][\w$]*\(\)\|\|[A-Za-z_$][\w$]*\.localMode\))"
    r"&&![A-Za-z_$][\w$]*"
)
_PLAIN_COND = re.compile(r"^([A-Za-z_$][\w$]*)\(\)&&!([A-Za-z_$][\w$]*)$")
_API_COND = re.compile(
    r"^\(([A-Za-z_$][\w$]*)\(\)\|\|[A-Za-z_$][\w$]*\.localMode\)&&!([A-Za-z_$][\w$]*)$"
)
_FUNCTION = re.compile(r"function ([A-Za-z_$][\w$]*)\(")
_AGENT_MARK = "The best way to code with AI"
_AGENT_TAIL = re.compile(
    r"\?Tf\((?P<app>[A-Za-z_$][\w$]*),\{alertDialogStackSize:[A-Za-z_$][\w$]*,"
    r"isPrivateInferenceHardStopActive:[A-Za-z_$][\w$]*,"
    r"isWindowFullScreen:[A-Za-z_$][\w$]*,"
    r"renderRootErrorFallback:[A-Za-z_$][\w$]*,"
    r"useOpaqueSplashBackground:[A-Za-z_$][\w$]*,"
    r"workspace:[A-Za-z_$][\w$]*,"
    r"workspaceCollectionService:[A-Za-z_$][\w$]*\}\):Tf\("
    r"(?P<login>[A-Za-z_$][\w$]*),\{\}\)"
)


class CursorModeError(RuntimeError):
    pass


@dataclass
class ModeChange:
    mode: str
    relaunched: bool
    version: str

    @property
    def message(self) -> str:
        if self.mode == "api":
            text = "已切到 API 模式。Agent 和 IDE 都走当前中转站，不用登录 Cursor。"
        else:
            text = "已切回登录模式。Cursor 已恢复成原版，用账号登录。"
        if self.relaunched:
            return text + " Cursor 已重新打开。"
        return text + " 请重新打开 Cursor。"


def find_app_root() -> Path:
    override = os.environ.get("WITCH_CURSOR_ROOT")
    if override:
        path = Path(override).expanduser()
        if not (path / "product.json").is_file():
            raise CursorModeError("没找到 Cursor 的安装目录。")
        return path
    candidates: list[Path] = []
    if sys.platform == "win32":
        candidates.extend(_windows_install_candidates())
    elif sys.platform == "darwin":
        candidates.append(Path("/Applications/Cursor.app/Contents/Resources/app"))
        candidates.append(Path.home() / "Applications" / "Cursor.app" / "Contents" / "Resources" / "app")
    else:
        candidates.extend(
            [
                Path("/usr/share/cursor/resources/app"),
                Path("/opt/cursor/resources/app"),
                Path.home() / ".local/share/cursor/resources/app",
            ]
        )
    for candidate in candidates:
        if (candidate / "product.json").is_file():
            return candidate
    raise CursorModeError("这台机器上没找到 Cursor。")


def _windows_install_candidates() -> list[Path]:
    found: list[Path] = []
    local = os.environ.get("LOCALAPPDATA")
    local_roots = [Path(local)] if local else [Path.home() / "AppData" / "Local"]
    for root in local_roots:
        found.append(root / "Programs" / "cursor" / "resources" / "app")
    for key in ("ProgramFiles", "ProgramW6432"):
        value = os.environ.get(key)
        if not value:
            continue
        found.append(Path(value) / "cursor" / "resources" / "app")
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in found:
        key = str(candidate).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def cursor_user_data() -> Path:
    override = os.environ.get("WITCH_CURSOR_USER_DATA")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        return Path(base or Path.home() / "AppData" / "Roaming") / "Cursor"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Cursor"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return Path(xdg) / "Cursor" if xdg else Path.home() / ".config" / "Cursor"


def cursor_binary(app_root: Path) -> Path | None:
    root = app_root.parent.parent
    for name in ("cursor", "Cursor", "Cursor.exe"):
        candidate = root / name
        if candidate.is_file():
            return candidate
    mac = root / "MacOS" / "Cursor"
    if mac.is_file():
        return mac
    return None


def installed_mode(app_root: Path | None = None) -> str:
    root = app_root or find_app_root()
    desktop = root / "out" / "vs" / "workbench" / "workbench.desktop.main.js"
    probe = desktop if desktop.is_file() else _first_flag_file(root)
    if probe is None:
        raise CursorModeError("这个 Cursor 版本还不能切换 API 模式。")
    with probe.open("rb") as handle:
        head = handle.read(1_500_000)
    if b"cursorPredictionOptions:!1,localMode:!0" in head:
        return "api"
    if b"cursorPredictionOptions:!1,localMode:!1" in head:
        return "login"
    raise CursorModeError("这个 Cursor 版本还不能切换 API 模式。")


def cursor_is_running(binary: Path | None = None) -> bool:
    binary = binary if binary is not None else cursor_binary(find_app_root())
    if binary is None:
        return False
    return bool(_cursor_pids(binary))


def apply_cursor_mode(
    mode: str,
    *,
    relaunch: bool = True,
    quit_running: bool = True,
    gateway: bool = True,
) -> ModeChange:
    if mode not in {"api", "login"}:
        raise CursorModeError("模式只能是 API 或登录。")
    app_root = find_app_root()
    binary = cursor_binary(app_root)
    if quit_running and binary is not None:
        _quit(binary)
    if mode == "api" and gateway:
        try:
            start_gateway()
        except RuntimeError as error:
            raise CursorModeError(str(error)) from error
    version = _product_version(app_root)
    _write_install(app_root, enable=mode == "api")
    if mode == "api":
        base_url, api_key, models = _active_target()
        sync_api_profile(cursor_user_data(), base_url, api_key, models)
    store = read_store()
    store["cursorMode"] = mode
    write_store(store)
    relaunched = False
    if relaunch and binary is not None and os.environ.get("WITCH_CURSOR_NO_LAUNCH") != "1":
        _launch(binary, mode)
        relaunched = True
    return ModeChange(mode=mode, relaunched=relaunched, version=version)


def refresh_api_profile() -> None:
    if read_store().get("cursorMode") != "api":
        return
    try:
        if installed_mode() != "api":
            return
    except CursorModeError:
        return
    base_url, api_key, models = _active_target()
    sync_api_profile(cursor_user_data(), base_url, api_key, models)


def sync_api_profile(user_data: Path, base_url: str, api_key: str, models: list[str]) -> None:
    database = user_data / "User" / "globalStorage" / "state.vscdb"
    database.parent.mkdir(parents=True, exist_ok=True)
    try:
        connection = sqlite3.connect(database, timeout=2)
    except sqlite3.Error as error:
        raise CursorModeError("写不进 Cursor 的配置。先退出 Cursor 再切。") from error
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)"
        )
        raw = connection.execute("SELECT value FROM ItemTable WHERE key=?", (APPLICATION_KEY,)).fetchone()
        payload: dict = {}
        if raw and raw[0]:
            text = raw[0].decode("utf-8") if isinstance(raw[0], bytes) else str(raw[0])
            try:
                loaded = json.loads(text)
            except json.JSONDecodeError:
                loaded = {}
            if isinstance(loaded, dict):
                payload = loaded
        payload["useOpenAIKey"] = True
        payload["openAIBaseUrl"] = base_url
        payload["localProviderModelIds"] = list(models)
        settings = payload.setdefault("aiSettings", {})
        if not isinstance(settings, dict):
            settings = {}
            payload["aiSettings"] = settings
        added = [item for item in settings.get("userAddedModels") or [] if isinstance(item, str)]
        for name in models:
            if name not in added:
                added.append(name)
        settings["userAddedModels"] = added
        if models:
            model_config = settings.setdefault("modelConfig", {})
            if not isinstance(model_config, dict):
                model_config = {}
                settings["modelConfig"] = model_config
            model_config["composer"] = {
                "modelName": models[0],
                "maxMode": False,
                "selectedModels": [{"modelId": models[0], "parameters": []}],
            }
        catalog = payload.get("availableDefaultModels2")
        if not isinstance(catalog, list):
            catalog = []
        known = {item.get("name") for item in catalog if isinstance(item, dict)}
        template = next((item for item in catalog if isinstance(item, dict)), None)
        for name in models:
            if name in known:
                continue
            entry = dict(template) if template else _blank_model()
            entry["name"] = name
            entry["clientDisplayName"] = name
            entry["inputboxShortModelName"] = name
            entry["supportsAgent"] = True
            catalog.append(entry)
            known.add(name)
        payload["availableDefaultModels2"] = catalog
        _put(connection, APPLICATION_KEY, json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        _put(connection, ONBOARD_KEY, "false")
        _put(connection, OPENAI_KEY, api_key)
        connection.execute("DELETE FROM ItemTable WHERE key=?", (SECRET_OPENAI_KEY,))
        connection.commit()
    except sqlite3.Error as error:
        raise CursorModeError("Cursor 正开着，配置写不进去。先退出再切。") from error
    finally:
        connection.close()


def transform_source(text: str, enable: bool) -> str:
    if len(_FLAG.findall(text)) != 1:
        raise CursorModeError("这个 Cursor 版本还不能切换 API 模式。")
    flag = _FLAG.search(text)
    if not flag:
        raise CursorModeError("这个 Cursor 版本还不能切换 API 模式。")
    flag_name = flag.group(1)
    bit = "0" if enable else "1"
    text = _FLAG.sub(lambda match: f"{match.group(1)}={{{match.group(2)}{bit}}}", text, count=1)
    text = _transform_submit(text, flag_name, enable)
    if LOGIN_HINT in text:
        text = _transform_visibility(text, flag_name, enable)
    return _transform_agent_root(text, flag_name, enable)


def _transform_submit(text: str, flag_name: str, enable: bool) -> str:
    matches = list(_SUBMIT.finditer(text))
    if LOGIN_HINT in text and not matches:
        raise CursorModeError("这个 Cursor 版本的发送逻辑对不上，还不能切 API 模式。")

    def replacer(match):
        signed, service, command = match.group(1), match.group(2), match.group(3)
        guard = f"!{signed}()&&!{flag_name}.localMode" if enable else f"!{signed}()"
        return (
            f"if({guard}){{{service}.cursorAuthenticationService.login(),"
            f"{service}.commandService.executeCommand({command},\"general\");return}}"
        )

    return _SUBMIT.sub(replacer, text)


def _transform_agent_root(text: str, flag_name: str, enable: bool) -> str:
    matches = list(_AGENT_TAIL.finditer(text))
    if not matches:
        if _AGENT_MARK in text and "alertDialogStackSize:" in text:
            raise CursorModeError("这个 Cursor 版本的 Agent 登录页对不上，还不能切 API 模式。")
        return text
    if len(matches) != 1:
        raise CursorModeError("这个 Cursor 版本的 Agent 登录页对不上，还不能切 API 模式。")
    match = matches[0]
    head = text[: match.start()]
    enabled = re.search(
        rf"\(([A-Za-z_$][\w$]*)\|\|{re.escape(flag_name)}\.localMode\)$",
        head,
    )
    plain = re.search(r"(?<![\w$])([A-Za-z_$][\w$]*)$", head)
    if enabled:
        if enable:
            return text
        return head[: enabled.start()] + enabled.group(1) + text[match.start() :]
    if plain:
        if not enable:
            return text
        return head[: plain.start()] + f"({plain.group(1)}||{flag_name}.localMode)" + text[match.start() :]
    raise CursorModeError("这个 Cursor 版本的 Agent 登录页对不上，还不能切 API 模式。")


def _transform_visibility(text: str, flag_name: str, enable: bool) -> str:
    hint = text.find(LOGIN_HINT)
    function_name = None
    for match in _FUNCTION.finditer(text[:hint]):
        function_name = match.group(1)
    if not function_name or f"({function_name},{{}})" not in text:
        raise CursorModeError("这个 Cursor 版本的登录按钮对不上，还不能切 API 模式。")
    pattern = re.compile(
        r"get when\(\)\{return (?P<cond>"
        + _COND
        + r")\},get fallback\(\)\{return [A-Za-z_$][\w$]*\("
        + re.escape(function_name)
        + r",\{\}\)\}"
    )
    found = list(pattern.finditer(text))
    if len(found) != 1:
        raise CursorModeError("这个 Cursor 版本的登录按钮对不上，还不能切 API 模式。")
    match = found[0]
    parsed = _API_COND.match(match.group("cond")) or _PLAIN_COND.match(match.group("cond"))
    if not parsed:
        raise CursorModeError("这个 Cursor 版本的登录按钮对不上，还不能切 API 模式。")
    signed, gate = parsed.group(1), parsed.group(2)
    cond = (
        f"({signed}()||{flag_name}.localMode)&&!{gate}"
        if enable
        else f"{signed}()&&!{gate}"
    )
    return text[: match.start("cond")] + cond + text[match.end("cond") :]


def _write_install(app_root: Path, enable: bool) -> None:
    bundles = _flag_files(app_root)
    if not bundles:
        raise CursorModeError("这个 Cursor 版本还不能切换 API 模式。")
    product_path = app_root / "product.json"
    product = json.loads(product_path.read_text(encoding="utf-8"))
    commit = str(product.get("commit") or "unknown")
    originals = {path: path.read_bytes() for path in bundles}
    originals[product_path] = product_path.read_bytes()
    if enable:
        for path, raw in originals.items():
            if path == product_path:
                continue
            if b"cursorPredictionOptions:!1,localMode:!1" in raw[:1_500_000]:
                _snapshot(commit, app_root, path, raw)
        if any(b"cursorPredictionOptions:!1,localMode:!1" in raw[:1_500_000] for path, raw in originals.items() if path != product_path):
            _snapshot(commit, app_root, product_path, originals[product_path])
    updates: dict[Path, bytes] = {}
    saw_login_ui = False
    for path, raw in originals.items():
        if path == product_path:
            continue
        text = raw.decode("utf-8", "surrogateescape")
        if LOGIN_HINT in text:
            saw_login_ui = True
        if enable:
            updated = transform_source(text, True)
        else:
            backed = _backup_file(commit, app_root, path)
            updated = backed.read_text(encoding="utf-8", errors="surrogateescape") if backed.is_file() else transform_source(text, False)
        data = updated.encode("utf-8", "surrogateescape")
        if data != raw:
            updates[path] = data
    if enable and not saw_login_ui:
        raise CursorModeError("这个 Cursor 版本还不能切换 API 模式。")
    final_bytes = {path: updates.get(path, raw) for path, raw in originals.items() if path != product_path}
    backed_product = _backup_file(commit, app_root, product_path)
    if not enable and backed_product.is_file():
        product_bytes = backed_product.read_bytes()
    else:
        product_bytes = _with_checksums(product, app_root, final_bytes, originals[product_path])
    if product_bytes != originals[product_path]:
        updates[product_path] = product_bytes
    if updates:
        _commit_writes(updates)


def _with_checksums(product: dict, app_root: Path, files: dict[Path, bytes], original: bytes) -> bytes:
    checksums = product.get("checksums")
    if not isinstance(checksums, dict):
        return original
    out = app_root / "out"
    changed = False
    for path, data in files.items():
        try:
            key = path.relative_to(out).as_posix()
        except ValueError:
            continue
        if key not in checksums:
            continue
        digest = base64.b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")
        if checksums.get(key) != digest:
            checksums[key] = digest
            changed = True
    if not changed:
        return original
    product["checksums"] = checksums
    return (json.dumps(product, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _flag_files(app_root: Path) -> list[Path]:
    out = app_root / "out"
    if not out.is_dir():
        return []
    found: list[Path] = []
    for path in out.rglob("*.js"):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > 80_000_000:
            continue
        with path.open("rb") as handle:
            if FLAG_MARK.encode() in handle.read(1_500_000):
                found.append(path)
    return found


def _first_flag_file(app_root: Path) -> Path | None:
    files = _flag_files(app_root)
    return files[0] if files else None


def _backup_root(commit: str) -> Path:
    return data_file().parent / "cursor-backup" / commit


def _backup_file(commit: str, app_root: Path, path: Path) -> Path:
    return _backup_root(commit) / path.relative_to(app_root).as_posix()


def _snapshot(commit: str, app_root: Path, path: Path, raw: bytes) -> None:
    dest = _backup_file(commit, app_root, path)
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)


def _active_target() -> tuple[str, str, list[str]]:
    store, provider = get_active()
    if not provider:
        raise CursorModeError("先启用一个中转站。")
    if provider.get("kind") != "demo" and not (provider.get("apiKey") or "").strip():
        raise CursorModeError(f"「{provider.get('name') or '当前中转站'}」还没填 API Key。")
    models = [
        str(item.get("cursorName") or "").strip()
        for item in provider.get("models") or []
        if str(item.get("cursorName") or "").strip()
    ]
    return gateway_base_url(), str(store.get("gatewayToken") or ""), models


def _blank_model() -> dict:
    return {
        "defaultOn": True,
        "name": "",
        "clientDisplayName": "",
        "inputboxShortModelName": "",
        "supportsAgent": True,
        "isRecommendedForBackgroundComposer": False,
        "idAliases": [],
        "cloudAgentEffortModes": [],
        "modelPickerBadges": [],
        "parameterDefinitions": [],
        "variants": [],
        "legacySlugs": [],
    }


def _put(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute("INSERT OR REPLACE INTO ItemTable(key, value) VALUES(?, ?)", (key, value))


def _product_version(app_root: Path) -> str:
    try:
        product = json.loads((app_root / "product.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(product.get("version") or "")


def _parse_windows_process_json(raw: str) -> list[tuple[int, str, str]]:
    text = raw.strip().lstrip("\ufeff")
    if not text:
        return []
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return []
    rows = loaded if isinstance(loaded, list) else [loaded]
    parsed: list[tuple[int, str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        pid = row.get("ProcessId")
        if isinstance(pid, str) and pid.isdigit():
            pid = int(pid)
        if not isinstance(pid, int):
            continue
        parsed.append((pid, str(row.get("ExecutablePath") or ""), str(row.get("CommandLine") or "")))
    return parsed


def _win_path(value: str) -> str:
    return value.replace("/", "\\").rstrip("\\").lower()


def _windows_main_pids(binary: Path, rows: list[tuple[int, str, str]]) -> list[int]:
    target = _win_path(str(binary))
    found: list[int] = []
    for pid, executable, command in rows:
        exe = _win_path(executable)
        folded = command.replace("/", "\\").lower()
        if exe != target and target not in folded:
            continue
        if "--type=" in folded or "cursor-server" in folded or "cli.js" in folded:
            continue
        found.append(pid)
    return found


def _cursor_pids(binary: Path) -> list[int]:
    if sys.platform == "win32":
        return _windows_main_pids(binary, _windows_processes())
    target = str(binary)
    found: list[int] = []
    proc = Path("/proc")
    if proc.is_dir():
        for entry in proc.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                raw = (entry / "cmdline").read_bytes()
            except OSError:
                continue
            command = raw.replace(b"\0", b" ").decode("utf-8", "replace")
            if target not in command:
                continue
            if "--type=" in command or "cursor-server" in command or "ELECTRON_RUN_AS_NODE" in command:
                continue
            found.append(int(entry.name))
        return found
    try:
        listing = subprocess.run(
            ["ps", "-ax", "-o", "pid=,command="],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return []
    for line in listing.stdout.splitlines():
        line = line.strip()
        if not line or target not in line:
            continue
        if "--type=" in line or "cursor-server" in line:
            continue
        pid, _, _command = line.partition(" ")
        if pid.isdigit():
            found.append(int(pid))
    return found


def _windows_processes() -> list[tuple[int, str, str]]:
    command = [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        "Get-CimInstance Win32_Process -Filter \"Name = 'Cursor.exe'\" | "
        "Select-Object ProcessId,ExecutablePath,CommandLine | ConvertTo-Json -Compress",
    ]
    try:
        listing = subprocess.run(command, check=False, capture_output=True, text=True, encoding="utf-8")
    except OSError:
        return []
    return _parse_windows_process_json(listing.stdout)


def _stop_pid(pid: int, force: bool) -> None:
    if sys.platform == "win32":
        command = ["taskkill", "/PID", str(pid), "/T"]
        if force:
            command.append("/F")
        subprocess.run(command, check=False, capture_output=True)
        return
    try:
        os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
    except OSError:
        return


def _quit(binary: Path) -> None:
    pids = _cursor_pids(binary)
    if not pids:
        return
    for pid in pids:
        _stop_pid(pid, force=False)
    deadline = time.time() + 8
    while time.time() < deadline:
        if not _cursor_pids(binary):
            return
        time.sleep(0.2)
    for pid in _cursor_pids(binary):
        _stop_pid(pid, force=True)
    time.sleep(0.3)
    if _cursor_pids(binary):
        raise CursorModeError("Cursor 还没退出，先手动关掉再切。")


def _launch(binary: Path, mode: str) -> None:
    env = os.environ.copy()
    if mode == "api":
        base_url, api_key, _models = _active_target()
        env["CURSOR_LOCAL_AGENT_BASE_URL"] = base_url
        env["CURSOR_LOCAL_AGENT_API_KEY"] = api_key
        args = [str(binary), "--skip-onboarding", "--skip-welcome"]
    else:
        env.pop("CURSOR_LOCAL_AGENT_BASE_URL", None)
        env.pop("CURSOR_LOCAL_AGENT_API_KEY", None)
        args = [str(binary)]
    kwargs: dict = {
        "env": env,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(args, **kwargs)


def _commit_writes(updates: dict[Path, bytes]) -> None:
    denied: list[tuple[Path, bytes]] = []
    locked = False
    for path, data in updates.items():
        try:
            _atomic_write(path, data)
        except OSError as error:
            if getattr(error, "winerror", None) == 32:
                locked = True
                continue
            if isinstance(error, PermissionError):
                denied.append((path, data))
                continue
            raise
    if locked:
        raise CursorModeError("Cursor 还开着，安装文件被占用。先退出 Cursor 再切。")
    if not denied:
        return
    if sys.platform == "win32":
        raise CursorModeError("没有权限修改 Cursor 的安装目录。右键 Witch，用管理员身份运行。")
    staging = Path(tempfile.mkdtemp(prefix="witch-cursor-"))
    manifest = []
    for index, (path, data) in enumerate(denied):
        source = staging / f"{index}.bin"
        source.write_bytes(data)
        manifest.append({"src": str(source), "dst": str(path)})
    manifest_path = staging / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    script = staging / "apply.py"
    script.write_text(
        "import json, pathlib, sys\n"
        "ops = json.loads(pathlib.Path(sys.argv[1]).read_text())\n"
        "for item in ops:\n"
        "    pathlib.Path(item['dst']).write_bytes(pathlib.Path(item['src']).read_bytes())\n",
        encoding="utf-8",
    )
    if _run([ "sudo", "-n", sys.executable, str(script), str(manifest_path) ]):
        return
    if os.environ.get("DISPLAY") and _run(["pkexec", sys.executable, str(script), str(manifest_path)]):
        return
    raise CursorModeError("没有权限修改 Cursor 的安装目录。")


def _atomic_write(path: Path, data: bytes) -> None:
    temporary = path.with_name(path.name + ".witch-tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def _run(command: list[str]) -> bool:
    try:
        completed = subprocess.run(command, check=False, capture_output=True)
    except OSError:
        return False
    return completed.returncode == 0

from pathlib import Path
import os
import sys


def _user_data() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return base / "Witch" / "witch.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Witch" / "witch.json"
    return Path.home() / ".config" / "witch" / "witch.json"


def portable_root() -> Path | None:
    override = os.environ.get("WITCH_PORTABLE")
    if override:
        return Path(override).expanduser()
    exe = Path(sys.executable).resolve()
    candidates = [
        exe.parent,
        exe.parent.parent,
        exe.parent.parent.parent,
        Path.cwd(),
    ]
    if getattr(sys, "frozen", False):
        candidates.insert(0, exe.parent)
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            candidate = candidate.resolve()
        except OSError:
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        if (candidate / "portable").exists():
            return candidate
    return None


def data_file() -> Path:
    override = os.environ.get("WITCH_DATA")
    if override:
        return Path(override).expanduser()
    root = portable_root()
    if root:
        return root / "data" / "witch.json"
    if getattr(sys, "frozen", False):
        return _user_data()
    workspace = Path.cwd() / "data" / "witch.json"
    if workspace.exists():
        return workspace
    return _user_data()


def gateway_base_url() -> str:
    return f"http://{os.environ.get('WITCH_HOST', '127.0.0.1')}:{os.environ.get('WITCH_PORT', '43187')}/v1"

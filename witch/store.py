from __future__ import annotations

import json
import secrets
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from witch.convert import mask_secret
from witch.paths import data_file

DEMO_ID = "demo-echo"
_lock = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _token() -> str:
    return f"witch_{secrets.token_hex(18)}"


def demo_provider() -> dict[str, Any]:
    stamp = _now()
    return {
        "id": DEMO_ID,
        "name": "Witch 回显",
        "kind": "demo",
        "protocol": "openai",
        "authStyle": "bearer",
        "baseUrl": "witch://demo",
        "apiKey": "",
        "models": [{"cursorName": "witch-echo", "upstreamId": "echo"}],
        "notes": "",
        "createdAt": stamp,
        "updatedAt": stamp,
    }


def empty_store() -> dict[str, Any]:
    demo = demo_provider()
    return {
        "gatewayToken": _token(),
        "activeProviderId": demo["id"],
        "providers": [demo],
        "logs": [],
        "cursorSetup": {"copiedBaseUrl": False, "copiedKey": False, "probed": False},
    }


def _sanitize(store: dict[str, Any]) -> dict[str, Any]:
    store.setdefault("gatewayToken", _token())
    store.setdefault("providers", [])
    store.setdefault("logs", [])
    store.setdefault(
        "cursorSetup",
        {"copiedBaseUrl": False, "copiedKey": False, "probed": False},
    )
    ids = {item.get("id") for item in store["providers"]}
    if store.get("activeProviderId") not in ids:
        store["activeProviderId"] = store["providers"][0]["id"] if store["providers"] else None
    return store


def _path() -> Path:
    path = data_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def read_store() -> dict[str, Any]:
    with _lock:
        path = _path()
        if not path.exists():
            store = empty_store()
            path.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
            return store
        store = _sanitize(json.loads(path.read_text(encoding="utf-8")))
        return store


def write_store(store: dict[str, Any]) -> None:
    with _lock:
        path = _path()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)


def to_public(store: dict[str, Any]) -> dict[str, Any]:
    providers = []
    for item in store.get("providers", []):
        row = {k: v for k, v in item.items() if k != "apiKey"}
        key = item.get("apiKey") or ""
        row["apiKeyMasked"] = mask_secret(key)
        row["hasApiKey"] = bool(key) or item.get("kind") == "demo"
        providers.append(row)
    return {
        "gatewayToken": store.get("gatewayToken", ""),
        "activeProviderId": store.get("activeProviderId"),
        "providers": providers,
        "logs": store.get("logs", []),
        "cursorSetup": store.get("cursorSetup")
        or {"copiedBaseUrl": False, "copiedKey": False, "probed": False},
    }


def get_active() -> tuple[dict[str, Any], dict[str, Any] | None]:
    store = read_store()
    provider = next(
        (item for item in store["providers"] if item["id"] == store.get("activeProviderId")),
        None,
    )
    return store, provider


def create_provider(data: dict[str, Any], activate: bool = True) -> dict[str, Any]:
    store = read_store()
    stamp = _now()
    provider = {
        "id": f"p_{secrets.token_hex(8)}",
        "name": (data.get("name") or "").strip(),
        "kind": "relay",
        "protocol": data.get("protocol") or "openai",
        "authStyle": data.get("authStyle") or "bearer",
        "baseUrl": (data.get("baseUrl") or "").strip(),
        "apiKey": (data.get("apiKey") or "").strip(),
        "models": [
            {
                "cursorName": m.get("cursorName", "").strip(),
                "upstreamId": (m.get("upstreamId") or m.get("cursorName") or "").strip(),
            }
            for m in data.get("models") or []
            if (m.get("cursorName") or "").strip()
        ],
        "notes": (data.get("notes") or "").strip(),
        "createdAt": stamp,
        "updatedAt": stamp,
    }
    store["providers"].insert(0, provider)
    if activate:
        store["activeProviderId"] = provider["id"]
    write_store(store)
    return to_public(store)


def patch_provider(provider_id: str, data: dict[str, Any]) -> dict[str, Any]:
    store = read_store()
    provider = next((item for item in store["providers"] if item["id"] == provider_id), None)
    if not provider:
        raise ValueError("找不到这个中转站")
    for key in ("name", "protocol", "authStyle", "baseUrl", "notes"):
        if key in data and data[key] is not None:
            provider[key] = data[key].strip() if isinstance(data[key], str) else data[key]
    if data.get("apiKey"):
        provider["apiKey"] = str(data["apiKey"]).strip()
    if "models" in data and data["models"] is not None:
        provider["models"] = [
            {
                "cursorName": m.get("cursorName", "").strip(),
                "upstreamId": (m.get("upstreamId") or m.get("cursorName") or "").strip(),
            }
            for m in data["models"]
            if (m.get("cursorName") or "").strip()
        ]
    provider["updatedAt"] = _now()
    write_store(store)
    return to_public(store)


def remove_provider(provider_id: str) -> dict[str, Any]:
    store = read_store()
    store["providers"] = [item for item in store["providers"] if item["id"] != provider_id]
    if store.get("activeProviderId") == provider_id:
        store["activeProviderId"] = store["providers"][0]["id"] if store["providers"] else None
    write_store(store)
    return to_public(store)


def activate_provider(provider_id: str) -> dict[str, Any]:
    store = read_store()
    if not any(item["id"] == provider_id for item in store["providers"]):
        raise ValueError("找不到这个中转站")
    store["activeProviderId"] = provider_id
    write_store(store)
    return to_public(store)


def reorder_providers(ordered_ids: list[str]) -> dict[str, Any]:
    store = read_store()
    by_id = {item["id"]: item for item in store["providers"]}
    ordered = [by_id[item_id] for item_id in ordered_ids if item_id in by_id]
    leftover = [item for item in store["providers"] if item["id"] not in set(ordered_ids)]
    store["providers"] = ordered + leftover
    write_store(store)
    return to_public(store)


def move_provider(provider_id: str, delta: int) -> dict[str, Any]:
    store = read_store()
    ids = [item["id"] for item in store["providers"]]
    try:
        index = ids.index(provider_id)
    except ValueError as error:
        raise ValueError("找不到这个中转站") from error
    target = index + int(delta)
    if target < 0 or target >= len(ids):
        return to_public(store)
    ids[index], ids[target] = ids[target], ids[index]
    return reorder_providers(ids)


def duplicate_provider(provider_id: str) -> dict[str, Any]:
    store = read_store()
    source = next((item for item in store["providers"] if item["id"] == provider_id), None)
    if not source:
        raise ValueError("找不到这个中转站")
    copy = deepcopy(source)
    copy["id"] = f"p_{secrets.token_hex(8)}"
    copy["name"] = f"{source['name']} 副本"
    copy["kind"] = "relay"
    copy["createdAt"] = _now()
    copy["updatedAt"] = copy["createdAt"]
    copy.pop("lastTest", None)
    index = next(i for i, item in enumerate(store["providers"]) if item["id"] == provider_id)
    store["providers"].insert(index + 1, copy)
    write_store(store)
    return to_public(store)


def restore_demo() -> dict[str, Any]:
    store = read_store()
    if not any(item["id"] == DEMO_ID for item in store["providers"]):
        store["providers"].append(demo_provider())
        if not store.get("activeProviderId"):
            store["activeProviderId"] = DEMO_ID
        write_store(store)
    return to_public(store)


def rotate_token() -> dict[str, Any]:
    store = read_store()
    store["gatewayToken"] = _token()
    write_store(store)
    return to_public(store)


def append_log(entry: dict[str, Any]) -> None:
    store = read_store()
    store["logs"].insert(
        0,
        {"id": f"log_{secrets.token_hex(6)}", "at": _now(), **entry},
    )
    store["logs"] = store["logs"][:80]
    write_store(store)


def clear_logs() -> dict[str, Any]:
    store = read_store()
    store["logs"] = []
    write_store(store)
    return to_public(store)


def record_last_test(provider_id: str, result: dict[str, Any]) -> dict[str, Any]:
    store = read_store()
    provider = next((item for item in store["providers"] if item["id"] == provider_id), None)
    if not provider:
        raise ValueError("找不到这个中转站")
    provider["lastTest"] = {**result, "at": _now()}
    provider["updatedAt"] = _now()
    write_store(store)
    return to_public(store)


def patch_setup(patch: dict[str, bool]) -> dict[str, Any]:
    store = read_store()
    store["cursorSetup"] = {**(store.get("cursorSetup") or {}), **patch}
    write_store(store)
    return to_public(store)


def export_backup() -> dict[str, Any]:
    store = read_store()
    return {
        "version": 1,
        "exportedAt": _now(),
        "providers": [item for item in store["providers"] if item.get("kind") == "relay"],
    }


def import_backup(payload: dict[str, Any]) -> dict[str, Any]:
    incoming = payload.get("providers")
    if not isinstance(incoming, list) or not incoming:
        raise ValueError("备份里没有可导入的中转站。")
    store = read_store()
    added = 0
    for raw in incoming:
        if not isinstance(raw, dict) or raw.get("kind") == "demo":
            continue
        name = str(raw.get("name") or "").strip()
        base_url = str(raw.get("baseUrl") or "").strip()
        if not name or not base_url:
            continue
        exists = next(
            (
                item
                for item in store["providers"]
                if item.get("kind") == "relay"
                and item.get("name") == name
                and item.get("baseUrl") == base_url
            ),
            None,
        )
        if exists:
            if raw.get("apiKey"):
                exists["apiKey"] = str(raw["apiKey"])
            if raw.get("models"):
                exists["models"] = raw["models"]
            exists["updatedAt"] = _now()
        else:
            create_provider(
                {
                    "name": name,
                    "protocol": raw.get("protocol") or "openai",
                    "authStyle": raw.get("authStyle") or "bearer",
                    "baseUrl": base_url,
                    "apiKey": raw.get("apiKey") or "",
                    "models": raw.get("models") or [],
                    "notes": raw.get("notes") or "从备份导入",
                },
                activate=False,
            )
            store = read_store()
        added += 1
    if not added:
        raise ValueError("备份里没有有效站点。")
    return to_public(read_store())

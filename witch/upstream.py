from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from witch import __version__
from witch.convert import auth_headers, normalize_base_url


def models_url(base_url: str, protocol: str) -> str:
    base = normalize_base_url(base_url)
    if protocol == "anthropic" and not re.search(r"/(v1|anthropic)$", base, re.I):
        return f"{base}/v1/models"
    return f"{base}/models"


def model_ids_from_payload(payload: object) -> list[str]:
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        raw = payload.get("data")
        if raw is None:
            raw = payload.get("models")
        if raw is None and (payload.get("id") or payload.get("name")):
            raw = [payload]
        items = raw if isinstance(raw, list) else []
    else:
        items = []
    found: list[str] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, dict):
            name = str(item.get("id") or item.get("name") or item.get("model") or "").strip()
        else:
            name = ""
        if not name or name in seen:
            continue
        seen.add(name)
        found.append(name)
    return found


def list_model_ids(
    base_url: str,
    api_key: str,
    auth_style: str = "bearer",
    protocol: str = "openai",
    timeout: float = 20,
) -> list[str]:
    base_url = (base_url or "").strip()
    api_key = (api_key or "").strip()
    if not base_url.startswith("http"):
        raise ValueError("先填请求地址")
    if not api_key:
        raise ValueError("先填 API Key")
    headers = auth_headers(api_key, auth_style or "bearer", protocol or "openai")
    headers.pop("content-type", None)
    headers["accept"] = "application/json"
    headers["user-agent"] = f"Witch/{__version__}"
    request = Request(models_url(base_url, protocol or "openai"), headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(2_000_000)
    except HTTPError as error:
        if error.code in {401, 403}:
            raise ValueError(f"Key 被拒绝（{error.code}）") from error
        if error.code == 404:
            raise ValueError("这个地址没有模型列表（404）") from error
        raise ValueError(f"获取失败（{error.code}）") from error
    except URLError as error:
        reason = str(error.reason)
        if "timed out" in reason.lower():
            raise ValueError("获取模型超时") from error
        raise ValueError("连不上这个地址") from error
    except TimeoutError as error:
        raise ValueError("获取模型超时") from error
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("返回的不是模型列表") from error
    ids = model_ids_from_payload(payload)
    if not ids:
        raise ValueError("这个地址没有返回模型")
    return ids

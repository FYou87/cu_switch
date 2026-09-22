from __future__ import annotations

import json
import re

from witch.convert import normalize_base_url

KEY_RE = re.compile(r"(?:sk-|ccsk-|witch_)[A-Za-z0-9_\-]{8,}")
URL_RE = re.compile(r"https?://[^\s\"'`<>]+", re.I)


def _env(text: str, names: list[str]) -> str:
    for name in names:
        match = re.search(rf"(?:export\s+)?{name}\s*=\s*['\"]?([^\s'\"]+)", text, re.I)
        if match:
            return match.group(1).strip()
    return ""


def _embedded_json(text: str) -> dict | None:
    text = text.strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _safe_name(model_id: str) -> str:
    clean = model_id.strip()
    if not clean:
        return ""
    if re.match(r"^(gpt-|o\d|claude-|gemini-|composer|grok-|kimi-|muse-)", clean, re.I) and not re.search(
        r"relay|witch|custom", clean, re.I
    ):
        return f"{clean}-relay"
    return clean


def parse_relay_text(text: str) -> dict:
    raw = text.strip()
    if not raw:
        raise ValueError("先把中转站给的地址、Key 贴进来。")
    blob = _embedded_json(raw) or {}
    openai_base = _env(raw, ["OPENAI_BASE_URL", "OPENAI_API_BASE", "OPENAI_API_BASE_URL"])
    anthropic_base = _env(raw, ["ANTHROPIC_BASE_URL", "ANTHROPIC_API_BASE"])
    openai_key = _env(raw, ["OPENAI_API_KEY", "OPENAI_AUTH_TOKEN"])
    anthropic_key = _env(raw, ["ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"])
    urls = [normalize_base_url(re.sub(r"[),.;]+$", "", item)) for item in URL_RE.findall(raw)]
    keys = KEY_RE.findall(raw)
    protocol = "anthropic" if anthropic_base or blob.get("protocol") == "anthropic" else "openai"
    base_url = normalize_base_url(
        str(blob.get("baseUrl") or blob.get("base_url") or "")
        or (anthropic_base if protocol == "anthropic" else openai_base)
        or anthropic_base
        or openai_base
        or (urls[0] if urls else "")
    )
    api_key = str(blob.get("apiKey") or blob.get("api_key") or "") or anthropic_key or openai_key or (
        keys[0] if keys else ""
    )
    if not base_url:
        raise ValueError("没读到 Base URL。需要一行 https://… 地址。")
    if not api_key:
        raise ValueError("没读到 API Key。一般是 sk- 开头。")
    models: list[dict[str, str]] = []
    for match in re.finditer(r"(?:models?|主模型|模型)\s*[:=]\s*([A-Za-z0-9._:/-]+)", raw, re.I):
        upstream = match.group(1).rstrip(",;")
        models.append({"cursorName": _safe_name(upstream), "upstreamId": upstream})
    if isinstance(blob.get("models"), list):
        models = []
        for item in blob["models"]:
            if isinstance(item, str):
                models.append({"cursorName": _safe_name(item), "upstreamId": item})
            elif isinstance(item, dict):
                upstream = str(item.get("upstreamId") or item.get("id") or item.get("model") or "")
                cursor = str(item.get("cursorName") or _safe_name(upstream))
                if cursor and upstream:
                    models.append({"cursorName": cursor, "upstreamId": upstream})
    if not models:
        models = [{"cursorName": "relay-main", "upstreamId": "default"}]
    try:
        name = (blob.get("name") or "").strip() or _env(raw, ["name", "NAME"]) or (
            re.sub(r"^api\.", "", re.sub(r"^https?://", "", base_url).split("/")[0])
        )
    except Exception:
        name = "未命名中转"
    return {
        "name": name or "未命名中转",
        "protocol": protocol,
        "authStyle": "both" if protocol == "anthropic" or anthropic_key else "bearer",
        "baseUrl": base_url,
        "apiKey": api_key,
        "models": models,
        "notes": "",
    }

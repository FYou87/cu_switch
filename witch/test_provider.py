from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from witch.convert import anthropic_messages_url, auth_headers, normalize_base_url


def test_provider(provider: dict) -> dict:
    if provider.get("kind") == "demo":
        return {"ok": True, "status": 200, "message": "回显站点在本机，随时可用。"}
    if not (provider.get("baseUrl") or "").strip():
        return {"ok": False, "status": 400, "message": "还没填 Base URL。"}
    if not (provider.get("apiKey") or "").strip():
        return {"ok": False, "status": 400, "message": "还没填 API Key。"}
    model = (provider.get("models") or [{"upstreamId": "gpt-4o-mini"}])[0].get("upstreamId") or "gpt-4o-mini"
    try:
        if provider.get("protocol") == "anthropic":
            request = Request(
                anthropic_messages_url(provider["baseUrl"]),
                data=json.dumps(
                    {"model": model, "max_tokens": 16, "messages": [{"role": "user", "content": "ping"}]}
                ).encode("utf-8"),
                headers=auth_headers(provider["apiKey"], provider.get("authStyle") or "both", "anthropic"),
                method="POST",
            )
            with urlopen(request, timeout=20) as response:
                return {"ok": True, "status": response.status, "message": f"Anthropic 端点正常（{response.status}）。"}
        listed = Request(
            f"{normalize_base_url(provider['baseUrl'])}/models",
            headers=auth_headers(provider["apiKey"], provider.get("authStyle") or "bearer", "openai"),
        )
        try:
            with urlopen(listed, timeout=20) as response:
                if 200 <= response.status < 300:
                    return {"ok": True, "status": response.status, "message": "OpenAI 兼容端点正常，已读到 /models。"}
        except HTTPError:
            pass
        request = Request(
            f"{normalize_base_url(provider['baseUrl'])}/chat/completions",
            data=json.dumps(
                {"model": model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 16}
            ).encode("utf-8"),
            headers=auth_headers(provider["apiKey"], provider.get("authStyle") or "bearer", "openai"),
            method="POST",
        )
        with urlopen(request, timeout=20) as response:
            return {"ok": True, "status": response.status, "message": "OpenAI 兼容端点正常，chat/completions 已通。"}
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:280]
        return {"ok": False, "status": error.code, "message": detail or error.reason}
    except URLError as error:
        return {"ok": False, "status": 502, "message": str(error.reason)}
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "status": 502, "message": str(error)}

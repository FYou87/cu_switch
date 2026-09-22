from __future__ import annotations

import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from witch.convert import anthropic_messages_url, auth_headers, normalize_base_url


def test_provider(provider: dict) -> dict:
    started = time.perf_counter()

    def finish(ok: bool, status: int, message: str) -> dict:
        return {
            "ok": ok,
            "status": status,
            "message": message,
            "ms": max(1, int((time.perf_counter() - started) * 1000)),
        }

    if provider.get("kind") == "demo":
        return finish(True, 200, "回显站点在本机，随时可用。")
    if not (provider.get("baseUrl") or "").strip():
        return finish(False, 400, "还没填 Base URL。")
    if not (provider.get("apiKey") or "").strip():
        return finish(False, 400, "还没填 API Key。")
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
                return finish(True, response.status, f"Anthropic 端点正常（{response.status}）。")
        listed = Request(
            f"{normalize_base_url(provider['baseUrl'])}/models",
            headers=auth_headers(provider["apiKey"], provider.get("authStyle") or "bearer", "openai"),
        )
        try:
            with urlopen(listed, timeout=20) as response:
                if 200 <= response.status < 300:
                    return finish(True, response.status, "OpenAI 兼容端点正常，已读到 /models。")
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
            return finish(True, response.status, "OpenAI 兼容端点正常，chat/completions 已通。")
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:280]
        return finish(False, error.code, detail or error.reason)
    except URLError as error:
        return finish(False, 502, str(error.reason))
    except Exception as error:  # noqa: BLE001
        return finish(False, 502, str(error))

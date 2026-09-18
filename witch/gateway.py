from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from witch import GATEWAY_HOST, GATEWAY_PORT
from witch.convert import (
    anthropic_message_to_chat,
    anthropic_messages_url,
    auth_headers,
    chat_completions_url,
    chat_to_anthropic,
    last_user_text,
    openai_chunk,
    resolve_upstream_model,
    responses_to_chat,
    sse,
)
from witch.store import append_log, get_active

_server: ThreadingHTTPServer | None = None
_thread: threading.Thread | None = None


def _json(handler: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("content-type", "application/json; charset=utf-8")
    handler.send_header("access-control-allow-origin", "*")
    handler.send_header("content-length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def _bearer(handler: BaseHTTPRequestHandler) -> str:
    header = handler.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header.split(" ", 1)[1].strip()
    return (handler.headers.get("x-api-key") or handler.headers.get("api-key") or "").strip()


def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("content-length") or 0)
    if not length:
        return {}
    try:
        return json.loads(handler.rfile.read(length).decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return {}


def _demo_chat(model: str, provider_name: str, messages: Any, stream: bool):
    user = last_user_text(messages)
    text = f"Witch 回显已接通。当前站点「{provider_name}」，模型 {model}。你刚才说：{user[:240] or '（空）'}"
    chat_id = f"chatcmpl_demo_{int(time.time() * 1000)}"
    if not stream:
        return {
            "id": chat_id,
            "object": "chat.completion",
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
        }
    chunks = [
        sse(openai_chunk(chat_id, model, role="assistant", content="")),
        *[sse(openai_chunk(chat_id, model, content=text[i : i + 18])) for i in range(0, len(text), 18)],
        sse(openai_chunk(chat_id, model, content=None, finish_reason="stop")),
        sse("[DONE]"),
    ]
    return b"".join(chunks)


def _forward(url: str, headers: dict[str, str], payload: dict[str, Any]):
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    return urlopen(request, timeout=120)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("access-control-allow-origin", "*")
        self.send_header("access-control-allow-headers", "*")
        self.send_header("access-control-allow-methods", "GET,POST,OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in {"/v1/models", "/api/v1/models"}:
            store, provider = get_active()
            if _bearer(self) != store.get("gatewayToken"):
                return _json(self, 401, {"error": {"message": "网关密钥不对。"}})
            models = [
                {
                    "id": item["cursorName"],
                    "object": "model",
                    "owned_by": (provider or {}).get("name") or "witch",
                }
                for item in (provider or {}).get("models") or []
            ]
            return _json(self, 200, {"object": "list", "data": models})
        if path in {"/", "/health"}:
            return _json(self, 200, {"ok": True, "app": "witch-desktop"})
        return _json(self, 404, {"error": {"message": "not found"}})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in {
            "/v1/chat/completions",
            "/api/v1/chat/completions",
            "/v1/responses",
            "/api/v1/responses",
        }:
            self._handle_chat(path)
            return
        _json(self, 404, {"error": {"message": "not found"}})

    def _handle_chat(self, path: str) -> None:
        started = time.time()
        store, provider = get_active()
        body = _read_json(self)
        chat = responses_to_chat(body) if "responses" in path else body
        requested = str(chat.get("model") or body.get("model") or "")
        stream = bool(chat.get("stream") or body.get("stream"))
        token = _bearer(self)

        def done(status: int, error: str | None) -> None:
            append_log(
                {
                    "path": "/v1/responses" if "responses" in path else "/v1/chat/completions",
                    "providerId": (provider or {}).get("id"),
                    "providerName": (provider or {}).get("name") or "未启用",
                    "model": requested,
                    "status": status,
                    "ms": int((time.time() - started) * 1000),
                    "streamed": stream,
                    "error": error,
                }
            )

        if token != store.get("gatewayToken"):
            done(401, "网关密钥不对")
            return _json(self, 401, {"error": {"message": "网关密钥不对。到 Witch 窗口复制网关密钥。"}})
        if not provider:
            done(409, "没有启用中的中转站")
            return _json(self, 409, {"error": {"message": "先在 Witch 里启用一个中转站。"}})

        model = resolve_upstream_model(requested, provider.get("models") or [])
        try:
            if provider.get("kind") == "demo":
                result = _demo_chat(requested or model, provider["name"], chat.get("messages"), stream)
                if stream:
                    raw = result if isinstance(result, bytes) else b""
                    self.send_response(200)
                    self.send_header("content-type", "text/event-stream; charset=utf-8")
                    self.send_header("cache-control", "no-cache")
                    self.send_header("access-control-allow-origin", "*")
                    self.send_header("content-length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    done(200, None)
                    return
                done(200, None)
                return _json(self, 200, result)
            if not provider.get("apiKey"):
                done(400, "中转站没填 Key")
                return _json(self, 400, {"error": {"message": f"「{provider['name']}」还没填 API Key。"}})

            if provider.get("protocol") == "anthropic":
                payload = chat_to_anthropic(chat, model)
                url = anthropic_messages_url(provider["baseUrl"])
                headers = auth_headers(provider["apiKey"], provider.get("authStyle") or "both", "anthropic")
            else:
                payload = {**chat, "model": model, "stream": stream}
                url = chat_completions_url(provider["baseUrl"])
                headers = auth_headers(provider["apiKey"], provider.get("authStyle") or "bearer", "openai")

            try:
                upstream = _forward(url, headers, payload)
            except HTTPError as error:
                detail = error.read().decode("utf-8", errors="replace")[:240]
                done(error.code, detail or error.reason)
                return _json(
                    self,
                    error.code,
                    {"error": {"message": f"中转站返回 {error.code}。{detail or error.reason}"}},
                )

            if stream:
                self.send_response(200)
                self.send_header("content-type", "text/event-stream; charset=utf-8")
                self.send_header("cache-control", "no-cache")
                self.send_header("access-control-allow-origin", "*")
                self.end_headers()
                if provider.get("protocol") == "anthropic":
                    self._pipe_anthropic_stream(upstream, requested or model)
                else:
                    while True:
                        chunk = upstream.read(4096)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                done(200, None)
                return

            data = json.loads(upstream.read().decode("utf-8"))
            if provider.get("protocol") == "anthropic":
                data = anthropic_message_to_chat(data, requested or model)
            done(200, None)
            return _json(self, 200, data)
        except URLError as error:
            done(502, str(error.reason))
            return _json(self, 502, {"error": {"message": f"连不上中转站：{error.reason}"}})
        except Exception as error:  # noqa: BLE001
            done(502, str(error))
            return _json(self, 502, {"error": {"message": f"连不上中转站：{error}"}})

    def _pipe_anthropic_stream(self, upstream, model: str) -> None:
        chat_id = f"chatcmpl_{int(time.time() * 1000)}"
        buffer = ""
        while True:
            piece = upstream.read(1024)
            if not piece:
                break
            buffer += piece.decode("utf-8", errors="replace")
            while "\n\n" in buffer:
                raw, buffer = buffer.split("\n\n", 1)
                event = ""
                data_lines = []
                for line in raw.splitlines():
                    if line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].strip())
                if not data_lines:
                    continue
                try:
                    payload = json.loads("\n".join(data_lines))
                except json.JSONDecodeError:
                    continue
                kind = event or payload.get("type") or ""
                if kind == "message_start":
                    self.wfile.write(sse(openai_chunk(chat_id, model, role="assistant", content="")))
                elif kind == "content_block_delta":
                    delta = payload.get("delta") or {}
                    if delta.get("type") == "text_delta" and delta.get("text"):
                        self.wfile.write(sse(openai_chunk(chat_id, model, content=delta["text"])))
                elif kind == "message_delta":
                    reason = "tool_calls" if (payload.get("delta") or {}).get("stop_reason") == "tool_use" else "stop"
                    self.wfile.write(sse(openai_chunk(chat_id, model, content=None, finish_reason=reason)))
        self.wfile.write(sse("[DONE]"))


def start_gateway(host: str | None = None, port: int | None = None) -> None:
    global _server, _thread
    if _server:
        return
    host = host or os.environ.get("WITCH_HOST", GATEWAY_HOST)
    port = int(os.environ.get("WITCH_PORT", GATEWAY_PORT) if port is None else port)
    try:
        _server = ThreadingHTTPServer((host, port), Handler)
    except OSError as error:
        raise RuntimeError(f"网关端口 {port} 已被占用。先关掉另一份 Witch。") from error
    _thread = threading.Thread(target=_server.serve_forever, name="witch-gateway", daemon=True)
    _thread.start()


def stop_gateway() -> None:
    global _server, _thread
    if _server:
        _server.shutdown()
        _server.server_close()
    _server = None
    _thread = None

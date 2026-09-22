from __future__ import annotations

import json
import re
from typing import Any


def normalize_base_url(url: str) -> str:
    return re.sub(
        r"/(chat/completions|responses|messages)$",
        "",
        url.strip().rstrip("/"),
        flags=re.I,
    )


def chat_completions_url(base_url: str) -> str:
    return f"{normalize_base_url(base_url)}/chat/completions"


def anthropic_messages_url(base_url: str) -> str:
    base = normalize_base_url(base_url)
    if re.search(r"/v1$", base, re.I) or re.search(r"/anthropic$", base, re.I):
        return f"{base}/messages"
    return f"{base}/v1/messages"


def resolve_upstream_model(requested: str, routes: list[dict[str, str]]) -> str:
    aliases = [requested, re.sub(r"^(custom-|witch-)", "", requested)]
    for name in aliases:
        for route in routes:
            if route.get("cursorName") == name or route.get("upstreamId") == name:
                return route["upstreamId"]
    return requested


def mask_secret(value: str) -> str:
    text = value.strip()
    if not text:
        return "未填写"
    if len(text) <= 8:
        return "••••"
    return f"{text[:4]}…{text[-4:]}"


def content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                if isinstance(part.get("text"), str):
                    parts.append(part["text"])
                elif isinstance(part.get("content"), str):
                    parts.append(part["content"])
        return "\n".join(p for p in parts if p)
    if isinstance(content, dict) and isinstance(content.get("text"), str):
        return content["text"]
    return ""


def last_user_text(messages: Any) -> str:
    if not isinstance(messages, list):
        return ""
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "user":
            return content_to_text(message.get("content"))
    return ""


def responses_to_chat(body: dict[str, Any]) -> dict[str, Any]:
    if isinstance(body.get("messages"), list):
        out = dict(body)
        out["max_tokens"] = body.get("max_tokens") or body.get("max_output_tokens") or 4096
        return out
    messages: list[dict[str, Any]] = []
    if isinstance(body.get("instructions"), str) and body["instructions"].strip():
        messages.append({"role": "system", "content": body["instructions"]})
    incoming = body.get("input")
    if isinstance(incoming, str):
        messages.append({"role": "user", "content": incoming})
    elif isinstance(incoming, list):
        for item in incoming:
            if isinstance(item, str):
                messages.append({"role": "user", "content": item})
            elif isinstance(item, dict):
                messages.append(
                    {
                        "role": item.get("role") or "user",
                        "content": item.get("content") or item.get("text") or "",
                    }
                )
    return {
        "model": body.get("model"),
        "messages": messages,
        "stream": body.get("stream"),
        "temperature": body.get("temperature"),
        "max_tokens": body.get("max_output_tokens") or body.get("max_tokens") or 4096,
        "tools": body.get("tools"),
    }


def _to_anthropic_content(content: Any) -> Any:
    if isinstance(content, str) or content is None:
        return content or ""
    if not isinstance(content, list):
        return content_to_text(content)
    blocks = []
    for part in content:
        if isinstance(part, str):
            blocks.append({"type": "text", "text": part})
        elif isinstance(part, dict) and (
            part.get("type") == "text" or isinstance(part.get("text"), str)
        ):
            blocks.append({"type": "text", "text": str(part.get("text") or "")})
        else:
            blocks.append({"type": "text", "text": content_to_text(part)})
    return blocks


def chat_to_anthropic(body: dict[str, Any], model: str) -> dict[str, Any]:
    incoming = body.get("messages") if isinstance(body.get("messages"), list) else []
    system_parts: list[str] = []
    converted: list[dict[str, Any]] = []
    for raw in incoming:
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("role") or "user")
        if role in {"system", "developer"}:
            text = content_to_text(raw.get("content"))
            if text:
                system_parts.append(text)
            continue
        if role == "tool":
            converted.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": str(raw.get("tool_call_id") or raw.get("id") or ""),
                            "content": content_to_text(raw.get("content")),
                        }
                    ],
                }
            )
            continue
        if role == "assistant" and isinstance(raw.get("tool_calls"), list):
            blocks: list[dict[str, Any]] = []
            text = content_to_text(raw.get("content"))
            if text:
                blocks.append({"type": "text", "text": text})
            for call in raw["tool_calls"]:
                fn = (call or {}).get("function") or {}
                try:
                    payload = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    payload = {}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call.get("id"),
                        "name": fn.get("name"),
                        "input": payload,
                    }
                )
            converted.append({"role": "assistant", "content": blocks})
            continue
        if role in {"user", "assistant"}:
            converted.append({"role": role, "content": _to_anthropic_content(raw.get("content"))})
    tools = []
    for tool in body.get("tools") or []:
        if not isinstance(tool, dict):
            continue
        fn = tool.get("function") if isinstance(tool.get("function"), dict) else None
        if tool.get("type") == "function" and fn:
            tools.append(
                {
                    "name": fn.get("name"),
                    "description": fn.get("description"),
                    "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
                }
            )
        elif tool.get("name") and tool.get("input_schema"):
            tools.append(tool)
    return {
        "model": model,
        "max_tokens": int(body.get("max_tokens") or body.get("max_output_tokens") or 4096),
        "system": "\n\n".join(system_parts) or None,
        "messages": converted or [{"role": "user", "content": "Hello"}],
        "stream": bool(body.get("stream")),
        "temperature": body.get("temperature"),
        "tools": tools or None,
    }


def anthropic_message_to_chat(data: dict[str, Any], model: str) -> dict[str, Any]:
    blocks = data.get("content") if isinstance(data.get("content"), list) else []
    text = "".join(
        str(block.get("text") or "")
        for block in blocks
        if isinstance(block, dict) and block.get("type") == "text"
    )
    tool_calls = []
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            tool_calls.append(
                {
                    "id": block.get("id"),
                    "type": "function",
                    "function": {
                        "name": block.get("name"),
                        "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False),
                    },
                }
            )
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else None
    return {
        "id": str(data.get("id") or "chatcmpl_witch"),
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": text or None,
                    "tool_calls": tool_calls or None,
                },
                "finish_reason": "tool_calls" if data.get("stop_reason") == "tool_use" else "stop",
            }
        ],
        "usage": {
            "prompt_tokens": (usage or {}).get("input_tokens", 0),
            "completion_tokens": (usage or {}).get("output_tokens", 0),
            "total_tokens": (usage or {}).get("input_tokens", 0)
            + (usage or {}).get("output_tokens", 0),
        }
        if usage
        else None,
    }


def auth_headers(api_key: str, style: str, protocol: str) -> dict[str, str]:
    headers = {"content-type": "application/json"}
    if style in {"bearer", "both"}:
        headers["authorization"] = f"Bearer {api_key}"
    if style in {"x-api-key", "both"} or protocol == "anthropic":
        headers["x-api-key"] = api_key
    if protocol == "anthropic":
        headers["anthropic-version"] = "2023-06-01"
    return headers


def sse(data: Any, event: str | None = None) -> bytes:
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    body = f"data: {payload}\n\n"
    if event:
        body = f"event: {event}\n{body}"
    return body.encode("utf-8")


def openai_chunk(
    chat_id: str,
    model: str,
    content: Any = None,
    role: str | None = None,
    finish_reason: str | None = None,
    tool_calls: Any = None,
) -> dict[str, Any]:
    delta: dict[str, Any] = {}
    if role:
        delta["role"] = role
    if content is not None:
        delta["content"] = content
    if tool_calls is not None:
        delta["tool_calls"] = tool_calls
    return {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }

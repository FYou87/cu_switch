import unittest

from witch.convert import (
    chat_to_anthropic,
    mask_secret,
    normalize_base_url,
    resolve_upstream_model,
    responses_to_chat,
)
from witch.parse_import import parse_relay_text


class ConvertTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(
            normalize_base_url("https://api.example.com/v1/chat/completions/"),
            "https://api.example.com/v1",
        )

    def test_resolve_model(self):
        routes = [{"cursorName": "claude-relay", "upstreamId": "claude-sonnet-4-6"}]
        self.assertEqual(resolve_upstream_model("claude-relay", routes), "claude-sonnet-4-6")
        self.assertEqual(resolve_upstream_model("gpt-x", routes), "gpt-x")

    def test_responses(self):
        chat = responses_to_chat(
            {"model": "witch-echo", "instructions": "be brief", "input": "hello"}
        )
        self.assertEqual(
            chat["messages"],
            [{"role": "system", "content": "be brief"}, {"role": "user", "content": "hello"}],
        )

    def test_anthropic(self):
        body = chat_to_anthropic(
            {
                "messages": [
                    {"role": "system", "content": "rules"},
                    {"role": "user", "content": "hi"},
                ]
            },
            "claude-sonnet-4-6",
        )
        self.assertEqual(body["system"], "rules")
        self.assertEqual(body["max_tokens"], 4096)
        self.assertEqual(body["messages"][0]["role"], "user")

    def test_mask(self):
        self.assertEqual(mask_secret("sk-abcdefghij"), "sk-a…ghij")


class ParseTests(unittest.TestCase):
    def test_anthropic_env(self):
        parsed = parse_relay_text(
            """
export ANTHROPIC_BASE_URL=https://api.example.com
export ANTHROPIC_AUTH_TOKEN=sk-abcdefghijklmnop
model=claude-sonnet-4-6
"""
        )
        self.assertEqual(parsed["protocol"], "anthropic")
        self.assertEqual(parsed["baseUrl"], "https://api.example.com")
        self.assertEqual(parsed["models"][0]["cursorName"], "claude-sonnet-4-6-relay")


if __name__ == "__main__":
    unittest.main()

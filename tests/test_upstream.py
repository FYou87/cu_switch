import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from witch.upstream import list_model_ids, model_ids_from_payload, models_url


class ParseTests(unittest.TestCase):
    def test_openai_and_anthropic_shapes(self):
        self.assertEqual(
            model_ids_from_payload({"object": "list", "data": [{"id": "gpt-4o"}, {"id": "gpt-4o"}, "gpt-4o-mini"]}),
            ["gpt-4o", "gpt-4o-mini"],
        )
        self.assertEqual(
            model_ids_from_payload({"data": [{"id": "claude-sonnet-4-5", "display_name": "Sonnet"}]}),
            ["claude-sonnet-4-5"],
        )
        self.assertEqual(model_ids_from_payload({"models": [{"name": "deepseek-chat"}]}), ["deepseek-chat"])
        self.assertEqual(models_url("https://api.openai.com/v1", "openai"), "https://api.openai.com/v1/models")
        self.assertEqual(models_url("https://api.anthropic.com", "anthropic"), "https://api.anthropic.com/v1/models")
        self.assertEqual(models_url("https://api.anthropic.com/v1/", "anthropic"), "https://api.anthropic.com/v1/models")

    def test_live_list(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.server.seen_auth = self.headers.get("Authorization")
                self.server.seen_path = self.path
                body = json.dumps({"data": [{"id": "alpha"}, {"id": "beta"}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):  # noqa: A003
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_address[1]
        try:
            ids = list_model_ids(f"http://127.0.0.1:{port}/v1", "sk-test", "bearer", "openai", timeout=3)
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(ids, ["alpha", "beta"])
        self.assertEqual(server.seen_auth, "Bearer sk-test")
        self.assertEqual(server.seen_path, "/v1/models")

    def test_rejects_missing_key_and_empty_list(self):
        with self.assertRaises(ValueError):
            list_model_ids("https://api.example.com/v1", "", timeout=1)
        with self.assertRaises(ValueError):
            list_model_ids("witch://demo", "sk-test", timeout=1)


if __name__ == "__main__":
    unittest.main()

import os
import tempfile
import unittest
from pathlib import Path

from witch.store import (
    create_provider,
    move_provider,
    read_store,
    reorder_providers,
    to_public,
)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["WITCH_DATA"] = str(Path(self.tmp.name) / "witch.json")

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("WITCH_DATA", None)

    def test_reorder_and_move(self):
        create_provider(
            {
                "name": "A站",
                "protocol": "openai",
                "authStyle": "bearer",
                "baseUrl": "https://a.example/v1",
                "apiKey": "sk-aaaaaaaa",
                "models": [{"cursorName": "a-relay", "upstreamId": "a"}],
            },
            activate=False,
        )
        create_provider(
            {
                "name": "B站",
                "protocol": "openai",
                "authStyle": "bearer",
                "baseUrl": "https://b.example/v1",
                "apiKey": "sk-bbbbbbbb",
                "models": [{"cursorName": "b-relay", "upstreamId": "b"}],
            },
            activate=False,
        )
        ids = [item["id"] for item in to_public(read_store())["providers"]]
        self.assertGreaterEqual(len(ids), 3)
        reversed_ids = list(reversed(ids))
        reorder_providers(reversed_ids)
        self.assertEqual([item["id"] for item in to_public(read_store())["providers"]], reversed_ids)
        first = reversed_ids[0]
        move_provider(first, 1)
        moved = [item["id"] for item in to_public(read_store())["providers"]]
        self.assertEqual(moved[1], first)


if __name__ == "__main__":
    unittest.main()

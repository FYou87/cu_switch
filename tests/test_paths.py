import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from witch.paths import data_file


class PathTests(unittest.TestCase):
    def test_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "custom.json"
            with mock.patch.dict(os.environ, {"WITCH_DATA": str(target)}):
                self.assertEqual(data_file(), target)

    def test_frozen_skips_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_exe = Path(tmp) / "Witch"
            fake_exe.write_text("")
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("WITCH_DATA", None)
                os.environ.pop("WITCH_PORTABLE", None)
                with mock.patch("witch.paths.sys") as fake_sys:
                    fake_sys.frozen = True
                    fake_sys.platform = "linux"
                    fake_sys.executable = str(fake_exe)
                    path = data_file()
        self.assertTrue(str(path).endswith("/.config/witch/witch.json"))

    def test_portable_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "portable").write_text("witch")
            python = root / "python" / "python.exe"
            python.parent.mkdir()
            python.write_text("")
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("WITCH_DATA", None)
                os.environ.pop("WITCH_PORTABLE", None)
                with mock.patch("witch.paths.sys") as fake_sys:
                    fake_sys.frozen = False
                    fake_sys.platform = "win32"
                    fake_sys.executable = str(python)
                    path = data_file()
            self.assertEqual(path, root / "data" / "witch.json")


if __name__ == "__main__":
    unittest.main()

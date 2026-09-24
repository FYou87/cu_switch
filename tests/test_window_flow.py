import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton

import witch.window as window_mod
from witch.app import apply_dark
from witch.store import create_provider, read_store, to_public
from witch.window import MainWindow, ModeSwitch, ProviderDialog, SettingsDialog


def _names() -> list[str]:
    return [item["name"] for item in to_public(read_store())["providers"]]


def _card_name(card) -> str:
    return card.findChild(QLabel, "providerName").text()


class WindowFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])
        apply_dark(cls._app)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        os.environ["WITCH_DATA"] = str(root / "witch.json")
        os.environ["WITCH_CURSOR_ROOT"] = str(root / "no-cursor")
        os.environ["WITCH_CURSOR_USER_DATA"] = str(root / "cursor-user")
        os.environ["WITCH_CURSOR_NO_LAUNCH"] = "1"
        os.environ["WITCH_PORT"] = "43991"
        self.shots = root / "shots"
        self.shots.mkdir()
        create_provider(
            {
                "name": "甲站",
                "protocol": "openai",
                "authStyle": "bearer",
                "baseUrl": "https://a.example.com/v1",
                "apiKey": "sk-aaaa",
                "models": [{"cursorName": "jia", "upstreamId": "jia-up"}],
            },
            activate=False,
        )
        create_provider(
            {
                "name": "乙站",
                "protocol": "openai",
                "authStyle": "bearer",
                "baseUrl": "https://b.example.com/v1",
                "apiKey": "sk-bbbb",
                "models": [{"cursorName": "yi", "upstreamId": "yi-up"}],
            },
            activate=False,
        )
        self.window = MainWindow()
        self.window.resize(1080, 680)
        self.window.show()
        QTest.qWait(30)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        QTest.qWait(10)
        self.tmp.cleanup()
        for key in (
            "WITCH_DATA",
            "WITCH_CURSOR_ROOT",
            "WITCH_CURSOR_USER_DATA",
            "WITCH_CURSOR_NO_LAUNCH",
            "WITCH_PORT",
        ):
            os.environ.pop(key, None)

    def test_tabs_settings_and_card_actions(self):
        tabs = self.window.findChildren(ModeSwitch, "modeTabs")
        self.assertEqual(len(tabs), 1)
        labels = [button.text() for button in tabs[0].findChildren(QPushButton, "modeTab")]
        self.assertEqual(labels, ["API", "登录"])
        self.assertEqual(tabs[0].mode(), "login")
        header_text = [button.text() for button in self.window.findChildren(QPushButton) if button.text()]
        self.assertNotIn("探测", header_text)

        tips = []
        for card in self.window.board.cards:
            tips.append(
                (
                    card.edit_btn.toolTip(),
                    card.dup_btn.toolTip(),
                    card.test_btn.toolTip(),
                    card.del_btn.toolTip(),
                )
            )
        self.assertTrue(tips)
        for row in tips:
            self.assertEqual(row, ("编辑", "复制", "测速", "删除"))

        seen = {}

        def inspect() -> None:
            dialog = self.window.findChild(SettingsDialog)
            self.assertIsNotNone(dialog)
            seen["edits"] = dialog.findChildren(QLineEdit)
            seen["hint"] = dialog.findChild(QLabel, "formHint").text()
            seen["buttons"] = [button.text() for button in dialog.findChildren(QPushButton)]
            dialog.grab().save(str(self.shots / "settings.png"))
            dialog.accept()

        QTimer.singleShot(20, inspect)
        self.window.open_settings()
        self.assertEqual(seen["edits"], [])
        self.assertIn("供应商卡片", seen["hint"])
        self.assertEqual(seen["buttons"], ["导出备份", "导入备份", "关闭"])
        self.window.grab().save(str(self.shots / "main.png"))

    def test_drag_follows_pointer_before_release_and_persists(self):
        board = self.window.board
        order_before = [_card_name(card) for card in board.cards]
        self.assertEqual(order_before, ["乙站", "甲站", "Witch 回显"])
        card = board.cards[0]
        below = board.cards[1]
        start_y = card.y()
        below_start = below.y()

        QTest.mousePress(card.grip, Qt.LeftButton, Qt.NoModifier, QPoint(8, 8))
        self.assertIs(board._drag, card)
        QTest.mouseMove(card.grip, QPoint(8, 160))
        moved_y = card.y()
        below_target = below._target_y
        self.window.grab().save(str(self.shots / "drag.png"))
        self.assertGreater(moved_y, start_y + 40)
        self.assertLess(below_target, below_start)
        QTest.mouseRelease(card.grip, Qt.LeftButton, Qt.NoModifier, QPoint(8, 160))
        QTest.qWait(250)

        order_after = [_card_name(card) for card in board.cards]
        self.assertNotEqual(order_after, order_before)
        self.assertEqual(_names(), order_after)
        self.assertIsNone(board._drag)
        self.window.grab().save(str(self.shots / "after-drag.png"))

    def test_edit_dialog_save_updates_card_and_json(self):
        target = next(card for card in self.window.board.cards if _card_name(card) == "乙站")
        provider_id = target.provider_id

        def fill_and_save() -> None:
            dialog = self.window.findChild(ProviderDialog)
            self.assertIsNotNone(dialog)
            self.assertEqual(dialog.base_url.text(), "https://b.example.com/v1")
            dialog.name.setText("已保存")
            dialog.base_url.setText("https://saved.example.com/v1")
            dialog.api_key.setText("sk-newkey")
            dialog.grab().save(str(self.shots / "edit.png"))
            save = next(button for button in dialog.findChildren(QPushButton) if button.text() == "保存")
            save.click()

        QTimer.singleShot(30, fill_and_save)
        self.window.edit_provider(provider_id)

        shown = next(card for card in self.window.board.cards if card.provider_id == provider_id)
        self.assertEqual(_card_name(shown), "已保存")
        self.assertEqual(shown.findChild(QLabel, "providerUrl").text(), "https://saved.example.com/v1")
        raw = next(item for item in read_store()["providers"] if item["id"] == provider_id)
        self.assertEqual(raw["name"], "已保存")
        self.assertEqual(raw["baseUrl"], "https://saved.example.com/v1")
        self.assertEqual(raw["apiKey"], "sk-newkey")
        self.assertEqual(raw["kind"], "relay")
        self.window.grab().save(str(self.shots / "after-save.png"))

    def test_blank_form_stays_open_and_does_not_write(self):
        target = next(card for card in self.window.board.cards if _card_name(card) == "甲站")
        before = next(item for item in read_store()["providers"] if item["id"] == target.provider_id)
        original_warning = window_mod.QMessageBox.warning
        window_mod.QMessageBox.warning = staticmethod(lambda *args, **kwargs: QMessageBox.Ok)

        def clear_and_save() -> None:
            dialog = self.window.findChild(ProviderDialog)
            dialog.name.clear()
            dialog.base_url.clear()
            save = next(button for button in dialog.findChildren(QPushButton) if button.text() == "保存")
            save.click()
            self.assertEqual(dialog.result(), 0)
            self.assertTrue(dialog.isVisible())
            dialog.reject()

        try:
            QTimer.singleShot(30, clear_and_save)
            self.window.edit_provider(target.provider_id)
        finally:
            window_mod.QMessageBox.warning = original_warning

        after = next(item for item in read_store()["providers"] if item["id"] == target.provider_id)
        self.assertEqual(after["name"], before["name"])
        self.assertEqual(after["baseUrl"], before["baseUrl"])
        self.assertEqual(after["apiKey"], before["apiKey"])
        self.assertFalse(self.window.findChild(ProviderDialog).isVisible())

    def test_demo_edit_keeps_dialog_url_blank_until_http_saved(self):
        demo = next(card for card in self.window.board.cards if card.provider_id == "demo-echo")
        self.assertEqual(demo.findChild(QLabel, "providerUrl").text(), "本机回显")

        def fill() -> None:
            dialog = self.window.findChild(ProviderDialog)
            self.assertEqual(dialog.base_url.text(), "")
            dialog.base_url.setText("https://relay.example/v1")
            dialog.api_key.setText("sk-demo-saved")
            next(button for button in dialog.findChildren(QPushButton) if button.text() == "保存").click()

        QTimer.singleShot(30, fill)
        self.window.edit_provider("demo-echo")
        raw = next(item for item in read_store()["providers"] if item["id"] == "demo-echo")
        self.assertEqual(raw["kind"], "relay")
        self.assertEqual(raw["baseUrl"], "https://relay.example/v1")
        self.assertEqual(raw["apiKey"], "sk-demo-saved")
        shown = next(card for card in self.window.board.cards if card.provider_id == "demo-echo")
        self.assertEqual(shown.findChild(QLabel, "providerUrl").text(), "https://relay.example/v1")

    def test_fetch_models_into_dropdown_and_save(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.server.seen_auth = self.headers.get("Authorization")
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
        target = next(card for card in self.window.board.cards if _card_name(card) == "乙站")
        holder = {"ok": False, "detail": ""}

        def poll(tries: int = 0) -> None:
            dialog = self.window.findChild(ProviderDialog)
            if dialog is None:
                return
            try:
                if tries == 0:
                    if dialog.findChildren(QPlainTextEdit):
                        raise AssertionError("model mapping is still a text box")
                    if dialog.fetch_btn.text() != "获取模型列表":
                        raise AssertionError(dialog.fetch_btn.text())
                    if dialog.api_key.text():
                        raise AssertionError("key field should stay empty")
                    if dialog.model_picker.chosen_ids() != ["yi-up"]:
                        raise AssertionError(str(dialog.model_picker.chosen_ids()))
                    dialog.base_url.setText(f"http://127.0.0.1:{port}/v1")
                    dialog.fetch_btn.click()
                elif dialog.model_status.text().startswith("获取到"):
                    combo = dialog.model_picker.combo
                    alpha = combo.findData("alpha")
                    if alpha < 0 or combo.findData("beta") < 0 or combo.findData("yi-up") != -1:
                        raise AssertionError(f"combo items missing {[combo.itemText(i) for i in range(combo.count())]}")
                    if server.seen_auth != "Bearer sk-bbbb":
                        raise AssertionError(server.seen_auth or "")
                    combo.activated.emit(alpha)
                    if dialog.model_picker.chosen_ids() != ["yi-up", "alpha"]:
                        raise AssertionError(str(dialog.model_picker.chosen_ids()))
                    labels = [label.text() for label in dialog.model_picker.findChildren(QLabel, "modelChoice")]
                    if labels != ["yi-up", "alpha"]:
                        raise AssertionError(str(labels))
                    holder["ok"] = True
                    next(button for button in dialog.findChildren(QPushButton) if button.text() == "保存").click()
                    return
                elif dialog.model_status.property("state") == "error" or tries > 40:
                    holder["detail"] = dialog.model_status.text()
                    dialog.reject()
                    return
            except Exception as error:  # noqa: BLE001
                holder["detail"] = str(error)
                dialog.reject()
                return
            QTimer.singleShot(50, lambda: poll(tries + 1))

        try:
            QTimer.singleShot(30, lambda: poll(0))
            self.window.edit_provider(target.provider_id)
        finally:
            server.shutdown()
            server.server_close()
        self.assertTrue(holder["ok"], holder["detail"])
        raw = next(item for item in read_store()["providers"] if item["id"] == target.provider_id)
        self.assertEqual(
            raw["models"],
            [
                {"cursorName": "yi-up", "upstreamId": "yi-up"},
                {"cursorName": "alpha", "upstreamId": "alpha"},
            ],
        )

    def test_fetch_failure_keeps_selected_models(self):
        target = next(card for card in self.window.board.cards if _card_name(card) == "甲站")
        holder = {"text": "", "ids": []}

        def poll(tries: int = 0) -> None:
            dialog = self.window.findChild(ProviderDialog)
            if dialog is None:
                return
            if tries == 0:
                dialog.base_url.setText("http://127.0.0.1:1/v1")
                dialog.api_key.setText("sk-temp")
                dialog.fetch_btn.click()
            elif dialog.model_status.property("state") == "error" or tries > 40:
                holder["text"] = dialog.model_status.text()
                holder["ids"] = dialog.model_picker.chosen_ids()
                dialog.reject()
                return
            QTimer.singleShot(50, lambda: poll(tries + 1))

        QTimer.singleShot(30, lambda: poll(0))
        self.window.edit_provider(target.provider_id)
        self.assertEqual(holder["text"], "连不上这个地址")
        self.assertEqual(holder["ids"], ["jia-up"])


if __name__ == "__main__":
    unittest.main()

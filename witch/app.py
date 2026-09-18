from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QFontDatabase,
    QGuiApplication,
    QIcon,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from witch.gateway import start_gateway
from witch.paths import gateway_base_url
from witch.store import activate_provider, read_store, to_public
from witch.window import MainWindow

STYLE = """
QWidget { background: #222226; color: #f4f4f5; font-size: 13px; }
QWidget#listHost { background: #222226; }
QLabel#appTitle { font-size: 17px; font-weight: 700; color: #fafafa; }
QLabel#muted { color: #a1a1aa; }
QLabel#grip { color: #71717a; font-size: 16px; }
QLabel#providerName { font-size: 14px; font-weight: 650; color: #fafafa; }
QLabel#providerUrl { color: #a1a1aa; font-size: 12px; }
QLabel#okMeta { color: #34d399; font-size: 12px; }
QLabel#failMeta { color: #f87171; font-size: 12px; }
QFrame#headerBar {
  background: #222226;
  border: none;
  border-bottom: 1px solid #3f3f46;
}
QFrame#providerCard {
  background: #3f3f46;
  border: 1px solid #52525b;
  border-radius: 12px;
}
QFrame#providerCard[active="true"] {
  border: 1px solid #60a5fa;
  background: #1e3a5f;
}
QScrollArea { background: #222226; border: none; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }
QScrollBar::handle:vertical { background: #3f3f46; border-radius: 4px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QTextEdit, QPlainTextEdit, QLineEdit, QComboBox {
  background: #27272a;
  border: 1px solid #3f3f46;
  border-radius: 8px;
  padding: 6px 8px;
  color: #f4f4f5;
  selection-background-color: #2563eb;
}
QPushButton {
  background: #3f3f46;
  border: 1px solid #52525b;
  border-radius: 8px;
  padding: 5px 10px;
  color: #f4f4f5;
}
QPushButton:hover { background: #52525b; }
QPushButton:disabled { color: #71717a; }
QPushButton#headerBtn {
  background: #27272a;
  border: 1px solid #3f3f46;
  border-radius: 8px;
  padding: 0;
}
QPushButton#headerBtn:hover { background: #3f3f46; }
QPushButton#addBtn {
  background: #2563eb;
  border: none;
  color: white;
  border-radius: 8px;
  padding: 5px 12px;
  font-weight: 600;
}
QPushButton#addBtn:hover { background: #1d4ed8; }
QPushButton#pill {
  background: #14532d;
  border: 1px solid #166534;
  color: #86efac;
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 12px;
}
QPushButton#pill[ok="false"] {
  background: #450a0a;
  border: 1px solid #7f1d1d;
  color: #fca5a5;
}
QPushButton#enableOff {
  background: #2563eb;
  border: none;
  color: white;
  border-radius: 8px;
  padding: 4px 14px;
  font-weight: 600;
}
QPushButton#enableOff:hover { background: #1d4ed8; }
QPushButton#enableOn {
  background: transparent;
  border: none;
  color: #93c5fd;
  font-size: 18px;
  font-weight: 700;
  padding: 4px 10px;
}
QPushButton#ghostBtn, QPushButton#ghostDanger {
  background: transparent;
  border: none;
  border-radius: 6px;
  padding: 0;
}
QPushButton#ghostBtn:hover { background: #3f3f46; }
QPushButton#ghostDanger:hover { background: #7f1d1d; }
QMenu { background: #27272a; border: 1px solid #3f3f46; padding: 6px; color: #f4f4f5; }
QMenu::item { padding: 6px 18px; }
QMenu::item:selected { background: #2563eb; }
QDialog { background: #222226; }
"""


def make_icon() -> QIcon:
    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor("#ece8dc"))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(4, 4, 56, 56, 14, 14)
    painter.setPen(QColor("#161616"))
    font = QFont()
    font.setBold(True)
    font.setPixelSize(28)
    painter.setFont(font)
    painter.drawText(pix.rect(), Qt.AlignCenter, "W")
    painter.end()
    return QIcon(pix)


def apply_dark(app: QApplication) -> None:
    app.setStyle("Fusion")
    font = QFont()
    for name in (
        "Microsoft YaHei UI",
        "PingFang SC",
        "WenQuanYi Micro Hei",
        "Noto Sans CJK SC",
        "Segoe UI",
        "Sans Serif",
    ):
        if name in QFontDatabase.families():
            font = QFont(name)
            break
    font.setPixelSize(13)
    app.setFont(font)
    app.setStyleSheet(STYLE)


class WitchApp:
    def __init__(self):
        self.qt = QApplication.instance() or QApplication(sys.argv)
        self.qt.setApplicationName("Witch")
        self.qt.setQuitOnLastWindowClosed(False)
        apply_dark(self.qt)
        self.icon = make_icon()
        self.qt.setWindowIcon(self.icon)
        try:
            start_gateway()
        except RuntimeError as error:
            QMessageBox.critical(None, "Witch", str(error))
            raise
        self.window = MainWindow(on_change=self._rebuild_tray)
        self.window.setWindowIcon(self.icon)
        self.window.set_gateway_status(True, gateway_base_url())
        self.tray = QSystemTrayIcon(self.icon)
        self.tray.setToolTip("Witch")
        self.tray.activated.connect(self._tray_activated)
        self._rebuild_tray()
        self.tray.show()
        self.window.show()

    def _rebuild_tray(self) -> None:
        if not getattr(self, "window", None) or not getattr(self, "tray", None):
            return
        menu = QMenu()
        show = QAction("打开主窗口", self.qt)
        show.triggered.connect(self.window.showNormal)
        menu.addAction(show)
        menu.addSeparator()
        state = to_public(read_store())
        for provider in state["providers"]:
            action = QAction(provider["name"], self.qt)
            action.setCheckable(True)
            action.setChecked(provider["id"] == state["activeProviderId"])
            action.triggered.connect(lambda checked=False, pid=provider["id"]: self._switch(pid))
            menu.addAction(action)
        menu.addSeparator()
        quit_action = QAction("退出", self.qt)
        quit_action.triggered.connect(self.qt.quit)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        active = next((item["name"] for item in state["providers"] if item["id"] == state["activeProviderId"]), "")
        self.tray.setToolTip(f"Witch · {active}" if active else "Witch")

    def _switch(self, provider_id: str) -> None:
        activate_provider(provider_id)
        self.window.refresh()
        name = next((item["name"] for item in to_public(read_store())["providers"] if item["id"] == provider_id), "")
        self.tray.showMessage("Witch", name, QSystemTrayIcon.Information, 1600)

    def _tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self.window.showNormal()
            self.window.raise_()
            self.window.activateWindow()

    def run(self) -> int:
        return self.qt.exec()


def main() -> int:
    if not QGuiApplication.instance():
        pass
    return WitchApp().run()

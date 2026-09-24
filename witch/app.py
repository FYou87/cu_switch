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
QWidget { color: #111827; font-size: 13px; }
QWidget#root { background: #f5f6f8; }
QWidget#listHost { background: #f5f6f8; }
QLabel#appTitle { font-size: 16px; font-weight: 700; color: #111827; background: transparent; }
QLabel#dialogTitle { font-size: 18px; font-weight: 700; color: #111827; }
QLabel#muted { color: #6b7280; background: transparent; }
QLabel#formLabel { color: #6b7280; font-size: 12px; background: transparent; }
QLabel#formHint { color: #6b7280; font-size: 12px; background: transparent; }
QLabel#grip { color: #9ca3af; font-size: 16px; background: transparent; }
QLabel#providerName { font-size: 14px; font-weight: 650; color: #111827; background: transparent; }
QLabel#providerUrl { font-size: 12px; background: transparent; }
QLabel#metaBadge {
  background: #f3f4f6;
  color: #4b5563;
  border-radius: 10px;
  padding: 3px 8px;
  font-size: 12px;
}
QLabel#metaOk { color: #059669; font-size: 12px; background: transparent; }
QLabel#metaFail { color: #dc2626; font-size: 12px; background: transparent; }
QFrame#headerBar {
  background: #ffffff;
  border: none;
  border-bottom: 1px solid #e6e8ee;
}
QFrame#searchRow { background: #ffffff; border: none; }
QFrame#providerCard {
  background: #ffffff;
  border: 1px solid #e6e8ee;
  border-radius: 12px;
}
QFrame#providerCard[active="true"] {
  border: 1px solid #3b82f6;
  background: #ffffff;
}
QScrollArea#providerScroll { background: #f5f6f8; border: none; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 4px 0; }
QScrollBar::handle:vertical { background: #d1d5db; border-radius: 4px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QTextEdit, QPlainTextEdit, QLineEdit, QComboBox {
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 7px 10px;
  color: #111827;
  selection-background-color: #dbeafe;
  selection-color: #111827;
}
QTextEdit:focus, QPlainTextEdit:focus, QLineEdit:focus, QComboBox:focus { border: 1px solid #2563eb; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
  background: #ffffff;
  color: #111827;
  selection-background-color: #eff6ff;
  selection-color: #111827;
  border: 1px solid #e5e7eb;
}
QPushButton {
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 6px 12px;
  color: #111827;
}
QPushButton:hover { background: #f9fafb; }
QPushButton:disabled { color: #9ca3af; }
QPushButton#iconBtn, QPushButton#toolBtn {
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 0 12px;
  color: #111827;
}
QPushButton#iconBtn { padding: 0; }
QPushButton#iconBtn:hover, QPushButton#toolBtn:hover { background: #f3f4f6; }
QPushButton#modeBtn {
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 6px 12px;
  font-weight: 650;
  color: #111827;
}
QPushButton#modeBtn[selected="true"] {
  background: #2563eb;
  border: none;
  color: #ffffff;
}
QPushButton#modeBtn[selected="true"]:hover { background: #1d4ed8; }
QPushButton#addBtn {
  background: #2563eb;
  border: none;
  border-radius: 18px;
  padding: 0;
}
QPushButton#addBtn:hover { background: #1d4ed8; }
QPushButton#hostChip {
  background: transparent;
  border: none;
  color: #16a34a;
  padding: 0 4px;
  font-weight: 600;
}
QPushButton#hostChip[ok="false"] { color: #dc2626; }
QPushButton#enableOff {
  background: #2563eb;
  border: none;
  color: white;
  border-radius: 8px;
  padding: 0 14px;
  font-weight: 650;
}
QPushButton#enableOff:hover { background: #1d4ed8; }
QPushButton#enableOn, QPushButton#enableOn:disabled {
  background: #f3f4f6;
  border: none;
  color: #6b7280;
  border-radius: 8px;
  padding: 0 12px;
  font-weight: 650;
}
QPushButton#cardIcon, QPushButton#cardDanger {
  background: transparent;
  border: none;
  border-radius: 8px;
  padding: 0;
}
QPushButton#cardIcon:hover { background: #f3f4f6; }
QPushButton#cardDanger:hover { background: #fee2e2; }
QPushButton#cardDanger:disabled { background: transparent; }
QPushButton#primaryBtn {
  background: #2563eb;
  border: none;
  color: white;
  border-radius: 8px;
  padding: 8px 18px;
  font-weight: 650;
}
QPushButton#primaryBtn:hover { background: #1d4ed8; }
QPushButton#ghostText {
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 8px 16px;
}
QMenu { background: #ffffff; border: 1px solid #e5e7eb; padding: 6px; color: #111827; }
QMenu::item { padding: 6px 18px; border-radius: 6px; }
QMenu::item:selected { background: #eff6ff; color: #111827; }
QDialog { background: #ffffff; }
QMessageBox { background: #ffffff; }
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
        show = QAction("打开主界面", self.qt)
        show.triggered.connect(self.window.showNormal)
        menu.addAction(show)
        mode = self.window.mode_switch.mode()
        api_mode = QAction("API 模式", self.qt)
        api_mode.setCheckable(True)
        api_mode.setChecked(mode == "api")
        api_mode.triggered.connect(lambda: self.window.choose_mode("api"))
        login_mode = QAction("登录模式", self.qt)
        login_mode.setCheckable(True)
        login_mode.setChecked(mode == "login")
        login_mode.triggered.connect(lambda: self.window.choose_mode("login"))
        menu.addAction(api_mode)
        menu.addAction(login_mode)
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

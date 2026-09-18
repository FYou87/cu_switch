from __future__ import annotations

import json
from typing import Callable

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QGuiApplication,
    QIcon,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from witch.paths import gateway_base_url
from witch.parse_import import parse_relay_text
from witch.store import (
    activate_provider,
    create_provider,
    duplicate_provider,
    export_backup,
    get_active,
    import_backup,
    move_provider,
    patch_provider,
    patch_setup,
    read_store,
    remove_provider,
    restore_demo,
    record_last_test,
    rotate_token,
    to_public,
)
from witch.test_provider import test_provider as run_test

ICON_COLORS = (
    "#3b82f6",
    "#10b981",
    "#f59e0b",
    "#8b5cf6",
    "#ec4899",
    "#06b6d4",
    "#f97316",
    "#64748b",
)


def _line_icon(kind: str, color: str = "#c8c8c8") -> QIcon:
    pix = QPixmap(36, 36)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(2, 2)
    pen = QPen(QColor(color))
    pen.setWidthF(1.5)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    if kind == "edit":
        painter.drawLine(4, 13, 13, 4)
        painter.drawLine(13, 4, 15, 6)
        painter.drawLine(15, 6, 6, 15)
        painter.drawLine(4, 13, 3, 16)
        painter.drawLine(3, 16, 6, 15)
    elif kind == "copy":
        painter.drawRoundedRect(6, 3, 9, 10, 1.5, 1.5)
        painter.drawLine(3, 6, 3, 15)
        painter.drawLine(3, 15, 12, 15)
        painter.drawLine(3, 6, 5, 6)
        painter.drawLine(12, 15, 12, 14)
    elif kind == "zap":
        painter.drawPolyline(
            [
                QPoint(10, 2),
                QPoint(6, 9),
                QPoint(10, 9),
                QPoint(8, 16),
                QPoint(14, 8),
                QPoint(10, 8),
                QPoint(12, 2),
            ]
        )
    elif kind == "trash":
        painter.drawLine(4, 5, 14, 5)
        painter.drawLine(7, 5, 8, 3)
        painter.drawLine(10, 3, 11, 5)
        painter.drawRoundedRect(5, 5, 8, 10, 1, 1)
        painter.drawLine(8, 8, 8, 12)
        painter.drawLine(10, 8, 10, 12)
    elif kind == "gear":
        painter.drawEllipse(7, 7, 4, 4)
        painter.drawEllipse(4, 4, 10, 10)
    elif kind == "plus":
        painter.drawLine(9, 4, 9, 14)
        painter.drawLine(4, 9, 14, 9)
    elif kind == "import":
        painter.drawLine(9, 3, 9, 11)
        painter.drawLine(6, 8, 9, 11)
        painter.drawLine(12, 8, 9, 11)
        painter.drawLine(4, 14, 14, 14)
    painter.end()
    return QIcon(pix)


def _icon_color(name: str) -> str:
    return ICON_COLORS[sum(ord(char) for char in name) % len(ICON_COLORS)]


def _ghost_button(icon: str, tip: str, danger: bool = False) -> QPushButton:
    button = QPushButton()
    button.setIcon(_line_icon(icon, "#f87171" if danger else "#e4e4e7"))
    button.setIconSize(QSize(16, 16))
    button.setToolTip(tip)
    button.setCursor(Qt.PointingHandCursor)
    button.setObjectName("ghostDanger" if danger else "ghostBtn")
    button.setFixedSize(28, 28)
    button.setFocusPolicy(Qt.NoFocus)
    return button


def _display_url(provider: dict) -> str:
    if provider.get("kind") == "demo":
        return "witch://demo"
    return (provider.get("baseUrl") or "").strip() or "未配置"


class ProviderCard(QFrame):
    enable = Signal(str)
    edit = Signal(str)
    duplicate = Signal(str)
    test = Signal(str)
    delete = Signal(str)
    moved = Signal(str, int)

    def __init__(self, provider: dict, active: bool, parent=None):
        super().__init__(parent)
        self.provider_id = provider["id"]
        self._drag_y: float | None = None
        self.setObjectName("providerCard")
        self.setProperty("active", "true" if active else "false")
        self.setFixedHeight(76)
        self.setCursor(Qt.ArrowCursor)

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 10, 12, 10)
        row.setSpacing(10)

        self.grip = QLabel("≡")
        self.grip.setObjectName("grip")
        self.grip.setFixedWidth(16)
        self.grip.setAlignment(Qt.AlignCenter)
        self.grip.setCursor(Qt.SizeAllCursor)
        self.grip.installEventFilter(self)
        row.addWidget(self.grip)

        badge = QLabel((provider.get("name") or "?")[:1].upper())
        badge.setObjectName("providerBadge")
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedSize(36, 36)
        badge.setStyleSheet(
            f"background: {_icon_color(provider.get('name') or '')}; color: #fff;"
            " border-radius: 10px; font-weight: 700; font-size: 15px;"
        )
        row.addWidget(badge)

        info = QVBoxLayout()
        info.setSpacing(2)
        info.setContentsMargins(0, 2, 0, 2)
        name = QLabel(provider.get("name") or "未命名")
        name.setObjectName("providerName")
        url = QLabel(_display_url(provider))
        url.setObjectName("providerUrl")
        url.setTextInteractionFlags(Qt.TextSelectableByMouse)
        if str(url.text()).startswith("http"):
            url.setCursor(Qt.PointingHandCursor)
            url.mousePressEvent = lambda event, href=url.text(): QDesktopServices.openUrl(QUrl(href))
        info.addWidget(name)
        info.addWidget(url)
        row.addLayout(info, 1)

        last = provider.get("lastTest") or {}
        if last:
            meta = QLabel("通过" if last.get("ok") else "失败")
            meta.setObjectName("okMeta" if last.get("ok") else "failMeta")
            row.addWidget(meta)

        self.enable_btn = QPushButton("✓" if active else "启用")
        self.enable_btn.setObjectName("enableOn" if active else "enableOff")
        self.enable_btn.setCursor(Qt.PointingHandCursor)
        self.enable_btn.setFixedHeight(30)
        self.enable_btn.setMinimumWidth(52)
        self.enable_btn.setEnabled(not active)
        self.enable_btn.setFocusPolicy(Qt.NoFocus)
        self.enable_btn.clicked.connect(lambda: self.enable.emit(self.provider_id))
        row.addWidget(self.enable_btn)

        self.action_wrap = QWidget()
        self.action_wrap.setFixedWidth(128)
        actions = QHBoxLayout(self.action_wrap)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(2)
        self.edit_btn = _ghost_button("edit", "编辑")
        self.dup_btn = _ghost_button("copy", "复制")
        self.test_btn = _ghost_button("zap", "测速")
        self.del_btn = _ghost_button("trash", "删除", danger=True)
        self.edit_btn.clicked.connect(lambda: self.edit.emit(self.provider_id))
        self.dup_btn.clicked.connect(lambda: self.duplicate.emit(self.provider_id))
        self.test_btn.clicked.connect(lambda: self.test.emit(self.provider_id))
        self.del_btn.clicked.connect(lambda: self.delete.emit(self.provider_id))
        self.del_btn.setEnabled(not active)
        for button in (self.edit_btn, self.dup_btn, self.test_btn, self.del_btn):
            actions.addWidget(button)
        row.addWidget(self.action_wrap)

        self._action_buttons = [self.edit_btn, self.dup_btn, self.test_btn, self.del_btn]
        self._action_effect = QGraphicsOpacityEffect(self.action_wrap)
        self.action_wrap.setGraphicsEffect(self._action_effect)
        self._set_actions_visible(False)

    def _set_actions_visible(self, visible: bool) -> None:
        self._action_effect.setOpacity(1 if visible else 0)
        for button in self._action_buttons:
            if button is self.del_btn and not button.isEnabled() and visible:
                continue
            button.setAttribute(Qt.WA_TransparentForMouseEvents, not visible)

    def enterEvent(self, event) -> None:
        self._set_actions_visible(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._set_actions_visible(False)
        super().leaveEvent(event)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.grip:
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._drag_y = event.globalPosition().y()
                self.grip.grabMouse()
                return True
            if event.type() == QEvent.MouseMove and self._drag_y is not None:
                delta = event.globalPosition().y() - self._drag_y
                if abs(delta) >= 40:
                    direction = 1 if delta > 0 else -1
                    self._drag_y = None
                    self.grip.releaseMouse()
                    self.moved.emit(self.provider_id, direction)
                return True
            if event.type() == QEvent.MouseButtonRelease:
                self._drag_y = None
                self.grip.releaseMouse()
                return True
        return super().eventFilter(obj, event)


class ProviderDialog(QDialog):
    def __init__(self, parent=None, provider: dict | None = None):
        super().__init__(parent)
        self.provider = provider
        self.setWindowTitle("编辑" if provider else "添加")
        self.resize(460, 420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        form = QFormLayout()
        form.setSpacing(10)
        self.name = QLineEdit(provider["name"] if provider else "")
        self.protocol = QComboBox()
        self.protocol.addItem("OpenAI", "openai")
        self.protocol.addItem("Anthropic", "anthropic")
        if provider:
            self.protocol.setCurrentIndex(0 if provider.get("protocol") == "openai" else 1)
        self.auth = QComboBox()
        self.auth.addItem("Bearer", "bearer")
        self.auth.addItem("x-api-key", "x-api-key")
        self.auth.addItem("Both", "both")
        if provider:
            self.auth.setCurrentIndex({"bearer": 0, "x-api-key": 1, "both": 2}.get(provider.get("authStyle"), 0))
        proto_row = QHBoxLayout()
        proto_row.addWidget(self.protocol, 1)
        proto_row.addWidget(self.auth, 1)
        proto_wrap = QWidget()
        proto_wrap.setLayout(proto_row)
        self.base_url = QLineEdit(
            "" if provider and provider.get("kind") == "demo" else (provider or {}).get("baseUrl", "")
        )
        self.base_url.setPlaceholderText("https://api.example.com/v1")
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.Password)
        self.api_key.setPlaceholderText("已保存" if provider and provider.get("hasApiKey") else "sk-...")
        self.models = QPlainTextEdit()
        self.models.setPlaceholderText("cursorName = upstreamId")
        self.models.setFixedHeight(96)
        lines = [
            f"{model.get('cursorName', '')} = {model.get('upstreamId', '')}"
            for model in (provider or {}).get("models") or []
        ]
        self.models.setPlainText("\n".join(lines))
        form.addRow("名称", self.name)
        form.addRow("协议", proto_wrap)
        form.addRow("地址", self.base_url)
        form.addRow("Key", self.api_key)
        form.addRow("模型", self.models)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def payload(self) -> dict:
        models = []
        for line in self.models.toPlainText().splitlines():
            if not line.strip():
                continue
            left, right = line.split("=", 1) if "=" in line else (line, line)
            models.append({"cursorName": left.strip(), "upstreamId": right.strip() or left.strip()})
        data = {
            "name": self.name.text().strip(),
            "protocol": self.protocol.currentData(),
            "authStyle": self.auth.currentData(),
            "baseUrl": self.base_url.text().strip()
            or ("witch://demo" if self.provider and self.provider.get("kind") == "demo" else ""),
            "apiKey": self.api_key.text().strip(),
            "models": models,
            "notes": "",
        }
        if not data["name"]:
            raise ValueError("名称不能为空")
        if self.provider is None and not data["baseUrl"]:
            raise ValueError("地址不能为空")
        if not data["models"]:
            raise ValueError("至少一条模型映射")
        return data


class ImportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("导入")
        self.resize(480, 360)
        layout = QVBoxLayout(self)
        self.text = QTextEdit()
        self.text.setPlaceholderText(
            "ANTHROPIC_BASE_URL=https://...\nANTHROPIC_AUTH_TOKEN=sk-...\nmodel=claude-sonnet-4-6"
        )
        self.preview = QLabel("")
        self.preview.setObjectName("muted")
        self.preview.setWordWrap(True)
        layout.addWidget(self.text, 1)
        layout.addWidget(self.preview)
        self.text.textChanged.connect(self._refresh)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("导入")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._parsed = None

    def _refresh(self) -> None:
        try:
            self._parsed = parse_relay_text(self.text.toPlainText())
            models = " ".join(item["cursorName"] for item in self._parsed["models"])
            self.preview.setText(f"{self._parsed['name']}  ·  {self._parsed['baseUrl']}  ·  {models}")
        except Exception as error:  # noqa: BLE001
            self._parsed = None
            self.preview.setText(str(error))

    def payload(self) -> dict:
        if not self._parsed:
            raise ValueError(self.preview.text() or "无法识别")
        return self._parsed


class SettingsDialog(QDialog):
    def __init__(self, parent: MainWindow):
        super().__init__(parent)
        self.main = parent
        self.setWindowTitle("设置")
        self.resize(460, 220)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        form = QFormLayout()
        self.url = QLineEdit(gateway_base_url())
        self.url.setReadOnly(True)
        self.key = QLineEdit()
        self.key.setReadOnly(True)
        self.key.setEchoMode(QLineEdit.Password)
        url_row = QHBoxLayout()
        url_row.addWidget(self.url, 1)
        copy_url = QPushButton("复制")
        copy_url.clicked.connect(self.main.copy_url)
        url_row.addWidget(copy_url)
        key_row = QHBoxLayout()
        key_row.addWidget(self.key, 1)
        copy_key = QPushButton("复制")
        copy_key.clicked.connect(self.main.copy_key)
        rotate = QPushButton("轮换")
        rotate.clicked.connect(self._rotate)
        key_row.addWidget(copy_key)
        key_row.addWidget(rotate)
        url_wrap = QWidget()
        url_wrap.setLayout(url_row)
        key_wrap = QWidget()
        key_wrap.setLayout(key_row)
        form.addRow("Base URL", url_wrap)
        form.addRow("API Key", key_wrap)
        layout.addLayout(form)
        actions = QHBoxLayout()
        for text, slot in (
            ("探测", self.main.probe),
            ("导出", self.main.export_file),
            ("导入备份", self.main.import_file),
            ("恢复回显", self.main.restore),
        ):
            button = QPushButton(text)
            button.clicked.connect(slot)
            actions.addWidget(button)
        layout.addLayout(actions)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.button(QDialogButtonBox.Close).setText("关闭")
        close.rejected.connect(self.reject)
        close.accepted.connect(self.accept)
        layout.addWidget(close)
        self.reload()

    def reload(self) -> None:
        self.url.setText(gateway_base_url())
        self.key.setText(to_public(read_store())["gatewayToken"])

    def _rotate(self) -> None:
        if QMessageBox.question(self, "轮换", "Cursor 里的 Key 也要改。") != QMessageBox.Yes:
            return
        rotate_token()
        self.reload()
        self.main.refresh()


class MainWindow(QWidget):
    def __init__(self, on_change: Callable[[], None] | None = None):
        super().__init__()
        self._on_change = on_change
        self._ready = False
        self.setWindowTitle("Witch")
        self.resize(760, 560)
        self.setMinimumSize(620, 420)
        self._build()
        self.refresh()
        self._ready = True

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 16)
        root.setSpacing(12)

        header_bar = QFrame()
        header_bar.setObjectName("headerBar")
        header = QHBoxLayout(header_bar)
        header.setContentsMargins(0, 0, 0, 10)
        header.setSpacing(8)
        title = QLabel("Witch")
        title.setObjectName("appTitle")
        header.addWidget(title)
        header.addStretch()
        self.pill = QPushButton()
        self.pill.setObjectName("pill")
        self.pill.setCursor(Qt.PointingHandCursor)
        self.pill.setFocusPolicy(Qt.NoFocus)
        self.pill.clicked.connect(self.open_settings)
        header.addWidget(self.pill)
        settings_btn = QPushButton()
        settings_btn.setIcon(_line_icon("gear"))
        settings_btn.setIconSize(QSize(16, 16))
        settings_btn.setToolTip("设置")
        settings_btn.setObjectName("headerBtn")
        settings_btn.setFixedSize(32, 32)
        settings_btn.setFocusPolicy(Qt.NoFocus)
        settings_btn.clicked.connect(self.open_settings)
        header.addWidget(settings_btn)
        import_btn = QPushButton()
        import_btn.setIcon(_line_icon("import"))
        import_btn.setIconSize(QSize(16, 16))
        import_btn.setToolTip("导入")
        import_btn.setObjectName("headerBtn")
        import_btn.setFixedSize(32, 32)
        import_btn.setFocusPolicy(Qt.NoFocus)
        import_btn.clicked.connect(self.import_text)
        header.addWidget(import_btn)
        add_btn = QPushButton("添加")
        add_btn.setIcon(_line_icon("plus", "#ffffff"))
        add_btn.setIconSize(QSize(14, 14))
        add_btn.setObjectName("addBtn")
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.setFocusPolicy(Qt.NoFocus)
        add_btn.clicked.connect(self.add_provider)
        header.addWidget(add_btn)
        root.addWidget(header_bar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_host = QWidget()
        self.list_host.setObjectName("listHost")
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(0, 0, 2, 0)
        self.list_layout.setSpacing(10)
        self.list_layout.addStretch()
        self.scroll.setWidget(self.list_host)
        root.addWidget(self.scroll, 1)

        QShortcut(QKeySequence.Preferences, self, self.open_settings)
        QShortcut(QKeySequence("Ctrl+N"), self, self.add_provider)
        QShortcut(QKeySequence("Ctrl+I"), self, self.import_text)

    def set_gateway_status(self, ok: bool, detail: str) -> None:
        host = gateway_base_url().replace("http://", "").replace("/v1", "")
        self.pill.setText(host)
        self.pill.setProperty("ok", "true" if ok else "false")
        self.pill.style().unpolish(self.pill)
        self.pill.style().polish(self.pill)
        self.pill.setToolTip(detail)

    def refresh(self) -> None:
        state = to_public(read_store())
        bar = self.scroll.verticalScrollBar()
        keep = bar.value()
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        providers = state["providers"]
        if not providers:
            empty = QLabel("还没有站点")
            empty.setObjectName("muted")
            empty.setAlignment(Qt.AlignCenter)
            empty.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.list_layout.insertWidget(0, empty)
        else:
            for index, provider in enumerate(providers):
                card = ProviderCard(provider, provider["id"] == state["activeProviderId"])
                card.enable.connect(self.enable_provider)
                card.edit.connect(self.edit_provider)
                card.duplicate.connect(self.duplicate_id)
                card.test.connect(self.test_provider)
                card.delete.connect(self.delete_provider)
                card.moved.connect(self.move_id)
                self.list_layout.insertWidget(index, card)
        bar.setValue(keep)
        if self._ready and self._on_change:
            self._on_change()

    def _provider(self, provider_id: str) -> dict | None:
        state = to_public(read_store())
        return next((item for item in state["providers"] if item["id"] == provider_id), None)

    def enable_provider(self, provider_id: str) -> None:
        activate_provider(provider_id)
        self.refresh()

    def add_provider(self) -> None:
        dialog = ProviderDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            create_provider(dialog.payload())
            self.refresh()
        except Exception as error:  # noqa: BLE001
            QMessageBox.warning(self, "添加失败", str(error))

    def edit_provider(self, provider_id: str) -> None:
        provider = self._provider(provider_id)
        if not provider:
            return
        dialog = ProviderDialog(self, provider)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            patch_provider(provider_id, dialog.payload())
            self.refresh()
        except Exception as error:  # noqa: BLE001
            QMessageBox.warning(self, "保存失败", str(error))

    def delete_provider(self, provider_id: str) -> None:
        provider = self._provider(provider_id)
        if not provider:
            return
        if provider_id == to_public(read_store())["activeProviderId"]:
            return
        if QMessageBox.question(self, "删除", f"删除「{provider['name']}」？") != QMessageBox.Yes:
            return
        remove_provider(provider_id)
        self.refresh()

    def duplicate_id(self, provider_id: str) -> None:
        duplicate_provider(provider_id)
        self.refresh()

    def move_id(self, provider_id: str, delta: int) -> None:
        move_provider(provider_id, delta)
        self.refresh()

    def test_provider(self, provider_id: str) -> None:
        store, _active = get_active()
        raw = next((item for item in store["providers"] if item["id"] == provider_id), None)
        if not raw:
            return
        result = run_test(raw)
        record_last_test(provider_id, result)
        self.refresh()
        box = QMessageBox.information if result["ok"] else QMessageBox.warning
        box(self, "测速", result["message"])

    def restore(self) -> None:
        restore_demo()
        self.refresh()

    def import_text(self) -> None:
        dialog = ImportDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            create_provider(dialog.payload())
            self.refresh()
        except Exception as error:  # noqa: BLE001
            QMessageBox.warning(self, "导入失败", str(error))

    def export_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出", "witch-backup.json", "JSON (*.json)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(export_backup(), handle, ensure_ascii=False, indent=2)

    def import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "导入备份", "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as handle:
                import_backup(json.load(handle))
            self.refresh()
        except Exception as error:  # noqa: BLE001
            QMessageBox.warning(self, "导入失败", str(error))

    def copy_url(self) -> None:
        QGuiApplication.clipboard().setText(gateway_base_url())
        patch_setup({"copiedBaseUrl": True})

    def copy_key(self) -> None:
        QGuiApplication.clipboard().setText(to_public(read_store())["gatewayToken"])
        patch_setup({"copiedKey": True})

    def open_settings(self) -> None:
        SettingsDialog(self).exec()

    def probe(self) -> None:
        import urllib.error
        import urllib.request

        state = to_public(read_store())
        active = next((item for item in state["providers"] if item["id"] == state["activeProviderId"]), None)
        model = ((active or {}).get("models") or [{"cursorName": "witch-echo"}])[0]["cursorName"]
        payload = json.dumps(
            {
                "model": model,
                "messages": [{"role": "user", "content": "ping"}],
                "stream": False,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{gateway_base_url()}/chat/completions",
            data=payload,
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {state['gatewayToken']}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                data = json.loads(response.read().decode("utf-8"))
            text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "ok"
            patch_setup({"probed": True})
            self.refresh()
            QMessageBox.information(self, "探测", str(text)[:400])
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            QMessageBox.warning(self, "探测", detail[:400] or error.reason)
            self.refresh()
        except Exception as error:  # noqa: BLE001
            QMessageBox.warning(self, "探测", str(error))
            self.refresh()

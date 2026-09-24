from __future__ import annotations

import json
from typing import Callable

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QSize,
    Qt,
    QThread,
    QTimer,
    QUrl,
    Signal,
)
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
    QAbstractButton,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from witch.paths import gateway_base_url
from witch.parse_import import parse_relay_text
from witch.presets import ICON_COLORS, PRESETS
from witch.store import (
    activate_provider,
    create_provider,
    duplicate_provider,
    export_backup,
    get_active,
    import_backup,
    patch_provider,
    patch_setup,
    read_store,
    remove_provider,
    reorder_providers,
    record_last_test,
    to_public,
)
from witch.test_provider import test_provider as run_test
from witch.upstream import list_model_ids


def _line_icon(kind: str, color: str = "#6b7280") -> QIcon:
    pix = QPixmap(36, 36)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(2, 2)
    pen = QPen(QColor(color))
    pen.setWidthF(1.6)
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
    elif kind == "chart":
        painter.drawLine(4, 15, 4, 9)
        painter.drawLine(8, 15, 8, 6)
        painter.drawLine(12, 15, 12, 3)
        painter.drawLine(3, 15, 15, 15)
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
    elif kind == "eye":
        painter.drawEllipse(4, 6, 10, 6)
        painter.drawEllipse(7, 7, 4, 4)
    painter.end()
    return QIcon(pix)


def _logo_pixmap() -> QPixmap:
    pix = QPixmap(56, 56)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#2563eb"))
    painter.drawRoundedRect(2, 2, 52, 52, 14, 14)
    pen = QPen(QColor("#ffffff"))
    pen.setWidth(4)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.drawLine(16, 22, 40, 22)
    painter.drawLine(33, 15, 40, 22)
    painter.drawLine(33, 29, 40, 22)
    painter.drawLine(16, 36, 40, 36)
    painter.drawLine(16, 36, 23, 29)
    painter.drawLine(16, 36, 23, 43)
    painter.end()
    return pix


def _icon_color(provider: dict) -> str:
    color = (provider.get("iconColor") or "").strip()
    if color:
        return color
    name = provider.get("name") or ""
    return ICON_COLORS[sum(ord(char) for char in name) % len(ICON_COLORS)]


def _host_text() -> str:
    return gateway_base_url().replace("http://", "").replace("/v1", "")


def _subtitle(provider: dict) -> str:
    if provider.get("kind") == "demo":
        return "本机回显"
    website = (provider.get("website") or "").strip()
    base = (provider.get("baseUrl") or "").strip()
    return website or base or (provider.get("notes") or "").strip() or "未配置"


class ElideLabel(QLabel):
    def __init__(self, text: str = "", color: str = "#111827", parent=None):
        super().__init__(text, parent)
        self._color = QColor(color)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setPen(self._color)
        painter.setFont(self.font())
        text = self.fontMetrics().elidedText(self.text(), Qt.ElideMiddle, max(0, self.width()))
        painter.drawText(self.rect(), int(Qt.AlignLeft | Qt.AlignVCenter), text)


class ProxySwitch(QAbstractButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(42, 24)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#22c55e" if self.isChecked() else "#d1d5db"))
        painter.drawRoundedRect(1, 2, 40, 20, 10, 10)
        painter.setBrush(QColor("#ffffff"))
        knob = 22 if self.isChecked() else 3
        painter.drawEllipse(knob, 4, 16, 16)
        painter.end()


class ProviderCard(QFrame):
    enable = Signal(str)
    edit = Signal(str)
    duplicate = Signal(str)
    test = Signal(str)
    delete = Signal(str)
    drag_press = Signal(object, float)
    drag_move = Signal(object, float)
    drag_release = Signal(object)

    def __init__(self, provider: dict, active: bool, parent=None):
        super().__init__(parent)
        self.provider_id = provider["id"]
        self._pressed = False
        self.setObjectName("providerCard")
        self.setProperty("active", "true" if active else "false")
        self.setFixedHeight(74)

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(12)

        self.grip = QLabel("≡")
        self.grip.setObjectName("grip")
        self.grip.setFixedWidth(18)
        self.grip.setAlignment(Qt.AlignCenter)
        self.grip.setCursor(Qt.SizeAllCursor)
        self.grip.installEventFilter(self)
        row.addWidget(self.grip)

        badge = QLabel((provider.get("name") or "?")[:1].upper())
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedSize(36, 36)
        badge.setStyleSheet(
            f"background: {_icon_color(provider)}; color: white; border-radius: 10px;"
            "font-weight: 700; font-size: 15px;"
        )
        row.addWidget(badge)

        info = QVBoxLayout()
        info.setSpacing(2)
        info.setContentsMargins(0, 4, 0, 4)
        name = ElideLabel(provider.get("name") or "未命名", "#111827")
        name.setObjectName("providerName")
        subtitle = _subtitle(provider)
        url = ElideLabel(subtitle, "#2563eb" if subtitle.startswith("http") else "#6b7280")
        url.setObjectName("providerUrl")
        if subtitle.startswith("http"):
            url.setCursor(Qt.PointingHandCursor)
            url.mousePressEvent = lambda event, href=subtitle: QDesktopServices.openUrl(QUrl(href))
        info.addWidget(name)
        info.addWidget(url)
        row.addLayout(info, 1)

        last = provider.get("lastTest") or {}
        if last.get("ms"):
            latency = QLabel(f"{last['ms']} ms" if last.get("ok") else "失败")
            latency.setObjectName("metaOk" if last.get("ok") else "metaFail")
            latency.setToolTip(last.get("message") or "")
            row.addWidget(latency)

        count = len(provider.get("models") or [])
        badge_text = QLabel(f"{count} 个模型")
        badge_text.setObjectName("metaBadge")
        badge_text.setAlignment(Qt.AlignCenter)
        row.addWidget(badge_text)

        self.enable_btn = QPushButton("✓  使用中" if active else "启用")
        self.enable_btn.setObjectName("enableOn" if active else "enableOff")
        self.enable_btn.setCursor(Qt.PointingHandCursor)
        self.enable_btn.setFixedHeight(32)
        self.enable_btn.setMinimumWidth(88 if active else 72)
        self.enable_btn.setEnabled(not active)
        self.enable_btn.setFocusPolicy(Qt.NoFocus)
        self.enable_btn.clicked.connect(lambda: self.enable.emit(self.provider_id))
        row.addWidget(self.enable_btn)

        self.edit_btn = self._icon_button("edit", "编辑")
        self.dup_btn = self._icon_button("copy", "复制")
        self.test_btn = self._icon_button("zap", "测速")
        self.del_btn = self._icon_button("trash", "删除", danger=True)
        self.edit_btn.clicked.connect(lambda: self.edit.emit(self.provider_id))
        self.dup_btn.clicked.connect(lambda: self.duplicate.emit(self.provider_id))
        self.test_btn.clicked.connect(lambda: self.test.emit(self.provider_id))
        self.del_btn.clicked.connect(lambda: self.delete.emit(self.provider_id))
        self.del_btn.setEnabled(not active)
        for button in (self.edit_btn, self.dup_btn, self.test_btn, self.del_btn):
            row.addWidget(button)

    def _icon_button(self, kind: str, tip: str, danger: bool = False) -> QPushButton:
        button = QPushButton()
        button.setIcon(_line_icon(kind, "#ef4444" if danger else "#6b7280"))
        button.setIconSize(QSize(16, 16))
        button.setToolTip(tip)
        button.setCursor(Qt.PointingHandCursor)
        button.setObjectName("cardDanger" if danger else "cardIcon")
        button.setFixedSize(32, 32)
        button.setFocusPolicy(Qt.NoFocus)
        return button

    def eventFilter(self, obj, event) -> bool:
        if obj is self.grip:
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._pressed = True
                self.grip.grabMouse()
                self.drag_press.emit(self, float(event.globalPosition().y()))
                return True
            if event.type() == QEvent.MouseMove and self._pressed:
                self.drag_move.emit(self, float(event.globalPosition().y()))
                return True
            if event.type() == QEvent.MouseButtonRelease and self._pressed:
                self._pressed = False
                self.grip.releaseMouse()
                self.drag_release.emit(self)
                return True
        return super().eventFilter(obj, event)


class ReorderList(QWidget):
    reordered = Signal(list)

    def __init__(self):
        super().__init__()
        self.setObjectName("listHost")
        self.cards: list[ProviderCard] = []
        self._drag: ProviderCard | None = None
        self._press_global = 0.0
        self._press_y = 0
        self._left = 16
        self._top = 14
        self._gap = 10
        self._allow_drag = True

    def set_cards(self, cards: list[ProviderCard], allow_drag: bool) -> None:
        for card in self.cards:
            card.setParent(None)
            card.deleteLater()
        empty = getattr(self, "_empty", None)
        if empty is not None:
            empty.setParent(None)
            empty.deleteLater()
            self._empty = None
        self.cards = cards
        self._allow_drag = allow_drag
        self._drag = None
        for card in cards:
            card.setParent(self)
            card.drag_press.connect(self._press)
            card.drag_move.connect(self._move)
            card.drag_release.connect(self._release)
            card.grip.setVisible(allow_drag)
            card.show()
        self._fit_width()
        self._place(animate=False)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_width()
        empty = getattr(self, "_empty", None)
        if empty is not None:
            empty.setGeometry(self._left, 24, max(0, self.width() - self._left * 2), 32)
        if self._drag is None:
            self._place(animate=False)

    def _fit_width(self) -> None:
        width = max(0, self.width() - self._left * 2)
        for card in self.cards:
            card.setFixedWidth(width)

    def _press(self, card: ProviderCard, global_y: float) -> None:
        if not self._allow_drag or card not in self.cards:
            return
        self._drag = card
        self._press_global = global_y
        self._press_y = card.y()
        card.setProperty("dragging", "true")
        card.style().unpolish(card)
        card.style().polish(card)
        card.raise_()

    def _move(self, card: ProviderCard, global_y: float) -> None:
        if self._drag is not card:
            return
        y = self._press_y + int(global_y - self._press_global)
        card.move(self._left, max(self._top, y))
        card.raise_()
        self._place(animate=True)

    def _release(self, card: ProviderCard) -> None:
        if self._drag is not card:
            return
        drop = self._drop_index()
        self.cards = [item for item in self.cards if item is not card]
        self.cards.insert(drop, card)
        self._drag = None
        card.setProperty("dragging", "false")
        card.style().unpolish(card)
        card.style().polish(card)
        self._place(animate=True)
        self.reordered.emit([item.provider_id for item in self.cards])

    def _drop_index(self) -> int:
        if self._drag is None:
            return 0
        others = [card for card in self.cards if card is not self._drag]
        center = self._drag.y() + self._drag.height() / 2
        y = self._top
        for index, card in enumerate(others):
            if center < y + card.height() / 2:
                return index
            y += card.height() + self._gap
        return len(others)

    def _targets(self) -> dict[ProviderCard, int]:
        if self._drag is None:
            y = self._top
            found = {}
            for card in self.cards:
                found[card] = y
                y += card.height() + self._gap
            return found
        others = [card for card in self.cards if card is not self._drag]
        drop = self._drop_index()
        y = self._top
        found = {}
        cursor = 0
        for index in range(len(others) + 1):
            if index == drop:
                y += self._drag.height() + self._gap
                continue
            card = others[cursor]
            found[card] = y
            y += card.height() + self._gap
            cursor += 1
        return found

    def _place(self, animate: bool) -> None:
        targets = self._targets()
        bottom = self._top
        for card, y in targets.items():
            self._move_to(card, y, animate)
            bottom = max(bottom, y + card.height() + self._gap)
        if self._drag is not None:
            bottom = max(bottom, self._drag.y() + self._drag.height() + self._gap)
        self.setMinimumHeight(max(bottom + 8, 80))

    def _move_to(self, card: ProviderCard, y: int, animate: bool) -> None:
        target = QPoint(self._left, y)
        if animate and getattr(card, "_target_y", None) == y:
            return
        card._target_y = y
        running = getattr(card, "_slide", None)
        if running is not None:
            running.stop()
            card._slide = None
        if not animate or card.pos() == target:
            card.move(target)
            return
        anim = QPropertyAnimation(card, b"pos", card)
        anim.setDuration(180)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.setStartValue(card.pos())
        anim.setEndValue(target)
        anim.start()
        card._slide = anim


class ColorDot(QPushButton):
    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self.color = color
        self._on = False
        self.setFixedSize(26, 26)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)

    def set_on(self, on: bool) -> None:
        self._on = on
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self._on:
            painter.setPen(QPen(QColor("#111827"), 2))
        else:
            painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(self.color))
        painter.drawEllipse(3, 3, 20, 20)
        painter.end()


def _field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("formLabel")
    return label


def _model_ids(models: list[dict] | None) -> list[str]:
    found: list[str] = []
    for item in models or []:
        name = str(item.get("upstreamId") or item.get("cursorName") or "").strip()
        if name and name not in found:
            found.append(name)
    return found


def _saved_api_key(provider_id: str) -> str:
    for item in read_store().get("providers") or []:
        if item.get("id") == provider_id:
            return str(item.get("apiKey") or "")
    return ""


class ModelFetch(QThread):
    succeeded = Signal(list)
    failed = Signal(str)

    def __init__(self, base_url: str, api_key: str, auth_style: str, protocol: str):
        super().__init__()
        self._base_url = base_url
        self._api_key = api_key
        self._auth_style = auth_style
        self._protocol = protocol

    def run(self) -> None:
        try:
            ids = list_model_ids(self._base_url, self._api_key, self._auth_style, self._protocol)
        except ValueError as error:
            self.failed.emit(str(error))
            return
        except Exception as error:  # noqa: BLE001
            self.failed.emit(str(error) or "获取失败")
            return
        self.succeeded.emit(ids)


class ModelPicker(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._catalog: list[str] = []
        self._chosen: list[str] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.combo = QComboBox()
        self.combo.setObjectName("modelCombo")
        self.combo.activated.connect(self._add_index)
        layout.addWidget(self.combo)
        self.selected_list = QListWidget()
        self.selected_list.setObjectName("selectedModels")
        self.selected_list.setMinimumHeight(140)
        layout.addWidget(self.selected_list, 1)
        self._rebuild()

    def chosen_ids(self) -> list[str]:
        return list(self._chosen)

    def set_models(self, chosen: list[str], catalog: list[str] | None = None) -> None:
        self._chosen = []
        for name in chosen:
            if name and name not in self._chosen:
                self._chosen.append(name)
        base = list(self._chosen if catalog is None else catalog)
        self._catalog = []
        for name in base + self._chosen:
            if name and name not in self._catalog:
                self._catalog.append(name)
        self._rebuild()
        self.changed.emit()

    def merge_catalog(self, ids: list[str]) -> None:
        for name in ids:
            if name and name not in self._catalog:
                self._catalog.append(name)
        self._rebuild()
        self.changed.emit()

    def _add_index(self, index: int) -> None:
        name = self.combo.itemData(index)
        if not name or name in self._chosen:
            self.combo.setCurrentIndex(0)
            return
        self._chosen.append(str(name))
        self._rebuild()
        self.changed.emit()

    def remove(self, name: str) -> None:
        self._chosen = [item for item in self._chosen if item != name]
        self._rebuild()
        self.changed.emit()

    def _rebuild(self) -> None:
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem("选择模型", "")
        available = [name for name in self._catalog if name not in self._chosen]
        if available:
            for name in available:
                self.combo.addItem(name, name)
        else:
            placeholder = "先获取模型列表" if not self._catalog else "已全部选上"
            self.combo.addItem(placeholder, "")
            item = self.combo.model().item(1)
            if item is not None:
                item.setEnabled(False)
        self.combo.setCurrentIndex(0)
        self.combo.blockSignals(False)

        for index in range(self.selected_list.count()):
            widget = self.selected_list.itemWidget(self.selected_list.item(index))
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.selected_list.clear()
        if not self._chosen:
            empty = QListWidgetItem("还没选模型")
            empty.setFlags(Qt.NoItemFlags)
            self.selected_list.addItem(empty)
            return
        for name in self._chosen:
            row_item = QListWidgetItem()
            row_item.setSizeHint(QSize(0, 36))
            self.selected_list.addItem(row_item)
            row = QWidget()
            row.setObjectName("modelRow")
            inner = QHBoxLayout(row)
            inner.setContentsMargins(10, 0, 6, 0)
            inner.setSpacing(8)
            label = QLabel(name)
            label.setObjectName("modelChoice")
            inner.addWidget(label, 1)
            remove = QPushButton("移除")
            remove.setObjectName("modelRemove")
            remove.setCursor(Qt.PointingHandCursor)
            remove.setFocusPolicy(Qt.NoFocus)
            remove.clicked.connect(lambda _checked=False, model=name: self.remove(model))
            inner.addWidget(remove)
            self.selected_list.setItemWidget(row_item, row)


class ProviderDialog(QDialog):
    def __init__(self, parent=None, provider: dict | None = None):
        super().__init__(parent)
        self.provider = provider
        self._color = (provider or {}).get("iconColor") or ICON_COLORS[0]
        self.setWindowTitle("编辑供应商" if provider else "添加供应商")
        self.resize(860, 640)
        self.setMinimumSize(760, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(14)
        title = QLabel("编辑供应商" if provider else "添加供应商")
        title.setObjectName("dialogTitle")
        root.addWidget(title)

        root.addWidget(_field_label("预设供应商"))
        self.preset = QComboBox()
        for item in PRESETS:
            self.preset.addItem(item["label"], item["id"])
        root.addWidget(self.preset)

        columns = QHBoxLayout()
        columns.setSpacing(22)
        left = QVBoxLayout()
        left.setSpacing(8)
        right = QVBoxLayout()
        right.setSpacing(8)

        left.addWidget(_field_label("供应商名称"))
        self.name = QLineEdit((provider or {}).get("name") or "")
        self.name.setPlaceholderText("例如 Packy、公司网关")
        left.addWidget(self.name)

        left.addWidget(_field_label("备注"))
        self.notes = QLineEdit((provider or {}).get("notes") or "")
        self.notes.setPlaceholderText("可选")
        left.addWidget(self.notes)

        left.addWidget(_field_label("官网链接"))
        self.website = QLineEdit((provider or {}).get("website") or "")
        self.website.setPlaceholderText("https://")
        left.addWidget(self.website)

        left.addWidget(_field_label("API Key"))
        key_row = QHBoxLayout()
        key_row.setSpacing(6)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.Password)
        self.api_key.setPlaceholderText("已保存，留空则不修改" if provider and provider.get("hasApiKey") else "sk-...")
        self.eye = QPushButton()
        self.eye.setIcon(_line_icon("eye"))
        self.eye.setIconSize(QSize(16, 16))
        self.eye.setFixedSize(36, 36)
        self.eye.setObjectName("iconBtn")
        self.eye.setCursor(Qt.PointingHandCursor)
        self.eye.setFocusPolicy(Qt.NoFocus)
        self.eye.clicked.connect(self._toggle_key)
        key_row.addWidget(self.api_key, 1)
        key_row.addWidget(self.eye)
        left.addLayout(key_row)

        left.addWidget(_field_label("请求地址"))
        shown_url = (provider or {}).get("baseUrl", "")
        if provider and provider.get("kind") == "demo":
            shown_url = ""
        self.base_url = QLineEdit(shown_url)
        self.base_url.setPlaceholderText("https://api.example.com/v1")
        left.addWidget(self.base_url)

        proto = QHBoxLayout()
        proto.setSpacing(8)
        proto_box = QVBoxLayout()
        proto_box.setSpacing(8)
        proto_box.addWidget(_field_label("协议"))
        self.protocol = QComboBox()
        self.protocol.addItem("OpenAI 兼容", "openai")
        self.protocol.addItem("Anthropic", "anthropic")
        if provider:
            self.protocol.setCurrentIndex(0 if provider.get("protocol") != "anthropic" else 1)
        proto_box.addWidget(self.protocol)
        auth_box = QVBoxLayout()
        auth_box.setSpacing(8)
        auth_box.addWidget(_field_label("认证"))
        self.auth = QComboBox()
        self.auth.addItem("Bearer", "bearer")
        self.auth.addItem("x-api-key", "x-api-key")
        self.auth.addItem("两者都带", "both")
        if provider:
            self.auth.setCurrentIndex({"bearer": 0, "x-api-key": 1, "both": 2}.get(provider.get("authStyle"), 0))
        auth_box.addWidget(self.auth)
        proto.addLayout(proto_box, 1)
        proto.addLayout(auth_box, 1)
        left.addLayout(proto)
        left.addStretch()

        right.addWidget(_field_label("图标颜色"))
        dots = QHBoxLayout()
        dots.setSpacing(6)
        self._dots: list[ColorDot] = []
        for color in ICON_COLORS:
            dot = ColorDot(color)
            dot.clicked.connect(lambda _=False, chosen=color: self._pick_color(chosen))
            self._dots.append(dot)
            dots.addWidget(dot)
        dots.addStretch()
        right.addLayout(dots)
        self._pick_color(self._color if self._color in ICON_COLORS else ICON_COLORS[0])

        right.addWidget(_field_label("模型"))
        fetch_row = QHBoxLayout()
        fetch_row.setSpacing(8)
        self.fetch_btn = QPushButton("获取模型列表")
        self.fetch_btn.setObjectName("ghostText")
        self.fetch_btn.setCursor(Qt.PointingHandCursor)
        self.fetch_btn.setFocusPolicy(Qt.NoFocus)
        self.fetch_btn.setFixedHeight(34)
        self.fetch_btn.clicked.connect(self._fetch_models)
        fetch_row.addWidget(self.fetch_btn)
        self.model_status = QLabel("先填地址和 Key，再获取列表，从下拉里选。")
        self.model_status.setObjectName("modelStatus")
        self.model_status.setWordWrap(True)
        fetch_row.addWidget(self.model_status, 1)
        right.addLayout(fetch_row)
        self.model_picker = ModelPicker()
        self.model_picker.set_models(_model_ids((provider or {}).get("models")))
        right.addWidget(self.model_picker, 1)

        columns.addLayout(left, 1)
        columns.addLayout(right, 1)
        root.addLayout(columns, 1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("取消")
        cancel.setObjectName("ghostText")
        cancel.clicked.connect(self.reject)
        save = QPushButton("保存" if provider else "添加")
        save.setObjectName("primaryBtn")
        save.setDefault(True)
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root.addLayout(buttons)

        self._payload: dict | None = None
        self._fetch: ModelFetch | None = None
        self.preset.currentIndexChanged.connect(self._apply_preset)

    def _save(self) -> None:
        try:
            self._payload = self._build_payload()
        except ValueError as error:
            QMessageBox.warning(self, "还没填完", str(error))
            return
        self.accept()

    def done(self, code: int) -> None:
        self._stop_fetch()
        super().done(code)

    def _stop_fetch(self) -> None:
        worker = self._fetch
        if worker is None:
            return
        self._fetch = None
        try:
            worker.succeeded.disconnect()
            worker.failed.disconnect()
        except RuntimeError:
            pass
        if worker.isRunning():
            worker.finished.connect(worker.deleteLater)
        else:
            worker.deleteLater()

    def _fetch_models(self) -> None:
        base = self.base_url.text().strip()
        if self.provider and self.provider.get("kind") == "demo" and not base:
            self.model_picker.set_models(["echo"], ["echo"])
            self._set_model_status("回显站不用拉列表，用 echo 就行。", error=False)
            return
        if not base.startswith("http"):
            self._set_model_status("先填请求地址", error=True)
            return
        key = self.api_key.text().strip()
        if not key and self.provider and self.provider.get("id"):
            key = _saved_api_key(self.provider["id"])
        if not key:
            self._set_model_status("先填 API Key", error=True)
            return
        self._stop_fetch()
        self.fetch_btn.setEnabled(False)
        self.fetch_btn.setText("获取中…")
        self._set_model_status("正在获取…", error=False)
        worker = ModelFetch(base, key, self.auth.currentData(), self.protocol.currentData())
        worker.succeeded.connect(self._models_loaded)
        worker.failed.connect(self._models_failed)
        self._fetch = worker
        worker.start()

    def _models_loaded(self, ids: list) -> None:
        self._fetch_idle()
        self.model_picker.merge_catalog([str(item) for item in ids])
        self._set_model_status(f"获取到 {len(ids)} 个，从下拉里选。", error=False)

    def _models_failed(self, message: str) -> None:
        self._fetch_idle()
        self._set_model_status(message or "获取失败", error=True)

    def _fetch_idle(self) -> None:
        self.fetch_btn.setEnabled(True)
        self.fetch_btn.setText("获取模型列表")

    def _set_model_status(self, text: str, error: bool) -> None:
        self.model_status.setText(text)
        self.model_status.setProperty("state", "error" if error else "ok")
        self.model_status.style().unpolish(self.model_status)
        self.model_status.style().polish(self.model_status)

    def _toggle_key(self) -> None:
        hidden = self.api_key.echoMode() == QLineEdit.Password
        self.api_key.setEchoMode(QLineEdit.Normal if hidden else QLineEdit.Password)

    def _pick_color(self, color: str) -> None:
        self._color = color
        for dot in self._dots:
            dot.set_on(dot.color == color)

    def _apply_preset(self, index: int) -> None:
        preset = PRESETS[index]
        if preset["id"] == "custom":
            return
        self.name.setText(preset["name"])
        self.website.setText(preset["website"])
        self.base_url.setText(preset["baseUrl"])
        self.protocol.setCurrentIndex(0 if preset["protocol"] == "openai" else 1)
        self.auth.setCurrentIndex({"bearer": 0, "x-api-key": 1, "both": 2}[preset["authStyle"]])
        self.model_picker.set_models(_model_ids(preset["models"]))
        self._pick_color(preset["iconColor"])

    def payload(self) -> dict:
        if self._payload is None:
            self._payload = self._build_payload()
        return self._payload

    def _build_payload(self) -> dict:
        data = {
            "name": self.name.text().strip(),
            "protocol": self.protocol.currentData(),
            "authStyle": self.auth.currentData(),
            "baseUrl": self.base_url.text().strip(),
            "apiKey": self.api_key.text().strip(),
            "models": [
                {"cursorName": name, "upstreamId": name} for name in self.model_picker.chosen_ids()
            ],
            "notes": self.notes.text().strip(),
            "website": self.website.text().strip(),
            "iconColor": self._color,
        }
        if self.provider and self.provider.get("kind") == "demo" and not data["baseUrl"]:
            data["baseUrl"] = "witch://demo"
            data["kind"] = "demo"
        elif data["baseUrl"].startswith("http"):
            data["kind"] = "relay"
        if not data["name"]:
            raise ValueError("名称不能为空")
        if not data["baseUrl"]:
            raise ValueError("请求地址不能为空")
        if not data["models"]:
            raise ValueError("先从下拉里选至少一个模型")
        return data


class ImportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("导入供应商")
        self.resize(520, 420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)
        title = QLabel("导入供应商")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        self.text = QTextEdit()
        self.text.setPlaceholderText(
            "OPENAI_BASE_URL=https://...\nOPENAI_API_KEY=sk-...\nmodel=deepseek-chat"
        )
        self.preview = QLabel("")
        self.preview.setObjectName("formHint")
        self.preview.setWordWrap(True)
        layout.addWidget(self.text, 1)
        layout.addWidget(self.preview)
        self.text.textChanged.connect(self._refresh)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("取消")
        cancel.setObjectName("ghostText")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("导入")
        ok.setObjectName("primaryBtn")
        ok.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        layout.addLayout(buttons)
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


class ModeSwitch(QFrame):
    chosen = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("modeTabs")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(0)
        self._mode = "login"
        self._buttons: dict[str, QPushButton] = {}
        for mode, label, tip in (
            ("api", "API", "不登录。Agent 和 IDE 都走当前中转站。"),
            ("login", "登录", "恢复原版 Cursor，用账号登录。"),
        ):
            button = QPushButton(label)
            button.setObjectName("modeTab")
            button.setCursor(Qt.PointingHandCursor)
            button.setFocusPolicy(Qt.NoFocus)
            button.setToolTip(tip)
            button.clicked.connect(lambda _checked=False, value=mode: self.chosen.emit(value))
            layout.addWidget(button)
            self._buttons[mode] = button
        self.set_mode("login")

    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        self._mode = mode if mode in self._buttons else "login"
        for value, button in self._buttons.items():
            button.setProperty("selected", "true" if value == self._mode else "false")
            button.style().unpolish(button)
            button.style().polish(button)


class SettingsDialog(QDialog):
    def __init__(self, parent: MainWindow):
        super().__init__(parent)
        self.main = parent
        self.setWindowTitle("设置")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)
        self.resize(420, 180)
        title = QLabel("设置")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        hint = QLabel("中转站的地址和 Key 写在供应商卡片里。顶栏的 API / 登录会直接改 Cursor，这里不用再填一把钥匙。")
        hint.setObjectName("formHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        actions = QHBoxLayout()
        for text, slot in (
            ("导出备份", self.main.export_file),
            ("导入备份", self.main.import_file),
        ):
            button = QPushButton(text)
            button.setObjectName("ghostText")
            button.clicked.connect(slot)
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)
        layout.addStretch()
        close = QPushButton("关闭")
        close.setObjectName("primaryBtn")
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(close)
        layout.addLayout(row)


class MainWindow(QWidget):
    def __init__(self, on_change: Callable[[], None] | None = None):
        super().__init__()
        self._on_change = on_change
        self._ready = False
        self._query = ""
        self.setObjectName("root")
        self.setWindowTitle("Witch")
        self.resize(1080, 680)
        self.setMinimumSize(920, 520)
        self._build()
        self.refresh()
        self._ready = True

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header_bar = QFrame()
        header_bar.setObjectName("headerBar")
        header = QHBoxLayout(header_bar)
        header.setContentsMargins(16, 12, 16, 12)
        header.setSpacing(8)

        mark = QLabel()
        mark.setPixmap(_logo_pixmap().scaled(28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        mark.setFixedSize(28, 28)
        header.addWidget(mark)
        title = QLabel("Witch")
        title.setObjectName("appTitle")
        header.addWidget(title)

        settings_btn = QPushButton()
        settings_btn.setIcon(_line_icon("gear", "#374151"))
        settings_btn.setIconSize(QSize(16, 16))
        settings_btn.setToolTip("设置")
        settings_btn.setObjectName("iconBtn")
        settings_btn.setFixedSize(34, 34)
        settings_btn.setCursor(Qt.PointingHandCursor)
        settings_btn.setFocusPolicy(Qt.NoFocus)
        settings_btn.clicked.connect(self.open_settings)
        header.addWidget(settings_btn)

        self.proxy = ProxySwitch()
        self.proxy.setToolTip("本地代理")
        self.proxy.toggled.connect(self._toggle_proxy)
        header.addWidget(self.proxy)

        self.host_chip = QPushButton(_host_text())
        self.host_chip.setObjectName("hostChip")
        self.host_chip.setCursor(Qt.PointingHandCursor)
        self.host_chip.setFocusPolicy(Qt.NoFocus)
        self.host_chip.setToolTip("点击复制 Base URL，填进 Cursor 的 Override OpenAI Base URL")
        self.host_chip.clicked.connect(self.copy_url)
        header.addWidget(self.host_chip)

        self.mode_switch = ModeSwitch()
        self.mode_switch.chosen.connect(self.choose_mode)
        header.addWidget(self.mode_switch)
        self._sync_mode_switch()
        header.addStretch()

        for text, slot, tip in (
            ("导入", self.import_text, "粘贴中转站配置"),
            ("备份", self.export_file, "导出供应商"),
        ):
            button = QPushButton(text)
            button.setObjectName("toolBtn")
            button.setCursor(Qt.PointingHandCursor)
            button.setFocusPolicy(Qt.NoFocus)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            header.addWidget(button)

        add_btn = QPushButton()
        add_btn.setIcon(_line_icon("plus", "#ffffff"))
        add_btn.setIconSize(QSize(16, 16))
        add_btn.setObjectName("addBtn")
        add_btn.setToolTip("添加供应商")
        add_btn.setFixedSize(36, 36)
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.setFocusPolicy(Qt.NoFocus)
        add_btn.clicked.connect(self.add_provider)
        header.addWidget(add_btn)
        root.addWidget(header_bar)

        self.search_row = QFrame()
        self.search_row.setObjectName("searchRow")
        search_layout = QHBoxLayout(self.search_row)
        search_layout.setContentsMargins(16, 0, 16, 10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索名称、备注、地址")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._on_search)
        search_layout.addWidget(self.search)
        self.search_row.hide()
        root.addWidget(self.search_row)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("providerScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.board = ReorderList()
        self.board.reordered.connect(self._commit_order)
        self.scroll.setWidget(self.board)
        root.addWidget(self.scroll, 1)

        QShortcut(QKeySequence.Preferences, self, self.open_settings)
        QShortcut(QKeySequence("Ctrl+N"), self, self.add_provider)
        QShortcut(QKeySequence("Ctrl+I"), self, self.import_text)
        QShortcut(QKeySequence.Find, self, self._open_search)
        QShortcut(QKeySequence(Qt.Key_Escape), self, self._close_search)

    def _open_search(self) -> None:
        self.search_row.show()
        self.search.setFocus()
        self.search.selectAll()

    def _close_search(self) -> None:
        if not self.search_row.isVisible():
            return
        self.search.clear()
        self.search_row.hide()

    def _on_search(self, text: str) -> None:
        self._query = text.strip().lower()
        self.refresh()

    def _matches(self, provider: dict) -> bool:
        if not self._query:
            return True
        blob = " ".join(
            [
                provider.get("name") or "",
                provider.get("notes") or "",
                provider.get("baseUrl") or "",
                provider.get("website") or "",
            ]
        ).lower()
        return self._query in blob

    def set_gateway_status(self, ok: bool, detail: str) -> None:
        self.proxy.blockSignals(True)
        self.proxy.setChecked(ok)
        self.proxy.blockSignals(False)
        self.proxy.setToolTip(detail)
        self.host_chip.setText(_host_text() if ok else "代理已停止")
        self.host_chip.setProperty("ok", "true" if ok else "false")
        self.host_chip.style().unpolish(self.host_chip)
        self.host_chip.style().polish(self.host_chip)

    def _toggle_proxy(self, on: bool) -> None:
        from witch.gateway import start_gateway, stop_gateway

        if not on and read_store().get("cursorMode") == "api":
            self.set_gateway_status(True, gateway_base_url())
            QMessageBox.information(self, "本地代理", "API 模式要靠本地代理把请求送到当前中转站，先别关。")
            return
        if on:
            try:
                start_gateway()
            except RuntimeError as error:
                self.set_gateway_status(False, str(error))
                QMessageBox.warning(self, "本地代理", str(error))
                return
            self.set_gateway_status(True, gateway_base_url())
            return
        stop_gateway()
        self.set_gateway_status(False, "本地代理已停止")

    def refresh(self) -> None:
        state = to_public(read_store())
        bar = self.scroll.verticalScrollBar()
        keep = bar.value()
        providers = [item for item in state["providers"] if self._matches(item)]
        cards = []
        for provider in providers:
            card = ProviderCard(provider, provider["id"] == state["activeProviderId"])
            card.enable.connect(self.enable_provider)
            card.edit.connect(self.edit_provider)
            card.duplicate.connect(self.duplicate_id)
            card.test.connect(self.test_provider)
            card.delete.connect(self.delete_provider)
            cards.append(card)
        self.board.set_cards(cards, allow_drag=not self._query)
        if not cards:
            empty = QLabel("没有匹配的供应商" if self._query else "还没有供应商")
            empty.setObjectName("muted")
            empty.setAlignment(Qt.AlignCenter)
            empty.setParent(self.board)
            empty.setGeometry(16, 24, max(0, self.board.width() - 32), 32)
            empty.show()
            self.board._empty = empty
        bar.setValue(keep)
        if self._ready and self._on_change:
            self._on_change()

    def _commit_order(self, ids: list[str]) -> None:
        if self._query:
            return
        reorder_providers(ids)
        if self._ready and self._on_change:
            self._on_change()

    def _provider(self, provider_id: str) -> dict | None:
        state = to_public(read_store())
        return next((item for item in state["providers"] if item["id"] == provider_id), None)

    def _sync_mode_switch(self) -> None:
        from witch.cursor_mode import CursorModeError, installed_mode

        try:
            mode = installed_mode()
        except CursorModeError:
            mode = read_store().get("cursorMode") or "login"
        self.mode_switch.set_mode(mode)

    def choose_mode(self, mode: str) -> None:
        if mode == self.mode_switch.mode():
            return
        from witch.cursor_mode import CursorModeError, apply_cursor_mode, cursor_binary, cursor_is_running, find_app_root

        try:
            binary = cursor_binary(find_app_root())
        except CursorModeError as error:
            QMessageBox.warning(self, "切换模式", str(error))
            return
        if binary is not None and cursor_is_running(binary):
            answer = QMessageBox.question(self, "切换模式", "要先退出 Cursor，再按这个模式重新打开。继续？")
            if answer != QMessageBox.Yes:
                return
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            result = apply_cursor_mode(mode, relaunch=True, quit_running=True)
        except CursorModeError as error:
            QMessageBox.warning(self, "切换模式", str(error))
            return
        finally:
            QGuiApplication.restoreOverrideCursor()
        self.mode_switch.set_mode(result.mode)
        self.refresh()
        QMessageBox.information(self, "切换模式", result.message)

    def _refresh_api_profile(self) -> None:
        from witch.cursor_mode import CursorModeError, refresh_api_profile

        try:
            refresh_api_profile()
        except CursorModeError as error:
            QMessageBox.warning(self, "API 模式", str(error))

    def enable_provider(self, provider_id: str) -> None:
        activate_provider(provider_id)
        self.refresh()
        self._refresh_api_profile()

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

    def test_provider(self, provider_id: str) -> None:
        store, _active = get_active()
        raw = next((item for item in store["providers"] if item["id"] == provider_id), None)
        if not raw:
            return
        result = run_test(raw)
        record_last_test(provider_id, result)
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
        if self.proxy.isChecked():
            self.host_chip.setText("已复制")
            QTimer.singleShot(900, lambda: self.host_chip.setText(_host_text()))

    def open_settings(self) -> None:
        SettingsDialog(self).exec()

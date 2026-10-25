from __future__ import annotations

from typing import Protocol

from PySide6.QtCore import QMimeData, QObject, QPoint, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QToolButton,
    QWidget,
)

from livevoicebridge.core.speech.models import ReadBlock, ReadBlockKind


class ReadBlockHost(Protocol):
    placeholder: QFrame
    read_block_layout: QHBoxLayout

    def drop_on_placeholder(self, source_id: int) -> None: ...
    def update_read_block_scroll_area_height(self) -> None: ...
    def read_block_widgets(self) -> list[QFrame]: ...


class PlaceholderFrame(QFrame):
    """ドラッグ中の挿入位置を示すプレースホルダーフレーム。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dialog: ReadBlockHost | None = None
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(ReadBlockFrame.MIME_TYPE):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(ReadBlockFrame.MIME_TYPE):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        if event.mimeData().hasFormat(ReadBlockFrame.MIME_TYPE):
            source_id = int(bytes(event.mimeData().data(ReadBlockFrame.MIME_TYPE)).decode("utf-8"))
            if self.dialog is not None:
                self.dialog.drop_on_placeholder(source_id)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class ReadBlockFrame(QFrame):
    """ドラッグ＆ドロップ可能な読み上げブロック用フレーム。"""

    move_requested = Signal(int)
    MIME_TYPE = "application/x-livevoicebridge-read-block"

    def __init__(self, block_id: int, dialog: ReadBlockHost):
        super().__init__()
        self.block_id = block_id
        self.dialog = dialog
        self._drag_start_pos = QPoint()
        self.setAcceptDrops(True)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return
        distance = (event.position().toPoint() - self._drag_start_pos).manhattanLength()
        if distance < QApplication.startDragDistance():
            super().mouseMoveEvent(event)
            return

        mime_data = QMimeData()
        mime_data.setData(self.MIME_TYPE, str(self.block_id).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drag.exec(Qt.DropAction.MoveAction)
        # ドラッグ終了時のクリーンアップ
        self.dialog.placeholder.hide()
        if self.dialog.read_block_layout.indexOf(self.dialog.placeholder) != -1:
            self.dialog.read_block_layout.removeWidget(self.dialog.placeholder)
        self.dialog.update_read_block_scroll_area_height()

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(self.MIME_TYPE):
            source_id = int(bytes(event.mimeData().data(self.MIME_TYPE)).decode("utf-8"))
            if source_id != self.block_id:
                self._update_placeholder_pos(event.position().x(), source_id)
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(self.MIME_TYPE):
            source_id = int(bytes(event.mimeData().data(self.MIME_TYPE)).decode("utf-8"))
            if source_id != self.block_id:
                self._update_placeholder_pos(event.position().x(), source_id)
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        if not event.mimeData().hasFormat(self.MIME_TYPE):
            super().dropEvent(event)
            return
        source_id = int(bytes(event.mimeData().data(self.MIME_TYPE)).decode("utf-8"))
        if source_id != self.block_id:
            self.move_requested.emit(source_id)
        event.acceptProposedAction()

    def _update_placeholder_pos(self, x: float, source_id: int) -> None:
        widgets = self.dialog.read_block_widgets()
        source_widget = next((w for w in widgets if isinstance(w, ReadBlockFrame) and w.block_id == source_id), None)
        if source_widget:
            self.dialog.placeholder.setFixedSize(source_widget.size())

        layout = self.dialog.read_block_layout
        target_index = layout.indexOf(self)

        insert_after = x > (self.width() / 2)
        if insert_after:
            target_index += 1

        current_placeholder_idx = layout.indexOf(self.dialog.placeholder)

        if current_placeholder_idx == target_index:
            return

        if current_placeholder_idx != -1:
            layout.removeWidget(self.dialog.placeholder)

        layout.insertWidget(target_index, self.dialog.placeholder)
        self.dialog.placeholder.show()
        self.dialog.update_read_block_scroll_area_height()


READ_BLOCK_TYPES = {"author", "message", "text"}
DEFAULT_READ_BLOCKS = [{"type": "message"}]


def normalize_read_blocks(blocks: object) -> list[dict]:
    if not isinstance(blocks, list):
        return [block.copy() for block in DEFAULT_READ_BLOCKS]

    normalized = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type not in READ_BLOCK_TYPES:
            continue
        if block_type == "text":
            value = str(block.get("value", ""))
            if value:
                normalized.append({"type": "text", "value": value})
        else:
            normalized.append({"type": block_type})
    return normalized or [block.copy() for block in DEFAULT_READ_BLOCKS]


class ReadBlockEditor(QObject):
    changed = Signal()

    def __init__(self, window: QWidget, blocks: tuple[ReadBlock, ...]):
        super().__init__(window)
        self.dialog_window = window
        self._bind_read_block_widgets()
        self._setup_read_block_placeholder()
        self.set_read_blocks([{"type": block.kind.value, "value": block.value} for block in blocks])
        self.add_author_block_button.clicked.connect(lambda: self.add_read_block("author"))
        self.add_message_block_button.clicked.connect(lambda: self.add_read_block("message"))
        self.add_text_block_button.clicked.connect(lambda: self.add_read_block("text", ""))

    def read(self) -> tuple[ReadBlock, ...]:
        return tuple(ReadBlock(ReadBlockKind(item["type"]), item.get("value", "")) for item in self.get_read_blocks())

    def _bind_read_block_widgets(self) -> None:
        self.read_block_scroll_area: QScrollArea = self.dialog_window.findChild(QScrollArea, "readBlockScrollArea")
        self.read_block_container: QWidget = self.dialog_window.findChild(QWidget, "readBlockScrollContent")
        self.read_block_layout: QHBoxLayout = self.dialog_window.findChild(QHBoxLayout, "readBlockHBoxLayout")
        self.read_block_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.add_author_block_button: QPushButton = self.dialog_window.findChild(QPushButton, "addAuthorBlockButton")
        self.add_message_block_button: QPushButton = self.dialog_window.findChild(QPushButton, "addMessageBlockButton")
        self.add_text_block_button: QPushButton = self.dialog_window.findChild(QPushButton, "addTextBlockButton")
        self._read_block_next_id = 1

    def _setup_read_block_placeholder(self) -> None:
        self.placeholder = self.dialog_window.findChild(PlaceholderFrame, "readBlockPlaceholder")
        self.placeholder.dialog = self
        self.placeholder.hide()

    def set_read_blocks(self, blocks: object) -> None:
        while self.read_block_layout.count():
            item = self.read_block_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for block in normalize_read_blocks(blocks):
            self.add_read_block(block["type"], block.get("value", ""), emit_changed=False)
        self.update_read_block_scroll_area_height()

    def add_read_block(self, block_type: str, value: str = "", emit_changed: bool = True) -> None:
        labels = {
            "author": "投稿者名",
            "message": "本文",
            "text": "テキスト",
        }
        block_id = self._read_block_next_id
        self._read_block_next_id += 1

        block_widget = ReadBlockFrame(block_id, self)
        block_widget.move_requested.connect(self.drop_on_placeholder)
        block_widget.setProperty("blockType", block_type)
        block_widget.setFrameShape(QFrame.Shape.StyledPanel)
        block_widget.setStyleSheet(
            "QFrame { background-color: palette(base); border: 1px solid transparent; }"
            "QFrame:hover { border: 1px solid #3498db; background-color: rgba(52, 152, 219, 20); }"
        )
        layout = QHBoxLayout(block_widget)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(6)
        layout.setSizeConstraint(QHBoxLayout.SizeConstraint.SetFixedSize)

        if block_type != "text":
            title_label = QLabel(labels[block_type])
            title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            layout.addWidget(title_label)

        text_input = None
        if block_type == "text":
            text_input = QLineEdit(value)
            text_input.setPlaceholderText("読み上げる固定テキスト")
            text_input.textChanged.connect(lambda _: self.on_text_block_changed(text_input, block_widget))
            layout.addWidget(text_input)
            self.update_text_block_width(text_input, block_widget)

        delete_button = QToolButton()
        delete_button.setText("×")
        delete_button.setAutoRaise(True)
        delete_button.setToolTip("削除")
        delete_button.setStyleSheet("QToolButton:hover { background-color: #c0392b; color: white; }")
        delete_button.clicked.connect(lambda: self.delete_read_block(block_widget))
        layout.addWidget(delete_button)

        self.read_block_layout.addWidget(block_widget)
        self.update_read_block_scroll_area_height()
        if emit_changed:
            self.changed.emit()

    def update_text_block_width(self, text_input: QLineEdit, block_widget: QFrame) -> None:
        text = text_input.text() or text_input.placeholderText()
        width = text_input.fontMetrics().horizontalAdvance(text) + 36
        text_input.setFixedWidth(max(80, min(width, 360)))
        block_widget.adjustSize()

    def on_text_block_changed(self, text_input: QLineEdit, block_widget: QFrame) -> None:
        self.update_text_block_width(text_input, block_widget)
        self.update_read_block_scroll_area_height()
        self.changed.emit()

    def read_block_widgets(self) -> list[QFrame]:
        widgets = []
        for index in range(self.read_block_layout.count()):
            widget = self.read_block_layout.itemAt(index).widget()
            if widget is not None and widget is not self.placeholder:
                widgets.append(widget)
        return widgets

    def update_read_block_scroll_area_height(self) -> None:
        widgets = self.read_block_widgets()
        height = max((widget.sizeHint().height() for widget in widgets), default=0)
        if height <= 0:
            return
        margins = self.read_block_layout.contentsMargins()
        spacing = self.read_block_layout.spacing() * max(len(widgets) - 1, 0)
        width = sum(widget.sizeHint().width() for widget in widgets)
        self.read_block_container.setMinimumWidth(width + spacing + margins.left() + margins.right())
        frame = self.read_block_scroll_area.frameWidth() * 2
        scrollbar = self.read_block_scroll_area.horizontalScrollBar().sizeHint().height()
        self.read_block_scroll_area.setFixedHeight(height + margins.top() + margins.bottom() + frame + scrollbar)

    def get_read_blocks(self) -> list[dict]:
        blocks = []
        for widget in self.read_block_widgets():
            block_type = widget.property("blockType")
            if block_type == "text":
                text_input = widget.findChild(QLineEdit) if widget else None
                blocks.append({"type": "text", "value": text_input.text() if text_input else ""})
            elif block_type in {"author", "message"}:
                blocks.append({"type": block_type})
        return normalize_read_blocks(blocks)

    def delete_read_block(self, block_widget: QFrame) -> None:
        self.read_block_layout.removeWidget(block_widget)
        block_widget.deleteLater()
        if not self.read_block_widgets():
            self.add_read_block("message", emit_changed=False)
        self.update_read_block_scroll_area_height()
        self.changed.emit()

    def drop_on_placeholder(self, source_id: int) -> None:
        widgets = self.read_block_widgets()
        source_widget = next((widget for widget in widgets if widget.block_id == source_id), None)
        if source_widget is None:
            return
        layout = self.read_block_layout
        target_index = layout.indexOf(self.placeholder)
        if target_index == -1:
            return
        source_index = layout.indexOf(source_widget)
        layout.removeWidget(source_widget)
        if source_index != -1 and source_index < target_index:
            target_index -= 1
        layout.insertWidget(target_index, source_widget)
        self.placeholder.hide()
        layout.removeWidget(self.placeholder)
        self.update_read_block_scroll_area_height()
        self.changed.emit()

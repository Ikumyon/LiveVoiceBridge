from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QMimeData, QPoint, Signal, Qt
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QApplication, QFrame

if TYPE_CHECKING:
    from core.settings_dialog import SettingsDialog


class PlaceholderFrame(QFrame):
    """ドラッグ中の挿入位置を示すプレースホルダーフレーム。"""

    def __init__(self, dialog: SettingsDialog):
        super().__init__()
        self.dialog = dialog
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
            self.dialog.drop_on_placeholder(source_id)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class ReadBlockFrame(QFrame):
    """ドラッグ＆ドロップ可能な読み上げブロック用フレーム。"""

    move_requested = Signal(int)
    MIME_TYPE = "application/x-livevoicebridge-read-block"

    def __init__(self, block_id: int, dialog: SettingsDialog):
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
        source_widget = next((w for w in widgets if w.block_id == source_id), None)
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

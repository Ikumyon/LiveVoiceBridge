from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QWidget

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from main import LiveVoiceBridgeApp


class CommentWindow(QWidget):
    """コメント表示用のPiP（ピクチャーインピクチャー）ウィンドウ。

    常に最前面に表示され、閉じると元のタブ表示に戻る。
    """

    def __init__(self, main_app: LiveVoiceBridgeApp) -> None:
        super().__init__(
            None,
            Qt.WindowType.Window
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowCloseButtonHint,
        )
        self.main_app = main_app
        self.setWindowTitle("コメント（別ウィンドウ）")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self.setLayout(self._layout)

    def attach_list_widget(self, list_widget: QWidget) -> None:
        """QListWidget をこのウィンドウのレイアウトに組み込む。"""
        self._layout.addWidget(list_widget)

    def detach_list_widget(self, list_widget: QWidget) -> None:
        """QListWidget をこのウィンドウのレイアウトから取り外す。"""
        self._layout.removeWidget(list_widget)
        list_widget.setParent(None)

    def closeEvent(self, event) -> None:  # noqa: N802
        """閉じるボタンが押されたらタブ表示に戻す（ウィンドウは破棄しない）。"""
        event.ignore()
        self.main_app.set_comment_popout(False)

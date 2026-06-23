from __future__ import annotations

from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget, QPushButton, QLabel
from PySide6.QtGui import QPainter, QColor

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
            | Qt.WindowType.FramelessWindowHint  # タイトルバーを非表示（枠なし）
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.main_app = main_app
        self.setWindowTitle("コメント（別ウィンドウ）")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        # 背景透過を有効化
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        # 不透明度の設定初期値
        self.opacity = self.main_app.config.get("comment_opacity", 0.8)

        # ドラッグ移動用の位置保持
        self._drag_pos = QPoint()

        # メインの縦レイアウト
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(0)
        self.setLayout(self._main_layout)

        # 自作ヘッダーバーの構築
        self.header_bar = QWidget(self)
        self.header_bar.setObjectName("headerBar")
        self.header_bar.setFixedHeight(28)
        self.header_bar.setStyleSheet("""
            QWidget#headerBar {
                background-color: rgba(20, 20, 20, 200);
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
        """)

        header_layout = QHBoxLayout(self.header_bar)
        header_layout.setContentsMargins(10, 0, 5, 0)
        header_layout.setSpacing(5)

        self.title_label = QLabel("コメントポップアップ", self.header_bar)
        self.title_label.setStyleSheet("color: #cccccc; font-size: 11px; font-weight: bold;")

        self.close_button = QPushButton("×", self.header_bar)
        self.close_button.setFixedSize(20, 20)
        self.close_button.setStyleSheet("""
            QPushButton {
                border: none;
                background-color: transparent;
                color: #aaaaaa;
                font-size: 14px;
                font-weight: bold;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 30);
                color: #ffffff;
            }
            QPushButton:pressed {
                background-color: rgba(255, 255, 255, 50);
            }
        """)
        self.close_button.clicked.connect(self.close_popout)

        header_layout.addWidget(self.title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.close_button)

        self._main_layout.addWidget(self.header_bar)

    def attach_list_widget(self, list_widget: QWidget) -> None:
        """QListWidget をこのウィンドウのレイアウトに組み込む。"""
        self._main_layout.addWidget(list_widget)

    def detach_list_widget(self, list_widget: QWidget) -> None:
        """QListWidget をこのウィンドウのレイアウトから取り外す。"""
        self._main_layout.removeWidget(list_widget)
        list_widget.setParent(None)

    def close_popout(self) -> None:
        self.main_app.set_comment_popout(False)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        """ヘッダーバーをドラッグしたときのみ移動を開始する。"""
        if event.button() == Qt.MouseButton.LeftButton:
            # クリック位置がヘッダーバーの範囲内にあるか判定
            if self.header_bar.rect().contains(self.header_bar.mapFromGlobal(event.globalPosition().toPoint())):
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
            else:
                event.ignore()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        """ウィンドウを移動させる。"""
        if event.buttons() == Qt.MouseButton.LeftButton and not self._drag_pos.isNull():
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
        else:
            event.ignore()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        """ドラッグ状態をクリア。"""
        self._drag_pos = QPoint()
        event.accept()

    def paintEvent(self, event) -> None:  # noqa: N802
        """背景および縁を半透明/不透明で塗りつぶす。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 背景の描画 (configのHEXカラーをQColorにして不透明度アルファ値を適用)
        bg_hex = self.main_app.config.get("comment_bg_color", "#1e1e1e")
        bg_color = QColor(bg_hex)
        bg_color.setAlpha(int(self.opacity * 255))
        painter.fillRect(self.rect(), bg_color)

        # 縁（境界線）の描画
        border_hex = self.main_app.config.get("comment_border_color", "#3c3c3c")
        border_color = QColor(border_hex)
        painter.setPen(border_color)
        painter.drawRect(0, 0, self.width() - 1, self.height() - 1)

    def wheelEvent(self, event) -> None:  # noqa: N802
        """マウスホイールのスクロールで不透明度を調整する。"""
        delta = event.angleDelta().y()
        if delta > 0:
            self.opacity = min(1.0, self.opacity + 0.1)
        elif delta < 0:
            self.opacity = max(0.1, self.opacity - 0.1)

        # 小数点以下の浮動小数点誤差を防ぐために丸める
        self.opacity = round(self.opacity, 1)

        # 設定の保存と画面更新
        self.main_app.config["comment_opacity"] = self.opacity
        self.main_app.save_config()
        self.update()

        self.main_app.append_log(f"[PiP] 背景不透明度を {int(self.opacity * 100)}% に変更しました。")
        event.accept()

    def closeEvent(self, event) -> None:  # noqa: N802
        """閉じるボタンが押されたらタブ表示に戻す（ウィンドウは破棄しない）。"""
        event.ignore()
        self.main_app.set_comment_popout(False)

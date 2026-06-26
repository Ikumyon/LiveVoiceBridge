from __future__ import annotations

from PySide6.QtCore import Qt, QPoint, QEvent
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

        # 各種不透明度の設定初期値
        self._opacity = self.main_app.config.get("comment_opacity", 0.8)
        self._header_opacity = self.main_app.config.get("comment_header_opacity", 0.8)
        self._border_opacity = self.main_app.config.get("comment_border_opacity", 0.8)

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

        self.setMouseTracking(True)
        self.header_bar.setMouseTracking(True)
        self.header_bar.installEventFilter(self)
        self._resize_dir = None
        self._start_geometry = None
        self._start_mouse_pos = None
        self.BORDER_WIDTH = 8
        self.update_header_style()

    def attach_list_widget(self, list_widget: QWidget) -> None:
        """QListWidget をこのウィンドウのレイアウトに組み込む。"""
        self._main_layout.addWidget(list_widget)
        list_widget.setMouseTracking(True)
        list_widget.installEventFilter(self)

    def detach_list_widget(self, list_widget: QWidget) -> None:
        """QListWidget をこのウィンドウのレイアウトから取り外す。"""
        list_widget.removeEventFilter(self)
        self._main_layout.removeWidget(list_widget)
        list_widget.setParent(None)

    def close_popout(self) -> None:
        self.main_app.set_comment_popout(False)

    @property
    def opacity(self) -> float:
        return self._opacity

    @opacity.setter
    def opacity(self, value: float) -> None:
        self._opacity = value
        self.update()

    @property
    def header_opacity(self) -> float:
        return self._header_opacity

    @header_opacity.setter
    def header_opacity(self, value: float) -> None:
        self._header_opacity = value
        self.update_header_style()

    @property
    def border_opacity(self) -> float:
        return self._border_opacity

    @border_opacity.setter
    def border_opacity(self, value: float) -> None:
        self._border_opacity = value
        self.update()

    def update_header_style(self) -> None:
        alpha = int(self._header_opacity * 255)
        self.header_bar.setStyleSheet(f"""
            QWidget#headerBar {{
                background-color: rgba(20, 20, 20, {alpha});
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }}
        """)

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.MouseMove:
            local_pos = self.mapFromGlobal(event.globalPosition().toPoint())
            self.handle_mouse_move(local_pos, event.globalPosition().toPoint())
            if self._resize_dir:
                return True
        elif event.type() == QEvent.Type.MouseButtonPress:
            local_pos = self.mapFromGlobal(event.globalPosition().toPoint())
            if self.handle_mouse_press(local_pos, event.globalPosition().toPoint(), event.button()):
                return True
        elif event.type() == QEvent.Type.MouseButtonRelease:
            if self.handle_mouse_release(event.button()):
                return True
        return super().eventFilter(obj, event)

    def handle_mouse_move(self, local_pos: QPoint, global_pos: QPoint) -> None:
        if self._resize_dir:
            delta = global_pos - self._start_mouse_pos
            new_geom = self._start_geometry
            w = new_geom.width()
            h = new_geom.height()
            
            if "right" in self._resize_dir:
                w = max(200, new_geom.width() + delta.x())
            if "bottom" in self._resize_dir:
                h = max(200, new_geom.height() + delta.y())
                
            self.resize(w, h)
            self.update()
        else:
            on_right = local_pos.x() >= self.width() - self.BORDER_WIDTH
            on_bottom = local_pos.y() >= self.height() - self.BORDER_WIDTH
            
            if on_right and on_bottom:
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif on_right:
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif on_bottom:
                self.setCursor(Qt.CursorShape.SizeVerCursor)
            else:
                self.unsetCursor()

    def handle_mouse_press(self, local_pos: QPoint, global_pos: QPoint, button: Qt.MouseButton) -> bool:
        if button == Qt.MouseButton.LeftButton:
            on_right = local_pos.x() >= self.width() - self.BORDER_WIDTH
            on_bottom = local_pos.y() >= self.height() - self.BORDER_WIDTH
            
            direction = ""
            if on_bottom:
                direction += "bottom"
            if on_right:
                direction += "_right" if direction else "right"
                
            if direction:
                self._resize_dir = direction
                self._start_geometry = self.geometry()
                self._start_mouse_pos = global_pos
                return True
        return False

    def handle_mouse_release(self, button: Qt.MouseButton) -> bool:
        if button == Qt.MouseButton.LeftButton and self._resize_dir:
            self._resize_dir = None
            self._start_geometry = None
            self._start_mouse_pos = None
            
            # サイズ変更後の値をconfigに保存
            geo = self.geometry()
            self.main_app.config["comment_win_w"] = geo.width()
            self.main_app.config["comment_win_h"] = geo.height()
            self.main_app.save_config()
            return True
        return False

    def mousePressEvent(self, event) -> None:  # noqa: N802
        local_pos = event.position().toPoint()
        global_pos = event.globalPosition().toPoint()
        
        if self.handle_mouse_press(local_pos, global_pos, event.button()):
            event.accept()
            return
            
        if event.button() == Qt.MouseButton.LeftButton:
            if self.header_bar.rect().contains(self.header_bar.mapFromGlobal(event.globalPosition().toPoint())):
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
            else:
                event.ignore()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        local_pos = event.position().toPoint()
        global_pos = event.globalPosition().toPoint()
        
        self.handle_mouse_move(local_pos, global_pos)
        
        if not self._resize_dir and event.buttons() == Qt.MouseButton.LeftButton and not self._drag_pos.isNull():
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
        else:
            event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self.handle_mouse_release(event.button()):
            event.accept()
            return
            
        self._drag_pos = QPoint()
        event.accept()

    def paintEvent(self, event) -> None:  # noqa: N802
        """背景および縁を半透明/不透明で塗りつぶす。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 背景の描画 (configのHEXカラーをQColorにして不透明度アルファ値を適用)
        bg_hex = self.main_app.config.get("comment_bg_color", "#1e1e1e")
        bg_color = QColor(bg_hex)
        bg_color.setAlpha(int(self._opacity * 255))
        painter.fillRect(self.rect(), bg_color)

        # 縁（境界線）の描画
        border_hex = self.main_app.config.get("comment_border_color", "#3c3c3c")
        border_color = QColor(border_hex)
        border_color.setAlpha(int(self._border_opacity * 255))
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

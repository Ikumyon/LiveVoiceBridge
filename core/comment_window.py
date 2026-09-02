from __future__ import annotations

from PySide6.QtCore import Qt, QPoint, QEvent, QTimer
from PySide6.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QPushButton,
    QLabel,
    QSplitter,
)
from PySide6.QtGui import QPainter, QColor

from core.ui.popup_metrics import POPUP_METRIC_PLACEMENTS, PopupMetricsPanel

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

        self.content_splitter = QSplitter(Qt.Orientation.Vertical, self)
        self.content_splitter.setChildrenCollapsible(False)
        self.metrics_panel = PopupMetricsPanel(self.content_splitter)
        self.metrics_panel.set_background_opacity(self._opacity)
        self.metrics_panel.visibility_changed.connect(self._refresh_metrics_visibility)
        self.content_splitter.splitterMoved.connect(self._on_splitter_moved)
        self._main_layout.addWidget(self.content_splitter, 1)

        self._attached_list_widget: QWidget | None = None
        self._applying_splitter_layout = False
        self._metrics_settings = self.main_app.config.get("popup_metrics", {})
        self._splitter_save_timer = QTimer(self)
        self._splitter_save_timer.setSingleShot(True)
        self._splitter_save_timer.setInterval(250)
        self._splitter_save_timer.timeout.connect(self.main_app.save_config)
        self.apply_metrics_settings(self._metrics_settings)

        self.setMouseTracking(True)
        self.header_bar.setMouseTracking(True)
        self.header_bar.installEventFilter(self)
        self._resize_edges: set[str] = set()
        self._start_geometry = None
        self._start_mouse_pos = None
        self._filtered_list_widget: QWidget | None = None
        self._filtered_list_viewport: QWidget | None = None
        self.MIN_WIDTH = 200
        self.MIN_HEIGHT = 200
        self.RESIZE_MARGIN = 8
        self.setMinimumSize(self.MIN_WIDTH, self.MIN_HEIGHT)
        self.update_header_style()

    def attach_list_widget(self, list_widget: QWidget) -> None:
        """QListWidget をこのウィンドウのレイアウトに組み込む。"""
        self._attached_list_widget = list_widget
        self._configure_splitter()
        list_widget.setMouseTracking(True)
        list_widget.installEventFilter(self)
        self._filtered_list_widget = list_widget

        viewport = getattr(list_widget, "viewport", lambda: None)()
        if viewport is not None:
            viewport.setMouseTracking(True)
            viewport.installEventFilter(self)
            self._filtered_list_viewport = viewport

    def detach_list_widget(self, list_widget: QWidget) -> None:
        """QListWidget をこのウィンドウのレイアウトから取り外す。"""
        if self._filtered_list_viewport is not None:
            self._filtered_list_viewport.removeEventFilter(self)
            self._filtered_list_viewport = None
        self._filtered_list_widget = None
        list_widget.removeEventFilter(self)
        self._attached_list_widget = None
        list_widget.setParent(None)

    def apply_metrics_settings(self, settings: dict | None = None) -> None:
        """PiPメトリクスの表示モード・配置・分割比率を反映する。"""
        source = settings if isinstance(settings, dict) else {}
        placement = source.get("placement", "top")
        if placement not in POPUP_METRIC_PLACEMENTS:
            placement = "top"
        display_modes = source.get("display_modes", {})
        if not isinstance(display_modes, dict):
            display_modes = {}
        self._metrics_settings = {
            "placement": placement,
            "vertical_ratio": self._safe_ratio(source.get("vertical_ratio", 0.35)),
            "horizontal_ratio": self._safe_ratio(source.get("horizontal_ratio", 0.35)),
            "display_modes": dict(display_modes),
        }
        self.metrics_panel.set_display_modes(self._metrics_settings["display_modes"])
        self._configure_splitter()

    def update_metrics(self, data: dict) -> None:
        self.metrics_panel.update_metrics(data)
        self._refresh_metrics_visibility(self.metrics_panel.has_visible_metrics())

    def update_youtube_connections(self, count: int) -> None:
        self.metrics_panel.update_youtube_connections(count)

    @staticmethod
    def _safe_ratio(value: object) -> float:
        try:
            return max(0.1, min(float(value), 0.9))
        except (TypeError, ValueError):
            return 0.35

    def _configure_splitter(self) -> None:
        placement = self._metrics_settings.get("placement", "top")
        orientation = (
            Qt.Orientation.Vertical
            if placement in {"top", "bottom"}
            else Qt.Orientation.Horizontal
        )

        self._applying_splitter_layout = True
        self.content_splitter.setOrientation(orientation)
        widgets = [self.metrics_panel]
        if self._attached_list_widget is not None:
            widgets.append(self._attached_list_widget)
        for widget in widgets:
            widget.setParent(None)

        metrics_first = placement in {"top", "left"}
        if metrics_first:
            self.content_splitter.addWidget(self.metrics_panel)
            if self._attached_list_widget is not None:
                self.content_splitter.addWidget(self._attached_list_widget)
        else:
            if self._attached_list_widget is not None:
                self.content_splitter.addWidget(self._attached_list_widget)
            self.content_splitter.addWidget(self.metrics_panel)

        self._refresh_metrics_visibility(self.metrics_panel.has_visible_metrics())
        self._applying_splitter_layout = False
        QTimer.singleShot(0, self._apply_splitter_ratio)

    def _refresh_metrics_visibility(self, visible: bool) -> None:
        self.metrics_panel.setVisible(visible)
        if self._attached_list_widget is not None:
            self._attached_list_widget.setVisible(True)
        if visible:
            QTimer.singleShot(0, self._apply_splitter_ratio)

    def _apply_splitter_ratio(self) -> None:
        if self.metrics_panel.isHidden() or self._attached_list_widget is None:
            return
        placement = self._metrics_settings.get("placement", "top")
        ratio_key = "vertical_ratio" if placement in {"top", "bottom"} else "horizontal_ratio"
        ratio = self._safe_ratio(self._metrics_settings.get(ratio_key, 0.35))
        total = (
            self.content_splitter.height()
            if self.content_splitter.orientation() == Qt.Orientation.Vertical
            else self.content_splitter.width()
        )
        total = max(total - self.content_splitter.handleWidth(), 2)
        metrics_size = max(1, round(total * ratio))
        comments_size = max(1, total - metrics_size)
        self._applying_splitter_layout = True
        if self.content_splitter.indexOf(self.metrics_panel) == 0:
            self.content_splitter.setSizes([metrics_size, comments_size])
        else:
            self.content_splitter.setSizes([comments_size, metrics_size])
        self._applying_splitter_layout = False

    def _on_splitter_moved(self, position: int, index: int) -> None:
        if self._applying_splitter_layout or self.metrics_panel.isHidden():
            return
        sizes = self.content_splitter.sizes()
        metrics_index = self.content_splitter.indexOf(self.metrics_panel)
        if metrics_index < 0 or not sizes or sum(sizes) <= 0:
            return
        ratio = sizes[metrics_index] / sum(sizes)
        ratio_key = (
            "vertical_ratio"
            if self.content_splitter.orientation() == Qt.Orientation.Vertical
            else "horizontal_ratio"
        )
        ratio = self._safe_ratio(ratio)
        self._metrics_settings[ratio_key] = ratio
        popup_config = self.main_app.config.setdefault("popup_metrics", {})
        popup_config[ratio_key] = ratio
        self._splitter_save_timer.start()

    def close_popout(self) -> None:
        self.main_app.set_comment_popout(False)

    @property
    def opacity(self) -> float:
        return self._opacity

    @opacity.setter
    def opacity(self, value: float) -> None:
        self._opacity = value
        if hasattr(self, "metrics_panel"):
            self.metrics_panel.set_background_opacity(value)
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
            if self._resize_edges:
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
        if self._resize_edges:
            delta = global_pos - self._start_mouse_pos
            new_geom = self._start_geometry
            left = new_geom.left()
            top = new_geom.top()
            right = new_geom.right()
            bottom = new_geom.bottom()

            if "left" in self._resize_edges:
                left = min(new_geom.left() + delta.x(), right - self.MIN_WIDTH + 1)
            if "right" in self._resize_edges:
                right = max(new_geom.right() + delta.x(), left + self.MIN_WIDTH - 1)
            if "top" in self._resize_edges:
                top = min(new_geom.top() + delta.y(), bottom - self.MIN_HEIGHT + 1)
            if "bottom" in self._resize_edges:
                bottom = max(new_geom.bottom() + delta.y(), top + self.MIN_HEIGHT - 1)

            self.setGeometry(left, top, right - left + 1, bottom - top + 1)
            self.update()
        else:
            edges = self.resize_edges_at(local_pos)
            if edges in ({"top", "left"}, {"bottom", "right"}):
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif edges in ({"top", "right"}, {"bottom", "left"}):
                self.setCursor(Qt.CursorShape.SizeBDiagCursor)
            elif "left" in edges or "right" in edges:
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif "top" in edges or "bottom" in edges:
                self.setCursor(Qt.CursorShape.SizeVerCursor)
            else:
                self.unsetCursor()

    def handle_mouse_press(self, local_pos: QPoint, global_pos: QPoint, button: Qt.MouseButton) -> bool:
        if button == Qt.MouseButton.LeftButton:
            edges = self.resize_edges_at(local_pos)
            if edges:
                self._resize_edges = edges
                self._start_geometry = self.geometry()
                self._start_mouse_pos = global_pos
                self.grabMouse()
                return True
        return False

    def handle_mouse_release(self, button: Qt.MouseButton) -> bool:
        if button == Qt.MouseButton.LeftButton and self._resize_edges:
            self._resize_edges = set()
            self._start_geometry = None
            self._start_mouse_pos = None
            self.releaseMouse()
            
            # サイズ変更後の値をconfigに保存
            geo = self.geometry()
            self.main_app.config["comment_win_w"] = geo.width()
            self.main_app.config["comment_win_h"] = geo.height()
            self.main_app.save_config()
            return True
        return False

    def resize_edges_at(self, local_pos: QPoint) -> set[str]:
        edges = set()
        margin = self.RESIZE_MARGIN

        if local_pos.x() <= margin:
            edges.add("left")
        elif local_pos.x() >= self.width() - margin:
            edges.add("right")

        if local_pos.y() <= margin:
            edges.add("top")
        elif local_pos.y() >= self.height() - margin:
            edges.add("bottom")

        return edges

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
        
        if not self._resize_edges and event.buttons() == Qt.MouseButton.LeftButton and not self._drag_pos.isNull():
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

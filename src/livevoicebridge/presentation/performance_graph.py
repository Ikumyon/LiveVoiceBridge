from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget


class PerformanceGraphWidget(QWidget):
    """リアルタイムパフォーマンス推移グラフウィジェット (マルチライン対応)"""

    def __init__(self, title: str, color: QColor | list[QColor], unit: str = "%", max_val: float = 100.0, parent=None):
        super().__init__(parent)
        self.title = title
        self.unit = unit
        self.max_val = max_val

        # 系列色
        if isinstance(color, list):
            self.line_colors = color
        else:
            self.line_colors = [color]

        # 各系列の履歴リスト [[val_s0_0, val_s0_1, ...], [val_s1_0, ...]]
        self.data_histories = [[0.0] * 60 for _ in self.line_colors]

        self.setMinimumHeight(130)
        self.setMaximumHeight(180)
        self.setMinimumWidth(0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)

        self.title_label = QLabel(self.title, self)
        font = QFont()
        font.setBold(True)
        self.title_label.setFont(font)
        self.title_label.setStyleSheet("color: #E0E0E0;")
        self.title_label.setMinimumWidth(0)
        self.title_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )

        self.value_label = QLabel(f"0.0 {self.unit}", self)
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        main_color_str = self.line_colors[0].name()
        self.value_label.setStyleSheet(f"color: {main_color_str}; font-weight: bold;")
        self.value_label.setMinimumWidth(0)
        self.value_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )

        # ラベル文字列の sizeHint をレイアウト幅へ反映させると、Elide 更新時に
        # resizeEvent が再帰し得る。幅はストレッチで固定的に配分する。
        header_layout.addWidget(self.title_label, 2)
        header_layout.addWidget(self.value_label, 3)
        layout.addLayout(header_layout)
        layout.addStretch(1)

        self.raw_title = title
        self.raw_value_text = f"0.0 {self.unit}"
        self._elide_update_pending = False

    def add_value(
        self,
        val: float | list[float],
        display_text: str | None = None,
        dynamic_max: float | None = None,
    ):
        """単一または複数の値を追加してグラフを更新"""
        if dynamic_max and dynamic_max > 0:
            self.max_val = dynamic_max

        if not isinstance(val, list):
            vals = [val]
        else:
            vals = val

        # 系列数の調整
        while len(self.data_histories) < len(vals):
            self.data_histories.append([0.0] * 60)
            if len(self.line_colors) < len(self.data_histories):
                self.line_colors.append(QColor(0, 230, 118))

        for idx, v in enumerate(vals):
            self.data_histories[idx].append(v)
            if len(self.data_histories[idx]) > 60:
                self.data_histories[idx].pop(0)

        if display_text:
            self.raw_value_text = display_text
        else:
            self.raw_value_text = f"{vals[0]:.1f} {self.unit}"

        self._update_elided_labels()
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_elided_labels_update()

    def _schedule_elided_labels_update(self):
        """レイアウト処理の完了後に一度だけ省略表示を更新する。"""
        if self._elide_update_pending:
            return
        self._elide_update_pending = True
        QTimer.singleShot(0, self._run_elided_labels_update)

    def _run_elided_labels_update(self):
        self._elide_update_pending = False
        self._update_elided_labels()

    def _update_elided_labels(self):
        """カード幅に合わせてタイトルと値を ... (Elide) 省略更新"""
        from PySide6.QtGui import QFontMetrics

        title_font = self.title_label.font()
        value_font = self.value_label.font()
        fm_t = QFontMetrics(title_font)
        fm_v = QFontMetrics(value_font)

        title_text = fm_t.elidedText(
            self.raw_title,
            Qt.TextElideMode.ElideRight,
            max(self.title_label.width(), 20),
        )
        value_text = fm_v.elidedText(
            self.raw_value_text,
            Qt.TextElideMode.ElideRight,
            max(self.value_label.width(), 20),
        )

        # 不要な setText はスタイル・レイアウトの再評価も発生させるため避ける。
        if self.title_label.text() != title_text:
            self.title_label.setText(title_text)
        if self.value_label.text() != value_text:
            self.value_label.setText(value_text)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 背景
        bg_rect = self.rect()
        painter.fillRect(bg_rect, QColor(25, 27, 32))

        # グラフ描画枠の決定
        header_height = 30
        margin = 10
        left = margin
        right = self.width() - margin
        top = header_height
        bottom = self.height() - margin
        graph_w = max(right - left, 10)
        graph_h = max(bottom - top, 10)

        # グリッド線描画
        painter.setPen(QPen(QColor(45, 48, 55), 1, Qt.PenStyle.DashLine))
        for i in range(1, 4):
            y = top + (graph_h * i / 4.0)
            painter.drawLine(int(left), int(y), int(right), int(y))

        max_v = max(self.max_val, 0.001)

        # 各系列の描画 (重ね描き)
        for s_idx, history in enumerate(self.data_histories):
            if len(history) < 2:
                continue

            color = self.line_colors[s_idx % len(self.line_colors)]
            num_pts = len(history)
            step_x = graph_w / float(num_pts - 1)

            points = []
            for i, val in enumerate(history):
                x = left + (i * step_x)
                normalized = max(0.0, min(val / max_v, 1.0))
                y = bottom - (normalized * graph_h)
                points.append(QPointF(x, y))

            # 塗りつぶし領域
            path = QPainterPath()
            path.moveTo(points[0])
            for p in points[1:]:
                path.lineTo(p)

            fill_path = QPainterPath(path)
            fill_path.lineTo(points[-1].x(), bottom)
            fill_path.lineTo(points[0].x(), bottom)
            fill_path.closeSubpath()

            # グラデーション塗り
            grad = QLinearGradient(0, top, 0, bottom)
            c_start = QColor(color)
            c_start.setAlpha(40)
            c_end = QColor(color)
            c_end.setAlpha(2)
            grad.setColorAt(0.0, c_start)
            grad.setColorAt(1.0, c_end)

            painter.fillPath(fill_path, QBrush(grad))

            # メイン線描画
            pen = QPen(color, 2)
            painter.setPen(pen)
            painter.drawPath(path)

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

POPUP_METRIC_MODES = {
    "hidden": "非表示",
    "text": "文字のみ",
    "both": "文字＋グラフ",
}

POPUP_METRIC_PLACEMENTS = {
    "top": "上",
    "bottom": "下",
    "left": "左",
    "right": "右",
}


@dataclass(frozen=True)
class MetricDescriptor:
    metric_id: str
    title: str
    colors: tuple[QColor, ...]
    max_value: float
    order: int


FIXED_METRIC_DESCRIPTORS = (
    MetricDescriptor("cpu", "CPU 使用率", (QColor(0, 210, 255),), 100.0, 0),
    MetricDescriptor("ram", "メモリ (RAM) 使用量", (QColor(255, 215, 64),), 100.0, 1),
    MetricDescriptor("network", "ネットワーク通信速度", (QColor(255, 145, 0), QColor(0, 210, 255)), 1024.0, 2),
    MetricDescriptor("youtube_connections", "YouTube 同時接続数", (QColor(255, 82, 82),), 4.0, 3),
    MetricDescriptor("npu", "NPU 使用率", (QColor(179, 136, 255),), 100.0, 4),
)

APP_METRIC_IDS = {"youtube_connections"}


def fixed_metric_catalog() -> list[dict[str, str]]:
    return [
        {"id": item.metric_id, "title": item.title}
        for item in FIXED_METRIC_DESCRIPTORS
        if item.metric_id in APP_METRIC_IDS
    ]


def clean_gpu_name(name: str, index: int) -> str:
    clean_name = name.replace(f"GPU {index} (", f"GPU {index}: ").rstrip(")")
    return clean_name.replace(" (8GB)", "").replace("(TM)", "").replace("(R)", "")


def metric_catalog_from_data(data: dict) -> list[dict[str, str]]:
    available = {str(metric_id) for metric_id in data.get("available_metrics", [])}
    catalog = [
        {"id": item.metric_id, "title": item.title}
        for item in FIXED_METRIC_DESCRIPTORS
        if item.metric_id in APP_METRIC_IDS or item.metric_id in available
    ]
    for index, gpu_info in enumerate(data.get("gpus", [])):
        gpu_id = str(gpu_info.get("id", f"gpu_{index}"))
        title = clean_gpu_name(str(gpu_info.get("name", f"GPU {index}")), index)
        catalog.append({"id": f"gpu:{gpu_id}", "title": title})
    return catalog


class PopupMetricCard(QWidget):
    """コメントPiP用の文字／スパークライン表示カード。"""

    def __init__(self, descriptor: MetricDescriptor, mode: str, parent=None) -> None:
        super().__init__(parent)
        self.descriptor = descriptor
        self.mode = "text"
        self.max_value = descriptor.max_value
        self.background_opacity = 0.8
        self.histories = [[0.0] * 60 for _ in descriptor.colors]
        self.raw_value_text = "--"

        self.setMinimumWidth(80)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.card_layout = QVBoxLayout(self)
        self.card_layout.setContentsMargins(8, 0, 8, 0)
        self.card_layout.setSpacing(0)
        self.card_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(4)

        self.title_label = QLabel(descriptor.title, self)
        font = QFont(self.title_label.font())
        font.setBold(True)
        self.title_label.setFont(font)
        self.title_label.setStyleSheet("color: #f0f0f0;")
        self.title_label.setMinimumWidth(0)

        self.value_label = QLabel("--", self)
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.value_label.setStyleSheet(f"color: {descriptor.colors[0].name()}; font-weight: bold;")
        self.value_label.setMinimumWidth(0)

        header.addWidget(self.title_label)
        header.addStretch(1)
        header.addWidget(self.value_label)
        self.card_layout.addLayout(header)
        self.set_mode(mode)

    def set_mode(self, mode: str) -> None:
        if mode not in {"text", "both"}:
            mode = "text"
        self.mode = mode
        if mode == "text":
            self.setFixedHeight(28)
            self.card_layout.setContentsMargins(8, 0, 8, 0)
            self.card_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        else:
            self.setFixedHeight(112)
            self.card_layout.setContentsMargins(8, 6, 8, 6)
            self.card_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.update()

    def set_background_opacity(self, opacity: float) -> None:
        self.background_opacity = max(0.0, min(float(opacity), 1.0))
        self.update()

    def add_value(
        self,
        value: float | list[float],
        display_text: str,
        dynamic_max: float | None = None,
    ) -> None:
        values = value if isinstance(value, list) else [value]
        while len(self.histories) < len(values):
            self.histories.append([0.0] * 60)
        for index, current in enumerate(values):
            self.histories[index].append(float(current))
            if len(self.histories[index]) > 60:
                self.histories[index].pop(0)
        if dynamic_max is not None and dynamic_max > 0:
            self.max_value = float(dynamic_max)
        self.raw_value_text = display_text
        self._update_elided_labels()
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_elided_labels()

    def _update_elided_labels(self) -> None:
        title_font = self.title_label.font()
        value_font = self.value_label.font()
        title_metrics = QFontMetrics(title_font)
        value_metrics = QFontMetrics(value_font)

        available_width = max(self.width() - 22, 20)

        full_title = self.descriptor.title
        full_value = self.raw_value_text

        req_title_w = title_metrics.horizontalAdvance(full_title)
        req_val_w = value_metrics.horizontalAdvance(full_value)

        if req_title_w + req_val_w <= available_width:
            self.title_label.setText(full_title)
            self.value_label.setText(full_value)
            return

        max_val_allowed = max(int(available_width * 0.75), 40)
        allocated_val_w = min(req_val_w, max_val_allowed)
        allocated_title_w = max(available_width - allocated_val_w, 20)

        self.title_label.setText(
            title_metrics.elidedText(
                full_title,
                Qt.TextElideMode.ElideRight,
                allocated_title_w,
            )
        )
        self.value_label.setText(
            value_metrics.elidedText(
                full_value,
                Qt.TextElideMode.ElideRight,
                allocated_val_w,
            )
        )

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(
            self.rect(),
            QColor(20, 22, 27, round(210 * self.background_opacity)),
        )

        if self.mode != "both":
            return

        left = 8
        right = self.width() - 8
        top = 31
        bottom = self.height() - 7
        graph_width = max(right - left, 10)
        graph_height = max(bottom - top, 10)

        painter.setPen(QPen(QColor(80, 83, 90, 150), 1, Qt.PenStyle.DashLine))
        for index in range(1, 3):
            y = top + graph_height * index / 3.0
            painter.drawLine(left, int(y), right, int(y))

        maximum = max(self.max_value, 0.001)
        for series_index, history in enumerate(self.histories):
            if len(history) < 2:
                continue
            color = self.descriptor.colors[series_index % len(self.descriptor.colors)]
            step_x = graph_width / float(len(history) - 1)
            points = []
            for index, current in enumerate(history):
                normalized = max(0.0, min(float(current) / maximum, 1.0))
                points.append(QPointF(left + index * step_x, bottom - normalized * graph_height))

            path = QPainterPath()
            path.moveTo(points[0])
            for point in points[1:]:
                path.lineTo(point)

            fill_path = QPainterPath(path)
            fill_path.lineTo(points[-1].x(), bottom)
            fill_path.lineTo(points[0].x(), bottom)
            fill_path.closeSubpath()
            gradient = QLinearGradient(0, top, 0, bottom)
            start_color = QColor(color)
            start_color.setAlpha(45)
            end_color = QColor(color)
            end_color.setAlpha(2)
            gradient.setColorAt(0.0, start_color)
            gradient.setColorAt(1.0, end_color)
            painter.fillPath(fill_path, QBrush(gradient))
            painter.setPen(QPen(color, 2))
            painter.drawPath(path)


class PopupMetricsPanel(QScrollArea):
    """表示設定に従ってメトリクスカードを自動グリッド配置する。"""

    COLUMN_MIN_WIDTH_TEXT = 180
    COLUMN_MIN_WIDTH_BOTH = 260

    visibility_changed = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet("QScrollArea { background: transparent; }")

        self.content = QWidget(self)
        self.content.setStyleSheet("background: transparent;")
        self.grid = QGridLayout(self.content)
        self.grid.setContentsMargins(4, 4, 4, 4)
        self.grid.setHorizontalSpacing(6)
        self.grid.setVerticalSpacing(6)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.setWidget(self.content)

        self.display_modes: dict[str, str] = {}
        self.descriptors = {descriptor.metric_id: descriptor for descriptor in FIXED_METRIC_DESCRIPTORS}
        self.cards: dict[str, PopupMetricCard] = {}
        self._column_count = 0
        self._background_opacity = 0.8

    def _get_column_min_width(self) -> int:
        has_graph = any(card.mode == "both" for card in self.cards.values())
        return self.COLUMN_MIN_WIDTH_BOTH if has_graph else self.COLUMN_MIN_WIDTH_TEXT

    def has_visible_metrics(self) -> bool:
        return bool(self.cards)

    def set_display_modes(self, display_modes: dict[str, str]) -> None:
        self.display_modes = {
            str(metric_id): mode for metric_id, mode in display_modes.items() if mode in POPUP_METRIC_MODES
        }
        self._sync_cards()

    def set_background_opacity(self, opacity: float) -> None:
        self._background_opacity = max(0.0, min(float(opacity), 1.0))
        for card in self.cards.values():
            card.set_background_opacity(self._background_opacity)

    def update_metrics(self, data: dict) -> None:
        for index, gpu_info in enumerate(data.get("gpus", [])):
            raw_id = str(gpu_info.get("id", f"gpu_{index}"))
            metric_id = f"gpu:{raw_id}"
            title = clean_gpu_name(str(gpu_info.get("name", f"GPU {index}")), index)
            self.descriptors[metric_id] = MetricDescriptor(
                metric_id,
                title,
                (QColor(0, 230, 118), QColor(255, 64, 129)),
                100.0,
                100 + index,
            )
        self._sync_cards()

        self._add_if_present("cpu", data.get("cpu_percent", 0.0), f"{data.get('cpu_percent', 0.0):.1f} %")
        ram_text = (
            f"{data.get('ram_used_gb', 0.0):.2f} / "
            f"{data.get('ram_total_gb', 0.0):.1f} GB "
            f"({data.get('ram_percent', 0.0):.1f}%)"
        )
        self._add_if_present("ram", data.get("ram_percent", 0.0), ram_text)

        net_send = float(data.get("net_send_speed_kb", 0.0))
        net_recv = float(data.get("net_recv_speed_kb", 0.0))

        def _fmt_net(kb: float) -> str:
            return f"{kb / 1024.0:.2f} MB/s" if kb >= 1024.0 else f"{kb:.1f} KB/s"

        network_text = f"↓ {_fmt_net(net_recv)}  ↑ {_fmt_net(net_send)}"
        max_speed = max((net_send + net_recv) * 1.5, 100.0)
        self._add_if_present("network", [net_recv, net_send], network_text, max_speed)

        for index, gpu_info in enumerate(data.get("gpus", [])):
            raw_id = str(gpu_info.get("id", f"gpu_{index}"))
            metric_id = f"gpu:{raw_id}"
            gpu_percent = float(gpu_info.get("gpu_percent", 0.0))
            vram_percent = float(gpu_info.get("vram_percent", 0.0))
            if gpu_info.get("has_vram", False):
                values = [gpu_percent, vram_percent]
                display = (
                    f"Core: {gpu_percent:.1f}% | VRAM: "
                    f"{gpu_info.get('vram_used_gb', 0.0):.2f}/"
                    f"{gpu_info.get('vram_total_gb', 0.0):.1f}GB"
                )
            else:
                values = [gpu_percent]
                display = f"Core: {gpu_percent:.1f}%"
            self._add_if_present(metric_id, values, display)

        if data.get("has_npu", False):
            npu = float(data.get("npu_percent", 0.0))
            self._add_if_present("npu", npu, f"{npu:.1f} %")

    def update_youtube_connections(self, count: int) -> None:
        self._add_if_present(
            "youtube_connections",
            count,
            f"{count} 件",
            max(4.0, count * 1.5),
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        viewport_w = self.viewport().width()
        col_w = self._get_column_min_width()
        columns = max(1, viewport_w // col_w)
        if columns != self._column_count:
            self._reflow(columns)
        for card in self.cards.values():
            card._update_elided_labels()

    def _add_if_present(
        self,
        metric_id: str,
        value: float | list[float],
        display_text: str,
        dynamic_max: float | None = None,
    ) -> None:
        card = self.cards.get(metric_id)
        if card is not None:
            card.add_value(value, display_text, dynamic_max)

    def _sync_cards(self) -> None:
        was_visible = self.has_visible_metrics()
        for metric_id, descriptor in self.descriptors.items():
            mode = self.display_modes.get(metric_id, "hidden")
            if mode == "hidden":
                card = self.cards.pop(metric_id, None)
                if card is not None:
                    self.grid.removeWidget(card)
                    card.deleteLater()
                continue
            card = self.cards.get(metric_id)
            if card is None:
                card = PopupMetricCard(descriptor, mode, self.content)
                card.set_background_opacity(self._background_opacity)
                self.cards[metric_id] = card
            else:
                card.set_mode(mode)
        viewport_w = self.viewport().width()
        col_w = self._get_column_min_width()
        self._reflow(max(1, viewport_w // col_w))
        is_visible = self.has_visible_metrics()
        if was_visible != is_visible:
            self.visibility_changed.emit(is_visible)

    def _reflow(self, columns: int) -> None:
        self._column_count = max(1, columns)
        while self.grid.count():
            self.grid.takeAt(0)
        for c in range(20):
            self.grid.setColumnStretch(c, 0)
        ordered_cards = sorted(self.cards.values(), key=lambda card: card.descriptor.order)
        for index, card in enumerate(ordered_cards):
            self.grid.addWidget(card, index // self._column_count, index % self._column_count)
        for column in range(self._column_count):
            self.grid.setColumnStretch(column, 1)
        for card in self.cards.values():
            card._update_elided_labels()

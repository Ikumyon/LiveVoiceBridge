from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import QGridLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from livevoicebridge.core.telemetry.models import MetricFrame
from livevoicebridge.desktop.monitoring.graph import frame_colors
from livevoicebridge.desktop.monitoring.series import paint_histories
from livevoicebridge.desktop.resources.forms.ui_metric_card import create_form as create_metric_card
from livevoicebridge.desktop.resources.forms.ui_popup_metrics import create_form as create_popup_metrics

POPUP_METRIC_MODES = {"hidden": "非表示", "text": "文字のみ", "both": "文字＋グラフ"}
POPUP_METRIC_PLACEMENTS = {"top": "上", "bottom": "下", "left": "左", "right": "右"}


def fixed_metric_catalog() -> list[dict[str, str]]:
    return [
        {"id": key, "title": title}
        for key, title in (
            ("cpu", "CPU 使用率"),
            ("ram", "メモリ (RAM) 使用量"),
            ("network", "ネットワーク通信速度"),
            ("youtube_connections", "YouTube 同時接続数"),
        )
    ]


class PopupMetricCard(QWidget):
    def __init__(self, frame: MetricFrame, mode: str, parent=None):
        super().__init__(parent)
        self.frame = frame
        self.mode = ""
        self.background_opacity = 0.8
        create_metric_card(root=self)
        self.card_layout = self.findChild(QVBoxLayout, "cardLayout")
        self.title_label = self.findChild(QLabel, "titleLabel")
        self.value_label = self.findChild(QLabel, "valueLabel")
        self.set_mode(mode)

    def set_mode(self, mode: str) -> None:
        if self.mode == mode:
            return
        self.mode = mode
        self.setFixedHeight(28 if mode == "text" else 112)
        self.card_layout.setContentsMargins(8, 0 if mode == "text" else 6, 8, 0 if mode == "text" else 6)
        self.card_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter if mode == "text" else Qt.AlignmentFlag.AlignTop)
        self.update()

    def set_background_opacity(self, value: float) -> None:
        self.background_opacity = value
        self.update()

    def set_frame(self, frame: MetricFrame) -> None:
        self.frame = frame
        if self.isVisible():
            self._update_labels()
            self.update()

    def _update_labels(self) -> None:
        available = max(self.width() - 22, 20)
        for label, text, fraction in (
            (self.title_label, self.frame.title, 0.45),
            (self.value_label, self.frame.text, 0.55),
        ):
            value = QFontMetrics(label.font()).elidedText(text, Qt.TextElideMode.ElideRight, int(available * fraction))
            if label.text() != value:
                label.setText(value)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self._update_labels()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "title_label"):
            self._update_labels()

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(20, 22, 27, round(210 * self.background_opacity)))
        if self.mode == "both":
            paint_histories(
                painter,
                self.rect().adjusted(8, 31, -8, -7),
                self.frame.histories,
                frame_colors(self.frame.kind),
                self.frame.maximum,
            )


class PopupMetricsPanel(QScrollArea):
    visibility_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        create_popup_metrics(root=self)
        self.content = self.findChild(QWidget, "metricsContent")
        self.grid = self.findChild(QGridLayout, "metricsGrid")
        self._frames: tuple[MetricFrame, ...] = ()
        self._catalog: tuple[tuple[str, str], ...] = ()
        self.display_modes: dict[str, str] = {}
        self.cards: dict[str, PopupMetricCard] = {}
        self._columns = 0
        self._background_opacity = 0.8

    def has_visible_metrics(self) -> bool:
        return bool(self.cards)

    def set_display_modes(self, modes: dict[str, str]) -> None:
        modes = {key: value for key, value in modes.items() if value in POPUP_METRIC_MODES}
        if modes != self.display_modes:
            self.display_modes = modes
            self._sync_cards()

    def set_background_opacity(self, value: float) -> None:
        self._background_opacity = value
        for card in self.cards.values():
            card.set_background_opacity(value)

    def update_metrics(self, frames: tuple[MetricFrame, ...]) -> None:
        self._frames = frames
        catalog = tuple((frame.identifier, frame.title) for frame in frames)
        if catalog != self._catalog:
            self._catalog = catalog
            self._sync_cards()
        for frame in frames:
            card = self.cards.get(frame.identifier)
            if card is not None:
                card.set_frame(frame)

    def _sync_cards(self) -> None:
        visible = self.has_visible_metrics()
        frames = {frame.identifier: frame for frame in self._frames}
        wanted = {key for key in frames if self.display_modes.get(key, "hidden") != "hidden"}
        for key in tuple(self.cards):
            if key not in wanted:
                card = self.cards.pop(key)
                self.grid.removeWidget(card)
                card.deleteLater()
        for key in wanted:
            mode = self.display_modes[key]
            if key not in self.cards:
                card = PopupMetricCard(frames[key], mode, self.content)
                card.set_background_opacity(self._background_opacity)
                self.cards[key] = card
            else:
                self.cards[key].set_mode(mode)
        self._reflow()
        if visible != self.has_visible_metrics():
            self.visibility_changed.emit(self.has_visible_metrics())

    def _reflow(self) -> None:
        minimum = 260 if any(card.mode == "both" for card in self.cards.values()) else 180
        self._columns = max(1, self.viewport().width() // minimum)
        while self.grid.count():
            self.grid.takeAt(0)
        order = {frame.identifier: index for index, frame in enumerate(self._frames)}
        for index, (_key, card) in enumerate(sorted(self.cards.items(), key=lambda item: order[item[0]])):
            self.grid.addWidget(card, index // self._columns, index % self._columns)
        for column in range(20):
            self.grid.setColumnStretch(column, int(column < self._columns))

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "cards"):
            self._reflow()

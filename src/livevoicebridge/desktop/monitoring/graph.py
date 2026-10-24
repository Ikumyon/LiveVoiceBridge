from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import QLabel, QWidget

from livevoicebridge.core.telemetry.models import MetricFrame
from livevoicebridge.desktop.forms import load_form
from livevoicebridge.desktop.monitoring.series import paint_histories


def frame_colors(kind: str) -> tuple[QColor, ...]:
    colors = {
        "cpu": ("#00d2ff",),
        "ram": ("#ffd740",),
        "network": ("#00d2ff", "#ff9100"),
        "connections": ("#ff5252",),
        "gpu": ("#00e676", "#ff4081"),
        "npu": ("#b388ff",),
    }
    return tuple(QColor(value) for value in colors[kind])


class PerformanceGraphWidget(QWidget):
    def __init__(self, parent=None, defer_form=False):
        super().__init__(parent)
        if not defer_form:
            self.initialize_form()

    def initialize_form(self):
        self._frame: MetricFrame | None = None
        load_form("performance_graph", root=self)
        self.title_label = self.findChild(QLabel, "titleLabel")
        self.value_label = self.findChild(QLabel, "valueLabel")

    def set_frame(self, frame: MetricFrame) -> None:
        self._frame = frame
        if self.isVisible():
            self._update_labels()
            self.update()

    def _update_labels(self) -> None:
        if self._frame is None:
            return
        for label, text in ((self.title_label, self._frame.title), (self.value_label, self._frame.text)):
            shown = QFontMetrics(label.font()).elidedText(text, Qt.TextElideMode.ElideRight, max(label.width(), 20))
            if shown != label.text():
                label.setText(shown)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self._update_labels()
        self.update()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "_frame"):
            self._update_labels()

    def paintEvent(self, event):  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(25, 27, 32))
        if self._frame is not None:
            paint_histories(
                painter,
                self.rect().adjusted(10, 30, -10, -10),
                self._frame.histories,
                frame_colors(self._frame.kind),
                self._frame.maximum,
            )

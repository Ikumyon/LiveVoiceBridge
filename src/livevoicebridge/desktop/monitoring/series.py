from collections.abc import Sequence

from PySide6.QtCore import QPointF


def graph_segments(
    history: Sequence[float | None],
    left: float,
    bottom: float,
    width: float,
    height: float,
    maximum: float,
) -> list[list[QPointF]]:
    """Keep unavailable samples as gaps rather than inventing zero usage."""
    segments: list[list[QPointF]] = []
    current: list[QPointF] = []
    step = width / max(len(history) - 1, 1)
    for index, value in enumerate(history):
        if value is None:
            if current:
                segments.append(current)
                current = []
            continue
        normalized = max(0.0, min(value / maximum, 1.0))
        current.append(QPointF(left + index * step, bottom - normalized * height))
    if current:
        segments.append(current)
    return segments


def paint_histories(painter, rect, histories, colors, maximum):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen

    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(45, 48, 55), 1, Qt.PenStyle.DashLine))
    for index in range(1, 4):
        y = rect.top() + rect.height() * index / 4
        painter.drawLine(rect.left(), round(y), rect.right(), round(y))
    for index, history in enumerate(histories):
        color = colors[index % len(colors)]
        for points in graph_segments(
            history, rect.left(), rect.bottom(), rect.width(), rect.height(), max(maximum, 0.001)
        ):
            path = QPainterPath()
            path.moveTo(points[0])
            for point in points[1:]:
                path.lineTo(point)
            fill = QPainterPath(path)
            fill.lineTo(points[-1].x(), rect.bottom())
            fill.lineTo(points[0].x(), rect.bottom())
            fill.closeSubpath()
            gradient = QLinearGradient(0, rect.top(), 0, rect.bottom())
            start, end = QColor(color), QColor(color)
            start.setAlpha(40)
            end.setAlpha(2)
            gradient.setColorAt(0, start)
            gradient.setColorAt(1, end)
            painter.fillPath(fill, QBrush(gradient))
            painter.setPen(QPen(color, 2))
            painter.drawPath(path)

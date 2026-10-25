from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QPainter, QPixmap


def clip_to_circle(pixmap: QPixmap, size: int) -> QPixmap:
    """与えられた Pixmap を丸形にクリップ（トリミング）する。"""
    target = QPixmap(size, size)
    target.fill(Qt.GlobalColor.transparent)

    painter = QPainter(target)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

    scaled_pixmap = pixmap.scaled(
        size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation
    )

    x_offset = (scaled_pixmap.width() - size) // 2
    y_offset = (scaled_pixmap.height() - size) // 2
    cropped_pixmap = scaled_pixmap.copy(x_offset, y_offset, size, size)

    brush = QBrush(cropped_pixmap)
    painter.setBrush(brush)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(0, 0, size, size)
    painter.end()

    return target

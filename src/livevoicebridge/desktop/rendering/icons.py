from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer


def render_svg(svg_path: Path, ref_widget, size: int) -> QPixmap:
    """Render a theme-colored SVG at the requested pixel size."""
    try:
        with open(svg_path, encoding="utf-8") as f:
            svg_content = f.read()
        text_color = ref_widget.palette().color(QPalette.ColorRole.Text).name()
        modified_svg = svg_content.replace("currentColor", text_color)
        renderer = QSvgRenderer(QByteArray(modified_svg.encode("utf-8")))
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return pixmap
    except Exception:
        return QIcon(str(svg_path)).pixmap(size, size)


def load_svg_icon(svg_path: Path, ref_widget) -> QIcon:
    return QIcon(render_svg(svg_path, ref_widget, 24))

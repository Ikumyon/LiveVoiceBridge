from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QBrush, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer

COMMENT_LIST_STYLESHEET = """
    QListView {
        border: none;
        background-color: transparent;
    }
    QScrollBar:vertical {
        border: none;
        background: transparent;
        width: 6px;
        margin: 0px;
    }
    QScrollBar::handle:vertical {
        background: rgba(128, 128, 128, 100);
        min-height: 20px;
        border-radius: 3px;
    }
    QScrollBar::handle:vertical:hover {
        background: rgba(128, 128, 128, 180);
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        border: none;
        background: transparent;
        height: 0px;
    }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
        background: transparent;
    }
"""


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


def load_svg_icon(svg_path: Path, ref_widget) -> QIcon:
    """SVG をテーマカラーに合わせて読み込む。失敗時はファイルパスから QIcon を作る。"""
    try:
        with open(svg_path, encoding="utf-8") as f:
            svg_content = f.read()
        text_color = ref_widget.palette().color(QPalette.ColorRole.Text).name()
        modified_svg = svg_content.replace("currentColor", text_color)
        renderer = QSvgRenderer(QByteArray(modified_svg.encode("utf-8")))
        pixmap = QPixmap(24, 24)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return QIcon(pixmap)
    except Exception:
        return QIcon(str(svg_path))

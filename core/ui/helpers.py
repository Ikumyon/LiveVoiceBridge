from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QColor, QBrush, QFont, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QLabel, QHBoxLayout, QListWidget, QListWidgetItem, QVBoxLayout, QWidget


COMMENT_LIST_STYLESHEET = """
    QListWidget {
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


def create_placeholder_avatar(initial: str, palette: QPalette) -> QPixmap:
    """アバター未設定時のイニシャル入り丸形プレースホルダー画像を生成する。"""
    pixmap = QPixmap(36, 36)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    bg_color = palette.color(QPalette.Link)

    painter.setBrush(QBrush(bg_color))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(0, 0, 36, 36)

    painter.setPen(QColor(Qt.white))
    font = QFont()
    font.setBold(True)
    font.setPointSize(14)
    painter.setFont(font)

    painter.drawText(0, 0, 36, 36, Qt.AlignCenter, initial)
    painter.end()
    return pixmap


def clip_to_circle(pixmap: QPixmap, size: int) -> QPixmap:
    """与えられた Pixmap を丸形にクリップ（トリミング）する。"""
    target = QPixmap(size, size)
    target.fill(Qt.transparent)

    painter = QPainter(target)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)

    scaled_pixmap = pixmap.scaled(
        size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
    )

    x_offset = (scaled_pixmap.width() - size) // 2
    y_offset = (scaled_pixmap.height() - size) // 2
    cropped_pixmap = scaled_pixmap.copy(x_offset, y_offset, size, size)

    brush = QBrush(cropped_pixmap)
    painter.setBrush(brush)
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(0, 0, size, size)
    painter.end()

    return target


def load_svg_icon(svg_path: Path, ref_widget) -> QIcon:
    """SVG をテーマカラーに合わせて読み込む。失敗時はファイルパスから QIcon を作る。"""
    try:
        with open(svg_path, "r", encoding="utf-8") as f:
            svg_content = f.read()
        text_color = ref_widget.palette().color(QPalette.Text).name()
        modified_svg = svg_content.replace("currentColor", text_color)
        renderer = QSvgRenderer(QByteArray(modified_svg.encode("utf-8")))
        pixmap = QPixmap(24, 24)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return QIcon(pixmap)
    except Exception:
        return QIcon(str(svg_path))


def create_comment_item(
    comment_list: QListWidget,
    data: dict,
    timestamp: str,
) -> tuple[QListWidgetItem, QLabel]:
    author = data.get("author", "")
    message = data.get("message", "")
    is_skip = data.get("is_skip", False)

    item = QListWidgetItem(comment_list)
    widget = QWidget()

    layout = QHBoxLayout(widget)
    layout.setContentsMargins(8, 6, 8, 6)
    layout.setSpacing(10)

    avatar_label = QLabel()
    avatar_label.setFixedSize(36, 36)
    initial = author[0] if author else "Anonymous"[0]
    placeholder_pixmap = create_placeholder_avatar(initial, comment_list.palette())
    avatar_label.setPixmap(placeholder_pixmap)
    layout.addWidget(avatar_label)

    text_layout = QVBoxLayout()
    text_layout.setSpacing(4)
    text_layout.setContentsMargins(0, 0, 0, 0)

    meta_layout = QHBoxLayout()
    meta_layout.setSpacing(8)
    meta_layout.setContentsMargins(0, 0, 0, 0)

    palette = comment_list.palette()
    time_color = palette.color(QPalette.PlaceholderText).name()

    time_label = QLabel(f"[{timestamp}]")
    time_label.setStyleSheet(f"color: {time_color}; font-size: 11px;")
    meta_layout.addWidget(time_label)

    if is_skip:
        name_color = "#e74c3c"
        name_text = f"[履歴スキップ] {author}"
    else:
        name_color = palette.color(QPalette.Link).name()
        name_text = author

    name_label = QLabel(name_text)
    name_label.setStyleSheet(f"color: {name_color}; font-weight: bold; font-size: 12px;")
    meta_layout.addWidget(name_label)
    meta_layout.addStretch()

    text_layout.addLayout(meta_layout)

    msg_color = palette.color(QPalette.Text).name() if not is_skip else palette.color(QPalette.PlaceholderText).name()
    msg_label = QLabel(message)
    msg_label.setWordWrap(True)
    msg_label.setStyleSheet(f"color: {msg_color}; font-size: 12px;")
    text_layout.addWidget(msg_label)

    layout.addLayout(text_layout)
    widget.setLayout(layout)

    item.setSizeHint(widget.sizeHint())
    comment_list.addItem(item)
    comment_list.setItemWidget(item, widget)
    return item, avatar_label

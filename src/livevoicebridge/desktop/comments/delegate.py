from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from livevoicebridge.desktop.comments.avatars import AvatarCache
from livevoicebridge.desktop.comments.model import CommentRow


class CommentDelegate(QStyledItemDelegate):
    def __init__(self, avatars: AvatarCache, parent=None) -> None:
        super().__init__(parent)
        self.avatars = avatars

    @staticmethod
    def _body_height(option, row: CommentRow, width: int) -> int:
        return option.fontMetrics.boundingRect(
            QRect(0, 0, max(width - 62, 40), 100000), Qt.TextFlag.TextWordWrap, row.message
        ).height()

    def sizeHint(self, option, index):  # noqa: N802
        row = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(row, CommentRow):
            return QSize(100, 48)
        view = self.parent()
        width = option.rect.width() or (view.viewport().width() if view is not None else 300)
        return QSize(width, max(48, self._body_height(option, row, width) + option.fontMetrics.height() + 20))

    def paint(self, painter: QPainter, option, index) -> None:
        row = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(row, CommentRow):
            return
        painter.save()
        painter.setClipRect(option.rect)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        palette = option.palette
        if selected:
            painter.fillRect(option.rect, palette.brush(QPalette.ColorRole.Highlight))
        box = option.rect.adjusted(8, 8, -8, -8)
        avatar_rect = QRect(box.left(), box.top(), 36, 36)
        image = self.avatars.get(row.avatar_key)
        if image is not None:
            painter.drawPixmap(avatar_rect, image)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(palette.brush(QPalette.ColorRole.Link))
            painter.drawEllipse(avatar_rect)
            painter.setPen(QColor("white"))
            painter.drawText(avatar_rect, Qt.AlignmentFlag.AlignCenter, row.author[:1] or "?")
        left = box.left() + 46
        width = max(box.width() - 46, 20)
        height = option.fontMetrics.height()
        title = f"[{row.timestamp}] {'[履歴スキップ] ' if row.skipped else ''}{row.author}"
        painter.setFont(option.font)
        painter.setPen(
            QColor("#e74c3c")
            if row.skipped
            else palette.color(QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Link)
        )
        painter.drawText(
            QRect(left, box.top(), width, height),
            Qt.AlignmentFlag.AlignVCenter,
            option.fontMetrics.elidedText(title, Qt.TextElideMode.ElideRight, width),
        )
        painter.setPen(palette.color(QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text))
        painter.drawText(
            QRect(left, box.top() + height + 4, width, max(box.height() - height - 4, 1)),
            Qt.TextFlag.TextWordWrap,
            row.message,
        )
        painter.restore()

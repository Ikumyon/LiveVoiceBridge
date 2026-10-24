from dataclasses import dataclass

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt


@dataclass(frozen=True, slots=True)
class CommentRow:
    author: str
    message: str
    timestamp: str
    avatar_key: str
    skipped: bool = False


class CommentListModel(QAbstractListModel):
    def __init__(self, limit: int, parent=None) -> None:
        super().__init__(parent)
        self.rows: list[CommentRow] = []
        self.limit = limit

    def rowCount(self, parent=None) -> int:  # noqa: N802
        return 0 if parent is not None and parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        row = self.rows[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return row
        if role == Qt.ItemDataRole.DisplayRole:
            return f"{row.author}: {row.message}"
        return None

    def append_batch(self, rows: list[CommentRow]) -> None:
        rows = rows[-self.limit :]
        self._trim(max(0, len(self.rows) + len(rows) - self.limit))
        if not rows:
            return
        start = len(self.rows)
        self.beginInsertRows(QModelIndex(), start, start + len(rows) - 1)
        self.rows.extend(rows)
        self.endInsertRows()

    def _trim(self, count: int) -> None:
        count = min(count, len(self.rows))
        if count:
            self.beginRemoveRows(QModelIndex(), 0, count - 1)
            del self.rows[:count]
            self.endRemoveRows()

    def set_limit(self, limit: int) -> None:
        self.limit = limit
        self._trim(max(0, len(self.rows) - limit))

    def clear(self) -> None:
        self._trim(len(self.rows))

    def avatars_changed(self, keys: tuple[str, ...]) -> None:
        wanted = set(keys)
        first: int | None = None
        last = 0
        for index, row in enumerate(self.rows):
            if row.avatar_key in wanted:
                first = index if first is None else first
                last = index
        if first is not None:
            self.dataChanged.emit(self.index(first), self.index(last), [Qt.ItemDataRole.DecorationRole])

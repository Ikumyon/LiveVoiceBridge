from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal

_INVALID_INDEX = QModelIndex()


class DictionaryTableModel(QAbstractTableModel):
    """辞書グループのリストを直接編集する表モデル。"""

    changed = Signal()

    _COLUMNS = (
        ("reading", "読み", ""),
        ("word", "単語", ""),
        ("pos", "品詞", "名詞"),
        ("comment", "コメント", ""),
    )

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[dict] = []

    def rowCount(self, parent: QModelIndex = _INVALID_INDEX) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = _INVALID_INDEX) -> int:
        return 0 if parent.isValid() else len(self._COLUMNS)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return None
        key, _, default = self._COLUMNS[index.column()]
        return str(self._rows[index.row()].get(key, default))

    def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False
        key, _, _ = self._COLUMNS[index.column()]
        new_value = str(value)
        if self._rows[index.row()].get(key, "") == new_value:
            return False
        self._rows[index.row()][key] = new_value
        self.dataChanged.emit(index, index, [role])
        self.changed.emit()
        return True

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._COLUMNS[section][1]
        return super().headerData(section, orientation, role)

    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def append_empty_row(self) -> None:
        self.append_rows(({},))

    def append_rows(self, rows: Iterable[dict]) -> None:
        normalized = [self._normalize_row(row) for row in rows]
        if not normalized:
            return
        first = len(self._rows)
        self.beginInsertRows(QModelIndex(), first, first + len(normalized) - 1)
        self._rows.extend(normalized)
        self.endInsertRows()
        self.changed.emit()

    def remove_row(self, row: int) -> bool:
        if row < 0 or row >= len(self._rows):
            return False
        self.beginRemoveRows(QModelIndex(), row, row)
        del self._rows[row]
        self.endRemoveRows()
        self.changed.emit()
        return True

    @classmethod
    def _normalize_row(cls, row: dict) -> dict[str, str]:
        return {key: str(row.get(key, default)) for key, _, default in cls._COLUMNS}

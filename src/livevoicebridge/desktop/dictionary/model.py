from __future__ import annotations

from collections import OrderedDict
from dataclasses import replace

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal

from livevoicebridge.core.dictionary.models import DictionaryEntry

_INVALID_INDEX = QModelIndex()


class DictionaryTableModel(QAbstractTableModel):
    """Virtual table with a bounded row cache; data() never accesses storage."""

    block_requested = Signal(int, int, int)
    entry_changed = Signal(object)
    BLOCK_SIZE = 256
    CACHE_BLOCKS = 8
    _COLUMNS = (
        ("reading", "読み"),
        ("word", "単語"),
        ("part_of_speech", "品詞"),
        ("comment", "コメント"),
    )

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cache: OrderedDict[int, tuple[DictionaryEntry, ...]] = OrderedDict()
        self._count = 0
        self._group = 0
        self._generation = 0
        self._requested = -1
        self._editable = True

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def group(self) -> int:
        return self._group

    def set_group(self, group: int, count: int) -> None:
        self.beginResetModel()
        self._group = group
        self._count = count
        self._generation += 1
        self._requested = -1
        self._cache.clear()
        self.endResetModel()

    def set_editable(self, editable: bool) -> None:
        self._editable = editable

    def has_block(self, block: int) -> bool:
        return block in self._cache

    def retry(self) -> None:
        self._requested = -1

    def rowCount(self, parent: QModelIndex = _INVALID_INDEX) -> int:
        return 0 if parent.isValid() else self._count

    def columnCount(self, parent: QModelIndex = _INVALID_INDEX) -> int:
        return 0 if parent.isValid() else len(self._COLUMNS)

    def entry(self, row: int) -> DictionaryEntry | None:
        if not 0 <= row < self._count:
            return None
        block, offset = divmod(row, self.BLOCK_SIZE)
        rows = self._cache.get(block)
        if rows is None:
            if block != self._requested:
                self._requested = block
                self.block_requested.emit(self._generation, self._group, block)
            return None
        self._cache.move_to_end(block)
        return rows[offset] if offset < len(rows) else None

    def receive(self, generation: int, group: int, block: int, rows: tuple[DictionaryEntry, ...]) -> None:
        if generation != self._generation or group != self._group:
            return
        self._cache[block] = rows
        self._cache.move_to_end(block)
        while len(self._cache) > self.CACHE_BLOCKS:
            self._cache.popitem(last=False)
        self._requested = -1
        first = block * self.BLOCK_SIZE
        last = min(first + len(rows), self._count) - 1
        if first <= last:
            self.dataChanged.emit(self.index(first, 0), self.index(last, len(self._COLUMNS) - 1))

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return None
        entry = self.entry(index.row())
        if entry is None:
            return "読み込み中…" if index.column() == 0 and role == Qt.ItemDataRole.DisplayRole else ""
        return getattr(entry, self._COLUMNS[index.column()][0])

    def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if not self._editable or not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False
        entry = self.entry(index.row())
        if entry is None:
            return False
        key = self._COLUMNS[index.column()][0]
        value = str(value)
        if getattr(entry, key) == value:
            return False
        entry = replace(entry, **{key: value})
        block, offset = divmod(index.row(), self.BLOCK_SIZE)
        rows = list(self._cache[block])
        rows[offset] = entry
        self._cache[block] = tuple(rows)
        self.dataChanged.emit(index, index, [role, Qt.ItemDataRole.DisplayRole])
        self.entry_changed.emit(entry)
        return True

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if self._editable and self.entry(index.row()) is not None:
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._COLUMNS[section][1]
        return super().headerData(section, orientation, role)

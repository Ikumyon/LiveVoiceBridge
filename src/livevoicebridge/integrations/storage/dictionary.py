"""SQLite adapter; complete dictionaries never cross the Python boundary."""

from pathlib import Path

from livevoicebridge import _native as native
from livevoicebridge.core.dictionary.models import DictionaryEntry, DictionaryGroup, DictionaryPage, DictionarySnapshot


class SqliteDictionaryRepository:
    def __init__(self, path: Path):
        self._database = native.DictionaryDatabase(str(path))

    def snapshot(self) -> DictionarySnapshot:
        return self._database.snapshot()

    def begin(self) -> int:
        return self._database.begin()

    def groups(self, draft: int) -> tuple[DictionaryGroup, ...]:
        return tuple(DictionaryGroup(*row) for row in self._database.groups(draft))

    def page(self, draft: int, group: int, offset: int, limit: int) -> DictionaryPage:
        revision, rows = self._database.page(draft, group, offset, limit)
        return DictionaryPage(revision, tuple(DictionaryEntry(*row) for row in rows))

    def add_group(self, draft: int, name: str) -> int:
        return self._database.add_group(draft, name)

    def edit_group(self, draft: int, group: int, name: str | None = None) -> None:
        self._database.edit_group(draft, group, name)

    def append(self, draft: int, group: int) -> int:
        return self._database.append(draft, group)

    def edit(self, draft: int, entry: DictionaryEntry, deleted: bool = False) -> None:
        self._database.edit(
            draft, (entry.id, entry.version, entry.word, entry.reading, entry.part_of_speech, entry.comment), deleted
        )

    def import_file(self, draft: int, group: int, path: Path) -> int:
        return self._database.import_file(draft, group, str(path))

    def commit(self, draft: int) -> None:
        self._database.commit(draft)

    def discard(self, draft: int) -> None:
        self._database.discard(draft)

    def educate(self, word: str, reading: str | None) -> None:
        self._database.educate(word, reading)

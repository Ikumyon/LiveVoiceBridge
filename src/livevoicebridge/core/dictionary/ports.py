from pathlib import Path
from typing import Protocol

from livevoicebridge.core.dictionary.models import DictionaryEntry

DictionaryGroups = dict[str, tuple[DictionaryEntry, ...]]


class DictionaryRepository(Protocol):
    def load(self) -> DictionaryGroups: ...
    def save(self, groups: DictionaryGroups) -> None: ...
    def import_file(self, path: Path) -> tuple[DictionaryEntry, ...]: ...

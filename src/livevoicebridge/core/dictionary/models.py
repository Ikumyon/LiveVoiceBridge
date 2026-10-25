from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class DictionaryEntry:
    id: int
    version: int
    word: str
    reading: str
    part_of_speech: str = "名詞"
    comment: str = ""


@dataclass(frozen=True, slots=True)
class DictionaryConfig:
    active_group: str = "デフォルト"


@dataclass(frozen=True, slots=True)
class DictionaryGroup:
    id: int
    name: str
    count: int
    revision: int


@dataclass(frozen=True, slots=True)
class DictionaryPage:
    revision: int
    entries: tuple[DictionaryEntry, ...]


class DictionarySnapshot(Protocol):
    @property
    def revision(self) -> int: ...
    def replace(self, text: str) -> str: ...

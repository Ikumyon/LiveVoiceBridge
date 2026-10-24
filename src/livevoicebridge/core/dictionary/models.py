from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DictionaryEntry:
    word: str
    reading: str
    part_of_speech: str = "名詞"
    comment: str = ""


@dataclass(frozen=True, slots=True)
class DictionaryConfig:
    active_group: str = "デフォルト"


@dataclass(frozen=True, slots=True)
class DictionarySnapshot:
    revision: int
    entries: tuple[DictionaryEntry, ...]

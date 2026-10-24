"""Atomic dictionary snapshots and explicit file imports."""

import csv
import json
import os
from dataclasses import asdict
from pathlib import Path

from livevoicebridge.core.dictionary.models import DictionaryEntry
from livevoicebridge.core.dictionary.ports import DictionaryGroups


class JsonDictionaryRepository:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> DictionaryGroups:
        if not self.path.exists():
            groups: DictionaryGroups = {"デフォルト": ()}
            self.save(groups)
            return groups
        document = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or not document:
            raise ValueError("辞書データが不正です。")
        return {name: tuple(DictionaryEntry(**entry) for entry in entries) for name, entries in document.items()}

    def save(self, groups: DictionaryGroups) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        try:
            temporary.write_text(
                json.dumps(
                    {name: [asdict(entry) for entry in entries] for name, entries in groups.items()},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def import_file(self, path: Path) -> tuple[DictionaryEntry, ...]:
        return tuple(
            DictionaryEntry(str(row["word"]), str(row["reading"]), str(row["pos"]), str(row["comment"]))
            for row in load_import_word_list(str(path))
        )


def load_import_word_list(file_path: str) -> list[dict]:
    """JSON / CSV / テキスト辞書から単語リストを読み込む。"""
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".json":
        return _load_json_word_list(path)
    if suffix == ".csv":
        return _load_csv_word_list(path)
    if suffix == ".txt":
        return _load_text_word_list(path)
    return []


def _load_json_word_list(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    words = []
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            words.append(
                {
                    "reading": item.get("reading", ""),
                    "word": item.get("word", ""),
                    "pos": item.get("pos", "名詞"),
                    "comment": item.get("comment", ""),
                }
            )
    elif isinstance(data, dict):
        for word, reading in data.items():
            words.append(
                {
                    "reading": str(reading),
                    "word": str(word),
                    "pos": "名詞",
                    "comment": "",
                }
            )
    return words


def _load_csv_word_list(path: Path) -> list[dict]:
    words = []
    with open(path, encoding="utf-8") as f:
        reader = csv.reader(f)
        for row_data in reader:
            if not row_data:
                continue
            words.append(
                {
                    "reading": row_data[0] if len(row_data) > 0 else "",
                    "word": row_data[1] if len(row_data) > 1 else "",
                    "pos": row_data[2] if len(row_data) > 2 else "名詞",
                    "comment": row_data[3] if len(row_data) > 3 else "",
                }
            )
    return words


def _load_text_word_list(path: Path) -> list[dict]:
    words = []
    encoding = _detect_text_dictionary_encoding(path)
    with open(path, encoding=encoding, errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("!") or line.startswith("#"):
                continue

            row_data = line.split("\t")
            if len(row_data) < 2:
                continue

            words.append(
                {
                    "reading": row_data[0].strip(),
                    "word": row_data[1].strip(),
                    "pos": row_data[2].strip() if len(row_data) > 2 else "名詞",
                    "comment": row_data[3].strip() if len(row_data) > 3 else "",
                }
            )
    return words


def _detect_text_dictionary_encoding(path: Path) -> str:
    encoding = "shift_jis"
    for candidate in ["shift_jis", "utf-16", "utf-8"]:
        try:
            with open(path, encoding=candidate) as f:
                f.readline()
            encoding = candidate
            break
        except Exception:
            continue
    return encoding

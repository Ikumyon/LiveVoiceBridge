from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from core import dictionary


def test_default_dictionary_is_created_as_utf8_json(tmp_path: Path) -> None:
    defaults = [{"word": "東京", "reading": "とうきょう", "pos": "名詞", "comment": ""}]

    with (
        patch.object(dictionary, "DICT_DIR", tmp_path / "dict"),
        patch.object(dictionary, "DEFAULT_WORD_LIST", defaults),
    ):
        dictionary.ensure_default_dictionary()
        path = tmp_path / "dict" / "デフォルト.json"

        assert json.loads(path.read_text(encoding="utf-8")) == defaults


def test_add_replaces_duplicate_and_delete_reports_missing(tmp_path: Path) -> None:
    with patch.object(dictionary, "DICT_DIR", tmp_path):
        dictionary.add_word_to_group("配信コメント", "単語", "たんご")
        words = dictionary.add_word_to_group("配信コメント", "単語", "ことば")

        assert words == [{"word": "単語", "reading": "ことば", "pos": "名詞", "comment": ""}]
        assert dictionary.delete_word_from_group("配信コメント", "存在しない") is None
        assert dictionary.delete_word_from_group("配信コメント", "単語") == []


def test_save_removes_groups_not_present_in_memory(tmp_path: Path) -> None:
    stale = tmp_path / "古い.json"
    stale.write_text("[]", encoding="utf-8")

    with patch.object(dictionary, "DICT_DIR", tmp_path):
        dictionary.save_word_dict_data({"新しい": [{"word": "新", "reading": "しん", "pos": "名詞", "comment": ""}]})

        assert not stale.exists()
        assert (tmp_path / "新しい.json").exists()


def test_dictionary_import_formats_keep_current_column_order(tmp_path: Path) -> None:
    json_path = tmp_path / "words.json"
    csv_path = tmp_path / "words.csv"
    text_path = tmp_path / "words.txt"
    json_path.write_text('{"東京": "とうきょう"}', encoding="utf-8")
    csv_path.write_text("とうきょう,東京,名詞,地名\n", encoding="utf-8")
    text_path.write_text("!comment\nとうきょう\t東京\t名詞\t地名\n", encoding="utf-8")

    expected = [{"reading": "とうきょう", "word": "東京", "pos": "名詞", "comment": "地名"}]
    assert dictionary.load_import_word_list(str(json_path)) == [
        {"reading": "とうきょう", "word": "東京", "pos": "名詞", "comment": ""}
    ]
    assert dictionary.load_import_word_list(str(csv_path)) == expected
    assert dictionary.load_import_word_list(str(text_path)) == expected

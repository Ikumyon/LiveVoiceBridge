from __future__ import annotations

from core.comment_processing import (
    DictionaryMatcher,
    build_read_text,
    clean_comment,
    normalize_read_blocks,
    parse_comment_into_segments,
    split_speech_segments,
)


def test_dictionary_matcher_prefers_longest_match_without_replacing_twice() -> None:
    matcher = DictionaryMatcher(
        [
            {"word": "東京", "reading": "とうきょう"},
            {"word": "東京都", "reading": "とうきょうと"},
            {"word": "とうきょうと", "reading": "再置換しない"},
        ]
    )

    assert matcher.replace("東京都へ") == "とうきょうとへ"


def test_comment_commands_preserve_parameter_state_and_actions() -> None:
    segments, play_files = parse_comment_into_segments("前速度(120)後教育(a\\=b=えー)再生(x\\)y.wav)")

    assert segments[0]["text"] == "前"
    assert segments[0]["speed"] is None
    assert segments[1]["text"] == "後"
    assert segments[1]["speed"] == 1.2
    assert segments[2]["action"] == "add_dict"
    assert segments[2]["word"] == "a=b"
    assert segments[2]["reading"] == "えー"
    assert play_files == ["x)y.wav"]


def test_comment_commands_track_panning_and_sound_file() -> None:
    segments, play_files = parse_comment_into_segments("再生(test.wav)左)こんにちは右)世界")

    assert [segment["panning"] for segment in segments] == ["left", "right"]
    assert [segment["text"] for segment in segments] == ["こんにちは", "世界"]
    assert play_files == ["test.wav"]


def test_read_blocks_are_normalized_and_rendered_in_order() -> None:
    blocks = [
        {"type": "author"},
        {"type": "invalid"},
        "not-a-block",
        {"type": "text", "value": "さん。"},
        {"type": "message"},
        {"type": "text", "value": ""},
    ]

    assert normalize_read_blocks(blocks) == [
        {"type": "author"},
        {"type": "text", "value": "さん。"},
        {"type": "message"},
    ]
    assert build_read_text(blocks, "配信者", "こんにちは") == "配信者さん。こんにちは"


def test_invalid_read_blocks_fall_back_to_message_only() -> None:
    assert normalize_read_blocks(None) == [{"type": "message"}]
    assert normalize_read_blocks([]) == [{"type": "message"}]


def test_clean_comment_unescapes_collapses_urls_and_truncates() -> None:
    cleaned = clean_comment("  A&amp;B  https://example.com/path  続き  ", 8)

    assert cleaned == "A&B URL 、以下略"
    assert clean_comment("  A&amp;B\n続き  ", -1) == "A&B 続き"


def test_sentence_split_keeps_action_only_on_last_sentence() -> None:
    result = split_speech_segments([{"text": "一文目です。二文目です！", "action": "del_dict", "word": "単語"}])

    assert [item["text"] for item in result] == ["一文目です。", "二文目です！"]
    assert "action" not in result[0]
    assert result[1]["action"] == "del_dict"
    assert result[1]["word"] == "単語"

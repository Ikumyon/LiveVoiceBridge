from __future__ import annotations

import io
import wave
from pathlib import Path
from unittest.mock import patch

from livevoicebridge.infrastructure import wav_cache


def _wav_bytes() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(8_000)
        wav_file.writeframes(b"\x00\x00" * 80)
    return output.getvalue()


def _request(text: str) -> dict[str, object]:
    return {
        "engine": "voicevox",
        "model_path": "",
        "device": "cpu",
        "text": text,
        "speaker_id": 1,
        "speed": 1.0,
        "pitch": 0.0,
        "intonation": 1.0,
        "volume": 1.0,
        "pause_length": 1.0,
        "pre_phoneme_length": 0.1,
        "post_phoneme_length": 0.1,
        "num_steps": None,
        "lang": "ja",
    }


def test_cache_classification_rules(tmp_path: Path) -> None:
    with patch.object(wav_cache, "EXE_DIR", tmp_path):
        cache = wav_cache.TtsWavCache()

    assert cache.classify_unit("コメントありがとうございます。") == "fixed_phrase"
    assert cache.classify_unit("配信者さん") == "name"
    assert cache.classify_unit("なるほど") == "short_reaction"
    assert cache.classify_unit("これは二十文字を十分に超える通常の文章として分類される文章です。") == "sentence"


def test_fixed_phrase_is_persisted_and_returned_on_next_lookup(tmp_path: Path) -> None:
    with patch.object(wav_cache, "EXE_DIR", tmp_path):
        cache = wav_cache.TtsWavCache()
        request = _request("コメントありがとうございます。")
        unit_type = cache.classify_unit(str(request["text"]))

        cache_key, count, content, level = cache.record_and_lookup(unit_type, request)
        assert (count, content, level) == (1, None, wav_cache.CACHE_NONE)

        stored_path, stored_level = cache.store_generated(cache_key, unit_type, request, _wav_bytes())
        assert stored_path is not None
        assert stored_path.parent == cache.persistent_dir
        assert stored_level == wav_cache.CACHE_PERSISTENT

        second_key, second_count, second_content, second_level = cache.record_and_lookup(unit_type, request)
        assert second_key == cache_key
        assert second_count == 2
        assert second_content == _wav_bytes()
        assert second_level == wav_cache.CACHE_PERSISTENT


def test_short_reaction_needs_second_request_before_temporary_store(tmp_path: Path) -> None:
    with patch.object(wav_cache, "EXE_DIR", tmp_path):
        cache = wav_cache.TtsWavCache()
        request = _request("なるほど")
        unit_type = cache.classify_unit(str(request["text"]))

        cache_key, _, _, _ = cache.record_and_lookup(unit_type, request)
        first_path, first_level = cache.store_generated(cache_key, unit_type, request, _wav_bytes())
        assert (first_path, first_level) == (None, wav_cache.CACHE_NONE)

        cache.record_and_lookup(unit_type, request)
        second_path, second_level = cache.store_generated(cache_key, unit_type, request, _wav_bytes())
        assert second_path is not None
        assert second_path.parent == cache.temp_dir
        assert second_level == wav_cache.CACHE_TEMP


def test_sensitive_or_unstable_text_is_not_safe_for_persistent_cache() -> None:
    assert not wav_cache.TtsWavCache._is_persistent_safe("https://example.com")
    assert not wav_cache.TtsWavCache._is_persistent_safe("123456")
    assert not wav_cache.TtsWavCache._is_persistent_safe("2026年9月2日")
    assert wav_cache.TtsWavCache._is_persistent_safe("通常の読み上げ文章")

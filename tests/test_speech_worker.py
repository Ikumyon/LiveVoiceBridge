from __future__ import annotations

import queue
from unittest.mock import Mock, patch

from livevoicebridge.workers.speech import SpeechWorker


class _FakeCache:
    def classify_unit(self, _text: str) -> str:
        return "sentence"


def _worker(engine_type: str, engine_config: dict) -> SpeechWorker:
    with patch("livevoicebridge.workers.speech.TtsWavCache", return_value=_FakeCache()):
        return SpeechWorker(queue.Queue(), Mock(), engine_type, engine_config, [])


def test_voicevox_parameters_use_segment_values_before_engine_defaults() -> None:
    worker = _worker(
        "voicevox",
        {"speaker_id": 1, "speed": 1.0, "pitch": 0.0, "volume": 1.0, "intonation": 1.2},
    )
    try:
        params = worker._resolve_parameters({"speaker_id": 7, "speed": 1.5, "pitch": 0.1, "volume": 0.8, "echo": 20})
    finally:
        worker.stop()

    assert params["speaker_id"] == 7
    assert params["speed"] == 1.5
    assert params["pitch"] == 0.1
    assert params["volume"] == 0.8
    assert params["intonation"] == 1.2
    assert params["echo"] == 20


def test_bouyomichan_defaults_are_minus_one_and_overrides_are_integers() -> None:
    worker = _worker("bouyomichan", {"speaker_id": 0})
    try:
        defaults = worker._resolve_parameters({})
        overrides = worker._resolve_parameters({"speed": 120.9, "pitch": 90.2, "volume": 80.8})
    finally:
        worker.stop()

    assert (defaults["speed"], defaults["pitch"], defaults["volume"]) == (-1, -1, -1)
    assert (overrides["speed"], overrides["pitch"], overrides["volume"]) == (120, 90, 80)


def test_supertonic_cache_request_contains_output_affecting_settings() -> None:
    worker = _worker(
        "supertonic",
        {"path": "models/supertonic-3", "device": "gpu", "num_steps": 12},
    )
    params = {
        "speaker_id": 2,
        "speed": 1.1,
        "pitch": 0.0,
        "intonation": None,
        "volume": 0.9,
        "pause_length": None,
        "pre_phoneme_length": None,
        "post_phoneme_length": None,
        "echo": None,
        "yamabiko": None,
        "panning": None,
    }
    try:
        request = worker._build_cache_request("テスト", params)
    finally:
        worker.stop()

    assert request == {
        "engine": "supertonic",
        "model_path": "models/supertonic-3",
        "device": "gpu",
        "text": "テスト",
        "speaker_id": 2,
        "speed": 1.1,
        "pitch": 0.0,
        "intonation": None,
        "volume": 0.9,
        "pause_length": None,
        "pre_phoneme_length": None,
        "post_phoneme_length": None,
        "num_steps": 12,
        "lang": "ja",
    }


def test_playback_units_batch_only_compatible_uncached_sentences() -> None:
    base = {
        "content": None,
        "request_count": 1,
        "unit_type": "sentence",
        "params": {"speaker_id": 1, "speed": 1.0},
    }
    segments = [
        {**base, "text": "一。"},
        {**base, "text": "二。"},
        {**base, "text": "三。", "params": {"speaker_id": 2, "speed": 1.0}},
    ]

    worker = _worker("voicevox", {})
    try:
        units = worker._build_playback_units(segments)
    finally:
        worker.stop()

    assert [unit["text"] for unit in units] == ["一。二。", "三。"]

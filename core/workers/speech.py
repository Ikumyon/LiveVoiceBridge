from __future__ import annotations

import os
import queue
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread, Signal

from core.audio.playback import apply_audio_effects, play_wav
from core.comment_processing import (
    replace_emojis,
    replace_words,
    split_speech_segments,
)
from core.tts.wav_cache import TtsWavCache

if TYPE_CHECKING:
    from core.tts.base import BaseTTSEngine


class SpeechWorker(QThread):
    log = Signal(str)
    error = Signal(str)
    dict_add_requested = Signal(str, str)
    dict_del_requested = Signal(str)

    def __init__(
        self,
        speech_queue: queue.Queue,
        tts_engine: BaseTTSEngine,
        engine_type: str,
        engine_config: dict,
        word_list: list[dict] = None
    ):
        super().__init__()
        self.speech_queue = speech_queue
        self.tts_engine = tts_engine
        self.engine_type = engine_type.lower()
        self.engine_config = engine_config if engine_config is not None else {}
        self.word_list = word_list if word_list is not None else []
        self.wav_cache = TtsWavCache()
        self._running = True
        max_workers = 1 if self.engine_type in {"supertonic", "supertonic_lightweight"} else 8
        self.executor = ThreadPoolExecutor(max_workers=max_workers)

    def stop(self) -> None:
        self._running = False
        self.speech_queue.put(None)
        self.executor.shutdown(wait=False)

    def run(self) -> None:
        while self._running:
            item = self.speech_queue.get()
            if item is None:
                break
            try:
                if isinstance(item, list):
                    self.speak_segments(item)
                elif isinstance(item, dict):
                    self.speak_item(item)
                else:
                    self.speak(str(item))
            except Exception as exc:
                self.error.emit(f"音声合成/再生エラー: {exc}")

    def speak_segments(self, segments: list[dict]) -> None:
        sentences = split_speech_segments(segments)
        planned = [self._prepare_sentence(segment) for segment in sentences]
        units = self._build_playback_units(planned)
        futures = [
            self.executor.submit(self._render_playback_unit, unit)
            for unit in units
        ]

        for unit, future in zip(units, futures):
            try:
                wav_path = future.result()
                if wav_path:
                    play_wav(wav_path)
                    os.remove(wav_path)
            except Exception as exc:
                self.error.emit(f"音声再生エラー: {exc}")
            for segment in unit["segments"]:
                self._run_segment_action(segment)

    def _prepare_sentence(self, segment: dict) -> dict:
        prepared = dict(segment)
        text = replace_emojis(
            replace_words(str(segment.get("text", "")), self.word_list)
        )
        prepared["text"] = text
        params = self._resolve_parameters(prepared)
        request = self._build_cache_request(text, params)
        unit_type = self.wav_cache.classify_unit(text)
        cache_key, count, content, level = self.wav_cache.record_and_lookup(
            unit_type,
            request,
        )
        prepared.update(
            params=params,
            request=request,
            unit_type=unit_type,
            cache_key=cache_key,
            request_count=count,
            content=content,
            cache_level=level,
        )
        return prepared

    @staticmethod
    def _settings_key(segment: dict) -> tuple:
        params = segment["params"]
        return tuple(params.get(key) for key in (
            "speaker_id", "speed", "pitch", "intonation", "volume",
            "pause_length", "pre_phoneme_length", "post_phoneme_length",
            "echo", "yamabiko", "panning",
        ))

    def _build_playback_units(self, segments: list[dict]) -> list[dict]:
        units = []
        pending = []
        for segment in segments:
            if segment["content"] is not None:
                if pending:
                    units.append(self._make_miss_unit(pending))
                    pending = []
                units.append({
                    "kind": "cache",
                    "text": segment["text"],
                    "segments": [segment],
                    "content": segment["content"],
                })
            else:
                if (
                    segment["request_count"] >= 2
                    or segment["unit_type"] == "fixed_phrase"
                ):
                    if pending:
                        units.append(self._make_miss_unit(pending))
                        pending = []
                    units.append(self._make_miss_unit([segment]))
                    continue
                if pending and self._settings_key(pending[-1]) != self._settings_key(segment):
                    units.append(self._make_miss_unit(pending))
                    pending = []
                pending.append(segment)
        if pending:
            units.append(self._make_miss_unit(pending))
        return units

    @staticmethod
    def _make_miss_unit(segments: list[dict]) -> dict:
        return {
            "kind": "generate",
            "text": "".join(segment["text"] for segment in segments),
            "segments": list(segments),
        }

    def _render_playback_unit(self, unit: dict) -> str | None:
        first = unit["segments"][0]
        params = first["params"]
        if unit["kind"] == "cache":
            content = unit["content"]
            self.log.emit(f"[SpeechWorker] キャッシュ再生: {unit['text']}")
        else:
            self.log.emit(
                f"[SpeechWorker] TTS生成単位: {unit['text']} "
                f"(文数: {len(unit['segments'])})"
            )
            content = self._generate_content(unit["text"], params)
            if content and len(unit["segments"]) == 1:
                self.wav_cache.store_generated(
                    first["cache_key"],
                    first["unit_type"],
                    first["request"],
                    content,
                )
            elif not content:
                for segment in unit["segments"]:
                    self.wav_cache.record_failure(segment["cache_key"])
        if not content:
            return None
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fp:
            fp.write(content)
            wav_path = fp.name
        return apply_audio_effects(
            wav_path,
            echo_level=params["echo"],
            yamabiko_level=params["yamabiko"],
            panning=params["panning"],
        )

    def _resolve_parameters(self, segment: dict) -> dict:
        cfg = self.engine_config
        bouyomi = self.engine_type == "bouyomichan"
        speed = segment.get("speed")
        pitch = segment.get("pitch")
        volume = segment.get("volume")
        return {
            "speaker_id": segment.get("speaker_id") if segment.get("speaker_id") is not None else int(cfg.get("speaker_id", 0)),
            "speed": int(speed) if bouyomi and speed is not None else (-1 if bouyomi else float(speed) if speed is not None else float(cfg.get("speed", 1.0) or 1.0)),
            "pitch": int(pitch) if bouyomi and pitch is not None else (-1 if bouyomi else float(pitch) if pitch is not None else float(cfg.get("pitch", 0.0) or 0.0)),
            "volume": int(volume) if bouyomi and volume is not None else (-1 if bouyomi else float(volume) if volume is not None else float(cfg.get("volume", 1.0) or 1.0)),
            "intonation": cfg.get("intonation"),
            "pause_length": cfg.get("pause_length"),
            "pre_phoneme_length": cfg.get("pre_phoneme_length"),
            "post_phoneme_length": cfg.get("post_phoneme_length"),
            "echo": segment.get("echo"),
            "yamabiko": segment.get("yamabiko"),
            "panning": segment.get("panning"),
        }

    def _build_cache_request(self, text: str, params: dict) -> dict:
        cfg = self.engine_config
        return {
            "engine": self.engine_type,
            "model_path": cfg.get("path", ""),
            "device": cfg.get("device", "cpu"),
            "text": text,
            "speaker_id": params["speaker_id"],
            "speed": params["speed"],
            "pitch": params["pitch"],
            "intonation": params["intonation"],
            "volume": params["volume"],
            "pause_length": params["pause_length"],
            "pre_phoneme_length": params["pre_phoneme_length"],
            "post_phoneme_length": params["post_phoneme_length"],
            "num_steps": int(cfg.get("num_steps", 8)) if self.engine_type == "supertonic" else None,
            "lang": "ja",
        }

    def _generate_content(self, text: str, params: dict) -> bytes | None:
        if self.engine_type == "supertonic":
            self.tts_engine.num_steps = int(self.engine_config.get("num_steps", 8))
        return self.tts_engine.synthesize_wav(
            text=text,
            speed=params["speed"],
            pitch=params["pitch"],
            intonation=params["intonation"],
            volume=params["volume"],
            pause_length=params["pause_length"],
            pre_phoneme_length=params["pre_phoneme_length"],
            post_phoneme_length=params["post_phoneme_length"],
            speaker_id=params["speaker_id"],
        )

    def _run_segment_action(self, segment: dict) -> None:
        action = segment.get("action")
        if action == "add_dict":
            word = segment.get("word")
            reading = segment.get("reading")
            if word and reading:
                self.dict_add_requested.emit(word, reading)
        elif action == "del_dict":
            word = segment.get("word")
            if word:
                self.dict_del_requested.emit(word)

    def speak_item(self, item: dict) -> None:
        self.speak_segments([item])

    def synthesize_wav(
        self,
        text: str,
        speed: float = None,
        pitch: float = None,
        volume: float = None,
        speaker_id: int = None,
        echo: int = None,
        yamabiko: int = None,
        panning: str = None,
    ) -> str | None:
        try:
            self.log.emit(f"[SpeechWorker] 音声合成リクエスト送信: '{text}'")
            text = replace_words(text, self.word_list)
            text = replace_emojis(text)

            # 各パラメータについて、セグメントからの個別指定がなければ engine_config から、それも無ければ合理的なデフォルト値を取得
            cfg = self.engine_config
            
            # 話者 ID
            target_speaker = speaker_id if speaker_id is not None else int(cfg.get("speaker_id", 0))
            
            # 話速
            target_speed = speed if speed is not None else cfg.get("speed")
            
            # 音高
            target_pitch = pitch if pitch is not None else cfg.get("pitch")
            
            # 音量
            target_volume = volume if volume is not None else cfg.get("volume")
            
            # 抑揚
            target_intonation = cfg.get("intonation")
            
            # 間長 (pause_length)
            target_pause_length = cfg.get("pause_length")
            
            # 開始無音 (pre_phoneme_length)
            target_pre_phoneme_length = cfg.get("pre_phoneme_length")
            
            # 終了無音 (post_phoneme_length)
            target_post_phoneme_length = cfg.get("post_phoneme_length")

            if self.engine_type == "supertonic":
                self.tts_engine.num_steps = int(cfg.get("num_steps", 8))

            # 棒読みちゃん用の値調整
            if self.engine_type == "bouyomichan":
                target_speed = int(target_speed) if target_speed is not None else -1
                target_pitch = int(target_pitch) if target_pitch is not None else -1
                target_volume = int(target_volume) if target_volume is not None else -1
            else:
                # 棒読みちゃん以外のエンジン
                target_speed = float(target_speed) if target_speed is not None else 1.0
                target_pitch = float(target_pitch) if target_pitch is not None else 0.0
                target_volume = float(target_volume) if target_volume is not None else 1.0

            self.log.emit(f"[SpeechWorker] 合成パラメータ -> speaker: {target_speaker}, speed: {target_speed}, pitch: {target_pitch}, volume: {target_volume}")

            unit_type = self.wav_cache.classify_unit(text)
            cache_request = {
                "engine": self.engine_type,
                "model_path": cfg.get("path", ""),
                "device": cfg.get("device", "cpu"),
                "text": text,
                "speaker_id": target_speaker,
                "speed": target_speed,
                "pitch": target_pitch,
                "intonation": target_intonation,
                "volume": target_volume,
                "pause_length": target_pause_length,
                "pre_phoneme_length": target_pre_phoneme_length,
                "post_phoneme_length": target_post_phoneme_length,
                "num_steps": int(cfg.get("num_steps", 8)) if self.engine_type == "supertonic" else None,
                "lang": "ja",
            }
            cache_key, request_count, content, cache_level = (
                self.wav_cache.record_and_lookup(
                    unit_type,
                    cache_request,
                )
            )
            if content is not None:
                self.log.emit(
                    f"[SpeechWorker] WAVキャッシュ使用 "
                    f"(level: {cache_level}, 使用回数: {request_count}, "
                    f"key: {cache_key[:12]})"
                )
            else:
                content = self.tts_engine.synthesize_wav(
                    text=text,
                    speed=target_speed,
                    pitch=target_pitch,
                    intonation=target_intonation,
                    volume=target_volume,
                    pause_length=target_pause_length,
                    pre_phoneme_length=target_pre_phoneme_length,
                    post_phoneme_length=target_post_phoneme_length,
                    speaker_id=target_speaker,
                )
                if content:
                    cache_path, stored_level = self.wav_cache.store_generated(
                        cache_key,
                        unit_type,
                        cache_request,
                        content,
                    )
                    if cache_path is not None:
                        self.log.emit(
                            f"[SpeechWorker] WAVキャッシュ保存 "
                            f"(level: {stored_level}, 使用回数: {request_count}, "
                            f"{cache_path})"
                        )
                    else:
                        self.log.emit(
                            f"[SpeechWorker] WAVキャッシュ未保存 "
                            f"(初回使用、使用回数: {request_count})"
                        )
                else:
                    self.wav_cache.record_failure(cache_key)

            if not content:
                raise RuntimeError("音声合成に失敗しました。")

            self.log.emit(f"[SpeechWorker] 音声合成データ取得成功 (サイズ: {len(content)} bytes)")
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fp:
                fp.write(content)
                wav_path = fp.name

            return apply_audio_effects(wav_path, echo_level=echo, yamabiko_level=yamabiko, panning=panning)
        except Exception as e:
            self.error.emit(f"並列音声合成失敗: {e}")
            self.log.emit(f"[SpeechWorker] 音声合成例外発生: {e}")
            return None

    def speak(
        self,
        text: str,
        speed: float = None,
        pitch: float = None,
        volume: float = None,
        speaker_id: int = None,
        echo: int = None,
        yamabiko: int = None,
        panning: str = None,
    ) -> None:
        wav_path = self.synthesize_wav(
            text,
            speed=speed,
            pitch=pitch,
            volume=volume,
            speaker_id=speaker_id,
            echo=echo,
            yamabiko=yamabiko,
            panning=panning,
        )
        if wav_path:
            try:
                play_wav(wav_path)
            finally:
                try:
                    os.remove(wav_path)
                except OSError:
                    pass

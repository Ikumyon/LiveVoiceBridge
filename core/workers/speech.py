from __future__ import annotations

import os
import queue
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread, Signal

from core.audio.playback import apply_audio_effects, play_wav
from core.comment_processing import replace_emojis, replace_words

if TYPE_CHECKING:
    from core.tts.base import BaseTTSEngine


class SpeechWorker(QThread):
    log = Signal(str)
    error = Signal(str)
    dict_add_requested = Signal(str, str)
    dict_del_requested = Signal(str)

    def __init__(self, speech_queue: queue.Queue, tts_engine: BaseTTSEngine, speaker_id: int, speed: float, word_list: list[dict] = None):
        super().__init__()
        self.speech_queue = speech_queue
        self.tts_engine = tts_engine
        self.speaker_id = speaker_id
        self.speed = speed
        self.word_list = word_list if word_list is not None else []
        self._running = True
        self.executor = ThreadPoolExecutor(max_workers=8)

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
        futures = []
        for seg in segments:
            text = seg.get("text", "")
            if not text:
                futures.append(None)
                continue

            self.log.emit(f"[SpeechWorker] 音声合成キュー追加: '{text}'")
            future = self.executor.submit(
                self.synthesize_wav,
                text,
                speed=seg.get("speed"),
                pitch=seg.get("pitch"),
                volume=seg.get("volume"),
                speaker_id=seg.get("speaker_id"),
                echo=seg.get("echo"),
                yamabiko=seg.get("yamabiko"),
                panning=seg.get("panning"),
            )
            futures.append(future)

        for idx, seg in enumerate(segments):
            future = futures[idx]
            if future is None:
                continue

            try:
                self.log.emit(f"[SpeechWorker] 再生開始を待機中: '{seg.get('text', '')}'")
                wav_path = future.result()
                if wav_path:
                    self.log.emit(f"[SpeechWorker] 再生中: {wav_path}")
                    play_wav(wav_path)
                    self.log.emit("[SpeechWorker] 再生完了")
                    try:
                        os.remove(wav_path)
                    except OSError:
                        pass
                else:
                    self.log.emit("[SpeechWorker] WAVファイル生成失敗のため再生スキップ")
            except Exception as exc:
                self.error.emit(f"音声再生エラー: {exc}")

            action = seg.get("action")
            if action == "add_dict":
                word = seg.get("word")
                reading = seg.get("reading")
                if word and reading:
                    self.dict_add_requested.emit(word, reading)
            elif action == "del_dict":
                word = seg.get("word")
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
            self.log.emit(f"[SpeechWorker] 音声合成リクエスト送信: '{text}' (話者: {speaker_id})")
            text = replace_words(text, self.word_list)
            text = replace_emojis(text)

            target_speaker = speaker_id if speaker_id is not None else self.speaker_id
            target_speed = speed if speed is not None else self.speed
            target_volume = volume if volume is not None else 1.0

            content = self.tts_engine.synthesize_wav(
                text=text,
                speed=target_speed,
                pitch=pitch,
                volume=target_volume,
                speaker_id=target_speaker,
            )
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

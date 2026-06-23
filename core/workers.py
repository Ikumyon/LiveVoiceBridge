from __future__ import annotations

import html
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from concurrent.futures import ThreadPoolExecutor

import requests
import emoji
from PySide6.QtCore import QThread, Signal

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from core.tts_engines import BaseTTSEngine

def replace_words(text: str, word_list: list[dict]) -> str:
    if not word_list:
        return text
    # 文字数の長い順にソートして部分一致の誤置換を防ぐ
    sorted_words = sorted(word_list, key=lambda x: len(x.get("word", "")), reverse=True)
    for item in sorted_words:
        word = item.get("word", "")
        reading = item.get("reading", "")
        if word and word in text:
            text = text.replace(word, reading)
    return text

def replace_emojis(text: str) -> str:
    emojis = emoji.emoji_list(text)
    if not emojis:
        return text

    sorted_emojis = sorted(emojis, key=lambda x: x["match_start"], reverse=True)
    chars = list(text)

    for item in sorted_emojis:
        em = item["emoji"]
        start = item["match_start"]
        end = item["match_end"]

        demo = emoji.demojize(em, language='ja')
        replacement = demo.strip(":")

        chars[start:end] = list(replacement)

    return "".join(chars)

def parse_education_command(text: str, start_pos: int) -> tuple[str, str, int] | tuple[None, None, None]:
    """
    Parses '教育(単語=読み)' starting at start_pos.
    Supports backslash escape sequences like \\) and \\\\ and \\=.
    Returns (word, reading, end_pos) or (None, None, None).
    """
    open_paren = text.find('(', start_pos + 2)
    if open_paren == -1:
        return None, None, None
    
    result_chars = []
    i = open_paren + 1
    escaped = False
    equal_idx = -1
    
    while i < len(text):
        char = text[i]
        if escaped:
            result_chars.append(char)
            escaped = False
        elif char == '\\':
            escaped = True
        elif char == '=' and equal_idx == -1:
            equal_idx = len(result_chars)
        elif char == ')':
            if equal_idx != -1:
                word = "".join(result_chars[:equal_idx]).strip()
                reading = "".join(result_chars[equal_idx:]).strip()
                return word, reading, i + 1
            return None, None, None
        else:
            result_chars.append(char)
        i += 1
        
    return None, None, None

def parse_forget_command(text: str, start_pos: int) -> tuple[str, int] | tuple[None, None]:
    """
    Parses '忘却(単語)' starting at start_pos.
    Supports backslash escape sequences like \\) and \\\\.
    Returns (word, end_pos) or (None, None).
    """
    open_paren = text.find('(', start_pos + 2)
    if open_paren == -1:
        return None, None
        
    result_chars = []
    i = open_paren + 1
    escaped = False
    
    while i < len(text):
        char = text[i]
        if escaped:
            result_chars.append(char)
            escaped = False
        elif char == '\\':
            escaped = True
        elif char == ')':
            word = "".join(result_chars).strip()
            return word, i + 1
        else:
            result_chars.append(char)
        i += 1
        
    return None, None

def parse_comment_into_segments(message: str) -> tuple[list[dict], list[str]]:
    """
    Parses a comment into multiple segments with their own voice parameters.
    Returns (segments, play_files).
    """
    segments = []
    current_states = {
        "speed": None,
        "pitch": None,
        "volume": None,
        "speaker_id": None,
        "echo": None,
        "yamabiko": None,
        "panning": None
    }
    
    i = 0
    text_accum = []
    play_files = []
    
    while i < len(message):
        # 1. 教育
        if message.startswith("教育", i):
            word, reading, end_pos = parse_education_command(message, i)
            if word is not None and reading is not None:
                if text_accum:
                    clean_txt = "".join(text_accum).strip()
                    if clean_txt:
                        segments.append({"text": clean_txt, **current_states})
                    text_accum = []
                read_text = f"{word}が{reading}に辞書登録されました。"
                segments.append({
                    "text": read_text,
                    "action": "add_dict",
                    "word": word,
                    "reading": reading,
                    **current_states
                })
                i = end_pos
                continue
                
        # 2. 忘却
        if message.startswith("忘却", i):
            word, end_pos = parse_forget_command(message, i)
            if word is not None:
                if text_accum:
                    clean_txt = "".join(text_accum).strip()
                    if clean_txt:
                        segments.append({"text": clean_txt, **current_states})
                    text_accum = []
                read_text = f"{word}が辞書から削除されました。"
                segments.append({
                    "text": read_text,
                    "action": "del_dict",
                    "word": word,
                    **current_states
                })
                i = end_pos
                continue
                
        # 3. 再生/音/sound
        play_match = re.match(r'^(?:再生|音|sound)\(', message[i:])
        if play_match:
            open_paren = i + play_match.end() - 1
            result_chars = []
            k = open_paren + 1
            escaped = False
            found_end = False
            while k < len(message):
                char = message[k]
                if escaped:
                    result_chars.append(char)
                    escaped = False
                elif char == '\\':
                    escaped = True
                elif char == ')':
                    found_end = True
                    end_pos = k + 1
                    break
                else:
                    result_chars.append(char)
                k += 1
            if found_end:
                play_files.append("".join(result_chars).strip())
                i = end_pos
                continue

        # 4. 速度
        speed_match = re.match(r'^速度\((\d+)\)', message[i:])
        if speed_match:
            val = float(speed_match.group(1))
            if text_accum:
                clean_txt = "".join(text_accum).strip()
                if clean_txt:
                    segments.append({"text": clean_txt, **current_states})
                text_accum = []
            current_states["speed"] = val / 100.0
            i += speed_match.end()
            continue

        # 5. 音程
        pitch_match = re.match(r'^音程\((\d+)\)', message[i:])
        if pitch_match:
            val = float(pitch_match.group(1))
            if text_accum:
                clean_txt = "".join(text_accum).strip()
                if clean_txt:
                    segments.append({"text": clean_txt, **current_states})
                text_accum = []
            current_states["pitch"] = (val - 100.0) / 100.0 * 0.15
            i += pitch_match.end()
            continue

        # 6. 音量
        volume_match = re.match(r'^音量\((\d+)\)', message[i:])
        if volume_match:
            val = float(volume_match.group(1))
            if text_accum:
                clean_txt = "".join(text_accum).strip()
                if clean_txt:
                    segments.append({"text": clean_txt, **current_states})
                text_accum = []
            current_states["volume"] = val / 100.0
            i += volume_match.end()
            continue

        # 7. 声
        speaker_match = re.match(r'^声\((\d+)\)', message[i:])
        if speaker_match:
            val = int(speaker_match.group(1))
            if text_accum:
                clean_txt = "".join(text_accum).strip()
                if clean_txt:
                    segments.append({"text": clean_txt, **current_states})
                text_accum = []
            current_states["speaker_id"] = val
            i += speaker_match.end()
            continue

        # 8. エコー
        echo_match = re.match(r'^エコー\((\d+)\)', message[i:])
        if echo_match:
            val = int(echo_match.group(1))
            if text_accum:
                clean_txt = "".join(text_accum).strip()
                if clean_txt:
                    segments.append({"text": clean_txt, **current_states})
                text_accum = []
            current_states["echo"] = val
            i += echo_match.end()
            continue

        # 9. やまびこ
        yamabiko_match = re.match(r'^やまびこ\((\d+)\)', message[i:])
        if yamabiko_match:
            val = int(yamabiko_match.group(1))
            if text_accum:
                clean_txt = "".join(text_accum).strip()
                if clean_txt:
                    segments.append({"text": clean_txt, **current_states})
                text_accum = []
            current_states["yamabiko"] = val
            i += yamabiko_match.end()
            continue

        # 10. 定位 (左/右/両)
        pan_match = re.match(r'^(左|右|両)(?:\)|）)', message[i:])
        if pan_match:
            direction = pan_match.group(1)
            if text_accum:
                clean_txt = "".join(text_accum).strip()
                if clean_txt:
                    segments.append({"text": clean_txt, **current_states})
                text_accum = []
            if direction == '左':
                current_states["panning"] = "left"
            elif direction == '右':
                current_states["panning"] = "right"
            elif direction == '両':
                current_states["panning"] = "both"
            i += pan_match.end()
            continue

        # Accumulate char
        text_accum.append(message[i])
        i += 1
        
    if text_accum:
        clean_txt = "".join(text_accum).strip()
        if clean_txt:
            segments.append({"text": clean_txt, **current_states})
            
    return segments, play_files

def apply_audio_effects(wav_path: str, echo_level: int = None, yamabiko_level: int = None, panning: str = None) -> str:
    """
    Applies echo and/or yamabiko effects, and panning (stereo localization) to a WAV file (16-bit PCM).
    Returns the path to the new WAV file.
    """
    if not echo_level and not yamabiko_level and not panning:
        return wav_path

    import wave
    import struct

    try:
        with wave.open(wav_path, 'rb') as w_in:
            params = w_in.getparams()
            nchannels, sampwidth, framerate, nframes, comptype, compname = params
            
            if sampwidth != 2:
                return wav_path
                
            raw_data = w_in.readframes(nframes)
            
        samples = list(struct.unpack(f"<{nframes * nchannels}h", raw_data))
        
        # 1. Apply echo/yamabiko if requested
        if echo_level or yamabiko_level:
            # Determine delay
            delay_seconds = 0.15 if echo_level else 0.35
            delay_frames = int(framerate * delay_seconds)
            delay_samples = delay_frames * nchannels
            
            if yamabiko_level:
                decay = min(max(yamabiko_level / 100.0, 0.1), 0.8)
                repetitions = 3
            else:
                decay = min(max(echo_level / 100.0, 0.1), 0.8)
                repetitions = 1
                
            extra_samples = delay_samples * repetitions
            out_samples = [0] * (len(samples) + extra_samples)
            
            for i in range(len(samples)):
                out_samples[i] += samples[i]
                for r in range(1, repetitions + 1):
                    delay_idx = i + r * delay_samples
                    if delay_idx < len(out_samples):
                        echo_val = int(samples[i] * (decay ** r))
                        out_samples[delay_idx] += echo_val
            samples = out_samples

        # Clip values to 16-bit signed range
        clipped_samples = []
        for s in samples:
            if s > 32767:
                clipped_samples.append(32767)
            elif s < -32768:
                clipped_samples.append(-32768)
            else:
                clipped_samples.append(int(s))
                
        # 2. Apply panning (left/right/both)
        if panning in ("left", "right"):
            panned_samples = []
            if nchannels == 1:
                # Convert mono to stereo
                nchannels = 2
                for s in clipped_samples:
                    if panning == "left":
                        panned_samples.extend([s, 0])
                    else:
                        panned_samples.extend([0, s])
            elif nchannels == 2:
                # Stereo: mask channels
                for i in range(0, len(clipped_samples), 2):
                    left_val = clipped_samples[i]
                    right_val = clipped_samples[i+1]
                    if panning == "left":
                        panned_samples.extend([left_val, 0])
                    else:
                        panned_samples.extend([0, right_val])
            clipped_samples = panned_samples

        out_data = struct.pack(f"<{len(clipped_samples)}h", *clipped_samples)
        
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fp_out:
            new_wav_path = fp_out.name
            
        with wave.open(new_wav_path, 'wb') as w_out:
            w_out.setparams((nchannels, sampwidth, framerate, len(clipped_samples) // nchannels, comptype, compname))
            w_out.writeframes(out_data)
            
        try:
            os.remove(wav_path)
        except OSError:
            pass
            
        return new_wav_path
    except Exception as e:
        print(f"Effect processing error: {e}")
        return wav_path

APP_VERSION = "1.0.0"
GRPC_TARGET = "dns:///youtube.googleapis.com:443"

TEXT_MESSAGE_EVENT = 1
SUPER_CHAT_EVENT = 15
SUPER_STICKER_EVENT = 16
MEMBER_MILESTONE_CHAT_EVENT = 17

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys._MEIPASS)
else:
    APP_DIR = Path(__file__).resolve().parent.parent
CORE_DIR = APP_DIR / "core"
PROTO_FILE = CORE_DIR / "stream_list.proto"
PB2_FILE = CORE_DIR / "stream_list_pb2.py"
PB2_GRPC_FILE = CORE_DIR / "stream_list_pb2_grpc.py"
UI_DIR = APP_DIR / "ui"
MAIN_UI_FILE = UI_DIR / "main_window.ui"
SETTINGS_UI_FILE = UI_DIR / "settings_dialog.ui"
ICON_FILE = APP_DIR / "assets" / "icon.png"
SETTINGS_ICON_FILE = APP_DIR / "assets" / "settings.svg"
PIP_OFF_ICON_FILE = APP_DIR / "assets" / "picture-in-picture-2.svg"
PIP_ON_ICON_FILE = APP_DIR / "assets" / "picture-in-picture.svg"
TV_ICON_FILE = APP_DIR / "assets" / "tv.svg"
PIP_ICON_FILE = PIP_OFF_ICON_FILE

if getattr(sys, "frozen", False):
    EXE_DIR = Path(sys.executable).parent
else:
    EXE_DIR = Path(__file__).resolve().parent.parent

DICT_DIR = EXE_DIR / "dict"
CONFIG_FILE = EXE_DIR / "config.json"

DEFAULT_CONFIG = {
    "youtube_api_key": "",
    "youtube_url": "",
    "speed": 1.0,
    "skip_history": True,
    "read_super_chat": True,
    "max_length": 50,
    "dict_group": "デフォルト",
    "use_ime": False,
    "comment_opacity": 0.8,
    "comment_bg_color": "#1e1e1e",
    "comment_border_color": "#3c3c3c",
    "check_updates": True,
    "tts_engine": "voicevox",
    "voicevox": {
        "url": "http://127.0.0.1:50021",
        "path": "",
        "speaker_id": 1
    },
    "coeiroink": {
        "url": "http://127.0.0.1:50032",
        "path": "",
        "speaker_id": 1
    },
    "bouyomichan": {
        "url": "127.0.0.1:50001",
        "path": "",
        "speaker_id": 0
    },
    "read_blocks": [
        {"type": "message"}
    ]
}

READ_BLOCK_TYPES = {"author", "message", "text"}
DEFAULT_READ_BLOCKS = [{"type": "message"}]


def normalize_read_blocks(blocks: object) -> list[dict]:
    if not isinstance(blocks, list):
        return [block.copy() for block in DEFAULT_READ_BLOCKS]

    normalized = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type not in READ_BLOCK_TYPES:
            continue
        if block_type == "text":
            value = str(block.get("value", ""))
            if value:
                normalized.append({"type": "text", "value": value})
        else:
            normalized.append({"type": block_type})

    return normalized or [block.copy() for block in DEFAULT_READ_BLOCKS]


def build_read_text(read_blocks: list[dict], author: str, message: str) -> str:
    parts = []
    for block in normalize_read_blocks(read_blocks):
        block_type = block["type"]
        if block_type == "author":
            parts.append(author)
        elif block_type == "message":
            parts.append(message)
        elif block_type == "text":
            parts.append(block.get("value", ""))
    return "".join(parts).strip()


DEFAULT_WORD_LIST = [
    {"word": "✨", "reading": "きらきら", "pos": "名詞", "comment": "初期絵文字サンプル"},
    {"word": "😭", "reading": "うるうる", "pos": "名詞", "comment": "初期絵文字サンプル"},
    {"word": "😂", "reading": "うれしなき", "pos": "名詞", "comment": "初期絵文字サンプル"},
    {"word": "👍", "reading": "ぐっど", "pos": "名詞", "comment": "初期絵文字サンプル"},
    {"word": "🔥", "reading": "めらめら", "pos": "名詞", "comment": "初期絵文字サンプル"},
    {"word": "👏", "reading": "ぱちぱち", "pos": "名詞", "comment": "初期絵文字サンプル"},
    {"word": "w", "reading": "わら", "pos": "名詞", "comment": "初期単語サンプル"}
]


# stream_list_pb2/grpc は sys.path に CORE_DIR が含まれている必要がある
if str(CORE_DIR) not in sys.path:
    sys.path.append(str(CORE_DIR))



def ensure_grpc_files() -> None:
    """Generate stream_list_pb2.py files on first run if they are missing."""
    if PB2_FILE.exists() and PB2_GRPC_FILE.exists():
        return

    try:
        from grpc_tools import protoc
    except ImportError as exc:
        raise RuntimeError(
            "gRPC用Pythonファイルがありません。先に `pip install -r requirements.txt` を実行してください。"
        ) from exc

    result = protoc.main(
        [
            "grpc_tools.protoc",
            f"-I{APP_DIR}",
            f"--python_out={CORE_DIR}",
            f"--grpc_python_out={CORE_DIR}",
            str(PROTO_FILE),
        ]
    )
    if result != 0:
        raise RuntimeError("stream_list.proto からgRPC用Pythonファイルを生成できませんでした。")


def extract_video_id(text: str) -> str:
    text = text.strip()
    if "youtube.com" not in text and "youtu.be" not in text:
        return text

    url = urlparse(text)

    if "youtu.be" in url.netloc:
        return url.path.strip("/").split("/")[0]

    if url.path == "/watch":
        return parse_qs(url.query).get("v", [""])[0]

    parts = url.path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] in {"live", "embed", "shorts"}:
        return parts[1]

    return text


def clean_comment(text: str, max_len: int) -> str:
    text = html.unescape(text)
    text = re.sub(r"https?://\S+", "URL", text)
    text = re.sub(r"\s+", " ", text).strip()
    if max_len != -1 and len(text) > max_len:
        text = text[:max_len] + "、以下略"
    return text


def now_text() -> str:
    return time.strftime("%H:%M:%S")


def play_wav(path: str) -> None:
    system = platform.system()

    if system == "Windows":
        import winsound

        winsound.PlaySound(path, winsound.SND_FILENAME)
        return

    if system == "Linux":
        # PipeWire / PulseAudio / ALSA の順に試す
        for command in ("pw-play", "paplay", "aplay"):
            exe = shutil.which(command)
            if not exe:
                continue
            if command == "aplay":
                subprocess.run([exe, "-q", path], check=False)
            else:
                subprocess.run([exe, path], check=False)
            return
        raise RuntimeError("Linuxの音声再生コマンドが見つかりません。alsa-utils等を入れてください。")

    if system == "Darwin":
        exe = shutil.which("afplay")
        if exe:
            subprocess.run([exe, path], check=False)
            return

    raise RuntimeError(f"未対応OSです: {system}")


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
        # 1. すべてのセグメントの音声合成処理を並列で実行
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
                panning=seg.get("panning")
            )
            futures.append(future)
            
        # 2. 合成が完了したものから順番に再生
        for idx, seg in enumerate(segments):
            future = futures[idx]
            if future is None:
                continue
                
            try:
                # このセグメントの合成完了を待つ (ブロック)
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
                
            # 再生完了後に辞書操作アクションを実行
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

    def synthesize_wav(self, text: str, speed: float = None, pitch: float = None, volume: float = None, speaker_id: int = None, echo: int = None, yamabiko: int = None, panning: str = None) -> str | None:
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
                speaker_id=target_speaker
            )
            if not content:
                raise RuntimeError("音声合成に失敗しました。")

            self.log.emit(f"[SpeechWorker] 音声合成データ取得成功 (サイズ: {len(content)} bytes)")
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fp:
                fp.write(content)
                wav_path = fp.name

            # エフェクトおよび定位制御の適用
            wav_path = apply_audio_effects(wav_path, echo_level=echo, yamabiko_level=yamabiko, panning=panning)
            return wav_path
        except Exception as e:
            self.error.emit(f"並列音声合成失敗: {e}")
            self.log.emit(f"[SpeechWorker] 音声合成例外発生: {e}")
            return None

    def speak(self, text: str, speed: float = None, pitch: float = None, volume: float = None, speaker_id: int = None, echo: int = None, yamabiko: int = None, panning: str = None) -> None:
        # テスト用/レガシーフォールバック用の単発同期再生
        wav_path = self.synthesize_wav(text, speed=speed, pitch=pitch, volume=volume, speaker_id=speaker_id, echo=echo, yamabiko=yamabiko, panning=panning)
        if wav_path:
            try:
                play_wav(wav_path)
            finally:
                try:
                    os.remove(wav_path)
                except OSError:
                    pass



class ChatStreamWorker(QThread):
    log = Signal(str)
    status = Signal(str)
    error = Signal(str)
    comment_received = Signal(dict)


    def __init__(
        self,
        speech_queue: queue.Queue,
        youtube_url_or_id: str,
        api_key: str,
        skip_history: bool,
        read_super_chat: bool,
        max_length: int,
        read_blocks: list[dict],
    ):
        super().__init__()
        self.speech_queue = speech_queue
        self.youtube_url_or_id = youtube_url_or_id
        self.api_key = api_key
        self.skip_history = skip_history
        self.read_super_chat = read_super_chat
        self.max_length = max_length
        self.read_blocks = normalize_read_blocks(read_blocks)
        self._running = True
        self._channel = None

    def stop(self) -> None:
        self._running = False
        if self._channel is not None:
            try:
                self._channel.close()
            except Exception:
                pass

    def run(self) -> None:
        try:
            ensure_grpc_files()
            video_id = extract_video_id(self.youtube_url_or_id)
            self.status.emit(f"video_id: {video_id}")
            live_chat_id = self.get_live_chat_id(video_id)
            self.status.emit("liveChatId取得OK。streamListに接続します。")
            self.stream_chat(live_chat_id)
        except Exception as exc:
            if self._running:
                self.error.emit(str(exc))

    def get_live_chat_id(self, video_id: str) -> str:
        response = requests.get(
            f"{YOUTUBE_API_BASE}/videos",
            params={
                "key": self.api_key,
                "part": "liveStreamingDetails",
                "id": video_id,
            },
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        items = data.get("items", [])
        if not items:
            raise RuntimeError("動画が見つかりません。URLまたは動画IDを確認してください。")

        live_chat_id = items[0].get("liveStreamingDetails", {}).get("activeLiveChatId")
        if not live_chat_id:
            raise RuntimeError("activeLiveChatIdを取得できません。ライブ中か、チャットが有効か確認してください。")
        return live_chat_id

    def should_read_type(self, message_type: int) -> bool:
        if message_type == TEXT_MESSAGE_EVENT:
            return True
        if self.read_super_chat and message_type in {
            SUPER_CHAT_EVENT,
            SUPER_STICKER_EVENT,
            MEMBER_MILESTONE_CHAT_EVENT,
        }:
            return True
        return False

    def stream_chat(self, live_chat_id: str) -> None:
        import grpc
        import stream_list_pb2
        import stream_list_pb2_grpc

        metadata = (("x-goog-api-key", self.api_key),)
        next_page_token = None
        first_response = True
        seen_ids: set[str] = set()
        reconnect_wait = 1


        while self._running:
            try:
                credentials = grpc.ssl_channel_credentials()
                options = [
                    ("grpc.keepalive_time_ms", 30000),
                    ("grpc.keepalive_timeout_ms", 10000),
                    ("grpc.http2.max_pings_without_data", 0),
                ]
                self._channel = grpc.secure_channel(GRPC_TARGET, credentials, options=options)
                stub = stream_list_pb2_grpc.V3DataLiveChatMessageServiceStub(self._channel)

                request = stream_list_pb2.LiveChatMessageListRequest(
                    live_chat_id=live_chat_id,
                    part=["snippet", "authorDetails"],
                    max_results=200,
                    page_token=next_page_token or "",
                )

                self.status.emit("接続中。コメント待機中です。")
                for response in stub.StreamList(request, metadata=metadata):
                    if not self._running:
                        return

                    reconnect_wait = 1
                    if response.next_page_token:
                        next_page_token = response.next_page_token

                    if response.offline_at:
                        self.status.emit("配信がオフラインになりました。")
                        return

                    for item in response.items:
                        if not self._running:
                            return

                        if item.id in seen_ids:
                            continue
                        seen_ids.add(item.id)

                        message_type = int(item.snippet.type)
                        if not self.should_read_type(message_type):
                            continue
                        author = item.author_details.display_name or "匿名"
                        profile_image_url = item.author_details.profile_image_url or ""
                        message = clean_comment(item.snippet.display_message, self.max_length)
                        if not message:
                            continue

                        is_skip = first_response and self.skip_history

                        read_text = build_read_text(self.read_blocks, author, message)
                        segments, play_files = parse_comment_into_segments(read_text)
                        clean_msg = "".join([s["text"] for s in segments])

                        self.comment_received.emit({
                            "author": author,
                            "message": message,
                            "profile_image_url": profile_image_url,
                            "is_skip": is_skip,
                            "play_file": play_files[0] if play_files else None,
                            "clean_message": clean_msg
                        })

                        if not is_skip:
                            self.log.emit(f"{author}: {clean_msg}")
                            
                            for idx, seg in enumerate(segments):
                                text_to_speak = seg["text"]
                                if not text_to_speak:
                                    continue
                                    
                                queue_item = {
                                    "text": text_to_speak,
                                    "speed": seg["speed"],
                                    "pitch": seg["pitch"],
                                    "volume": seg["volume"],
                                    "speaker_id": seg["speaker_id"],
                                    "echo": seg["echo"],
                                    "yamabiko": seg["yamabiko"],
                                    "panning": seg["panning"]
                                }
                                if seg.get("action"):
                                    queue_item["action"] = seg["action"]
                                    queue_item["word"] = seg.get("word")
                                    queue_item["reading"] = seg.get("reading")
                                self.speech_queue.put(queue_item)
                    first_response = False

                # StreamList can end normally. Reconnect using the latest token.
                if self._running:
                    self.status.emit("ストリームが閉じました。再接続します。")

            except grpc.RpcError as exc:
                if not self._running:
                    return
                self.status.emit(f"gRPC切断: {exc.code()} / {exc.details()}")
                self.status.emit(f"{reconnect_wait}秒後に再接続します。")
                time.sleep(reconnect_wait)
                reconnect_wait = min(reconnect_wait * 2, 10)
            except Exception as exc:
                if not self._running:
                    return
                self.status.emit(f"エラー: {exc}")
                self.status.emit(f"{reconnect_wait}秒後に再接続します。")
                time.sleep(reconnect_wait)
                reconnect_wait = min(reconnect_wait * 2, 10)
            finally:
                if self._channel is not None:
                    try:
                        self._channel.close()
                    except Exception:
                        pass
                    self._channel = None

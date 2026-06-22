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

import requests
import emoji
from PySide6.QtCore import QThread, Signal

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"

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
PROTO_FILE = APP_DIR / "stream_list.proto"
PB2_FILE = CORE_DIR / "stream_list_pb2.py"
PB2_GRPC_FILE = CORE_DIR / "stream_list_pb2_grpc.py"
UI_DIR = APP_DIR / "ui"
MAIN_UI_FILE = UI_DIR / "main_window.ui"
SETTINGS_UI_FILE = UI_DIR / "settings_dialog.ui"
ICON_FILE = APP_DIR / "assets" / "icon.png"
SETTINGS_ICON_FILE = APP_DIR / "assets" / "settings.svg"
PIP_ICON_FILE = APP_DIR / "assets" / "picture-in-picture-2.svg"

if getattr(sys, "frozen", False):
    EXE_DIR = Path(sys.executable).parent
else:
    EXE_DIR = Path(__file__).resolve().parent.parent

DICT_DIR = EXE_DIR / "dict"
CONFIG_FILE = EXE_DIR / "config.json"

DEFAULT_CONFIG = {
    "youtube_api_key": "",
    "youtube_url": "",
    "voicevox_url": "http://127.0.0.1:50021",
    "speaker_id": 1,
    "speed": 1.0,
    "skip_history": True,
    "read_author": False,
    "read_super_chat": True,
    "max_length": 50,
    "dict_group": "デフォルト",
    "use_ime": False
}

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
    if len(text) > max_len:
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

    def __init__(self, speech_queue: queue.Queue, voicevox_url: str, speaker_id: int, speed: float, word_list: list[dict] = None):
        super().__init__()
        self.speech_queue = speech_queue
        self.voicevox_url = voicevox_url.rstrip("/")
        self.speaker_id = speaker_id
        self.speed = speed
        self.word_list = word_list if word_list is not None else []
        self._running = True

    def stop(self) -> None:
        self._running = False
        self.speech_queue.put(None)

    def run(self) -> None:
        while self._running:
            item = self.speech_queue.get()
            if item is None:
                break
            try:
                self.speak(str(item))
            except Exception as exc:
                self.error.emit(f"音声合成/再生エラー: {exc}")

    def speak(self, text: str) -> None:
        text = replace_words(text, self.word_list)
        text = replace_emojis(text)
        query_response = requests.post(
            f"{self.voicevox_url}/audio_query",
            params={"text": text, "speaker": self.speaker_id},
            timeout=10,
        )
        query_response.raise_for_status()
        audio_query = query_response.json()
        audio_query["speedScale"] = self.speed
        audio_query["intonationScale"] = 1.05
        audio_query["volumeScale"] = 1.0

        synthesis_response = requests.post(
            f"{self.voicevox_url}/synthesis",
            params={"speaker": self.speaker_id},
            json=audio_query,
            timeout=30,
        )
        synthesis_response.raise_for_status()

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fp:
            fp.write(synthesis_response.content)
            wav_path = fp.name

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
        read_author: bool,
        read_super_chat: bool,
        max_length: int,
    ):
        super().__init__()
        self.speech_queue = speech_queue
        self.youtube_url_or_id = youtube_url_or_id
        self.api_key = api_key
        self.skip_history = skip_history
        self.read_author = read_author
        self.read_super_chat = read_super_chat
        self.max_length = max_length
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

                        self.comment_received.emit({
                            "author": author,
                            "message": message,
                            "profile_image_url": profile_image_url,
                            "is_skip": is_skip
                        })

                        if not is_skip:
                            self.log.emit(f"{author}: {message}")
                            if self.read_author:
                                read_text = f"{author}さん。{message}"
                            else:
                                read_text = message
                            self.speech_queue.put(read_text)

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

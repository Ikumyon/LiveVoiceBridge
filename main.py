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
from PySide6.QtCore import QObject, QSettings, QThread, QFile, Signal
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QFileDialog,
)

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
GRPC_TARGET = "dns:///youtube.googleapis.com:443"

TEXT_MESSAGE_EVENT = 1
SUPER_CHAT_EVENT = 15
SUPER_STICKER_EVENT = 16
MEMBER_MILESTONE_CHAT_EVENT = 17

APP_DIR = Path(__file__).resolve().parent
PROTO_FILE = APP_DIR / "stream_list.proto"
PB2_FILE = APP_DIR / "stream_list_pb2.py"
PB2_GRPC_FILE = APP_DIR / "stream_list_pb2_grpc.py"
UI_FILE = APP_DIR / "live_voice_bridge.ui"


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
            f"--python_out={APP_DIR}",
            f"--grpc_python_out={APP_DIR}",
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

    def __init__(self, speech_queue: queue.Queue, voicevox_url: str, speaker_id: int, speed: float):
        super().__init__()
        self.speech_queue = speech_queue
        self.voicevox_url = voicevox_url.rstrip("/")
        self.speaker_id = speaker_id
        self.speed = speed
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
                        message = clean_comment(item.snippet.display_message, self.max_length)
                        if not message:
                            continue

                        if first_response and self.skip_history:
                            self.log.emit(f"[履歴スキップ] {author}: {message}")
                            continue

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


class LiveVoiceBridgeApp(QObject):
    def __init__(self):
        super().__init__()
        loader = QUiLoader()
        ui_file = QFile(str(UI_FILE))
        if not ui_file.open(QFile.ReadOnly):
            raise RuntimeError(f"UIファイルを開けません: {UI_FILE}")
        self.window = loader.load(ui_file)
        ui_file.close()
        if self.window is None:
            raise RuntimeError("UIファイルの読み込みに失敗しました。")

        self.settings = QSettings("LiveVoiceBridge", "LiveVoiceBridge")
        self.speech_queue: queue.Queue = queue.Queue()
        self.chat_worker: ChatStreamWorker | None = None
        self.speech_worker: SpeechWorker | None = None

        self.url_line: QLineEdit = self.window.findChild(QLineEdit, "urlLineEdit")
        self.api_key_line: QLineEdit = self.window.findChild(QLineEdit, "apiKeyLineEdit")
        self.voicevox_url_line: QLineEdit = self.window.findChild(QLineEdit, "voicevoxUrlLineEdit")
        self.speaker_spin: QSpinBox = self.window.findChild(QSpinBox, "speakerIdSpinBox")
        self.max_length_spin: QSpinBox = self.window.findChild(QSpinBox, "maxLengthSpinBox")
        self.speed_spin: QDoubleSpinBox = self.window.findChild(QDoubleSpinBox, "speedDoubleSpinBox")
        self.skip_history_check: QCheckBox = self.window.findChild(QCheckBox, "skipHistoryCheckBox")
        self.read_author_check: QCheckBox = self.window.findChild(QCheckBox, "readAuthorCheckBox")
        self.read_super_chat_check: QCheckBox = self.window.findChild(QCheckBox, "readSuperChatCheckBox")
        self.start_button: QPushButton = self.window.findChild(QPushButton, "startButton")
        self.stop_button: QPushButton = self.window.findChild(QPushButton, "stopButton")
        self.clear_log_button: QPushButton = self.window.findChild(QPushButton, "clearLogButton")
        self.test_voicevox_button: QPushButton = self.window.findChild(QPushButton, "testVoicevoxButton")
        self.log_text: QTextEdit = self.window.findChild(QTextEdit, "logTextEdit")
        self.comment_text: QTextEdit = self.window.findChild(QTextEdit, "commentTextEdit")
        self.status_label: QLabel = self.window.findChild(QLabel, "statusLabel")
        self.voicevox_path_line: QLineEdit = self.window.findChild(QLineEdit, "voicevoxPathLineEdit")
        self.voicevox_path_browse_button: QPushButton = self.window.findChild(QPushButton, "voicevoxPathBrowseButton")
        self.voicevox_process: subprocess.Popen | None = None

        self.load_settings()
        self.connect_signals()
        self.window.destroyed.connect(self.stop_all)

    def load_settings(self) -> None:
        env_key = os.environ.get("YOUTUBE_API_KEY", "")
        self.api_key_line.setText(self.settings.value("api_key", env_key))
        self.voicevox_url_line.setText(self.settings.value("voicevox_url", "http://127.0.0.1:50021"))
        self.voicevox_path_line.setText(self.settings.value("voicevox_path", ""))
        self.speaker_spin.setValue(int(self.settings.value("speaker_id", 3)))
        self.max_length_spin.setValue(int(self.settings.value("max_length", 80)))
        self.speed_spin.setValue(float(self.settings.value("speed", 1.2)))
        self.skip_history_check.setChecked(self.settings.value("skip_history", True, type=bool))
        self.read_author_check.setChecked(self.settings.value("read_author", False, type=bool))
        self.read_super_chat_check.setChecked(self.settings.value("read_super_chat", True, type=bool))

    def save_settings(self) -> None:
        self.settings.setValue("api_key", self.api_key_line.text().strip())
        self.settings.setValue("voicevox_url", self.voicevox_url_line.text().strip())
        self.settings.setValue("voicevox_path", self.voicevox_path_line.text().strip())
        self.settings.setValue("speaker_id", self.speaker_spin.value())
        self.settings.setValue("max_length", self.max_length_spin.value())
        self.settings.setValue("speed", self.speed_spin.value())
        self.settings.setValue("skip_history", self.skip_history_check.isChecked())
        self.settings.setValue("read_author", self.read_author_check.isChecked())
        self.settings.setValue("read_super_chat", self.read_super_chat_check.isChecked())

    def connect_signals(self) -> None:
        self.start_button.clicked.connect(self.start)
        self.stop_button.clicked.connect(self.stop_all)
        self.clear_log_button.clicked.connect(self.clear_all_logs)
        self.test_voicevox_button.clicked.connect(self.test_voicevox)
        self.voicevox_path_browse_button.clicked.connect(self.browse_voicevox_path)

        # リアルタイム設定反映
        self.skip_history_check.stateChanged.connect(self.update_live_settings)
        self.read_author_check.stateChanged.connect(self.update_live_settings)
        self.read_super_chat_check.stateChanged.connect(self.update_live_settings)
        self.speaker_spin.valueChanged.connect(self.update_live_settings)
        self.speed_spin.valueChanged.connect(self.update_live_settings)
        self.max_length_spin.valueChanged.connect(self.update_live_settings)

    def update_live_settings(self) -> None:
        if getattr(self, "chat_worker", None) is not None and self.chat_worker.isRunning():
            self.chat_worker.skip_history = self.skip_history_check.isChecked()
            self.chat_worker.read_author = self.read_author_check.isChecked()
            self.chat_worker.read_super_chat = self.read_super_chat_check.isChecked()
            self.chat_worker.max_length = self.max_length_spin.value()

        if getattr(self, "speech_worker", None) is not None and self.speech_worker.isRunning():
            self.speech_worker.speaker_id = self.speaker_spin.value()
            self.speech_worker.speed = self.speed_spin.value()

    def browse_voicevox_path(self) -> None:
        system = platform.system()
        if system == "Windows":
            filter_str = "Executable Files (*.exe);;All Files (*)"
        else:
            filter_str = "All Files (*)"

        file_path, _ = QFileDialog.getOpenFileName(
            self.window,
            "VOICEVOX 実行ファイルを選択",
            self.voicevox_path_line.text().strip(),
            filter_str
        )
        if file_path:
            self.voicevox_path_line.setText(file_path)

    def append_comment(self, text: str) -> None:
        self.comment_text.append(f"{now_text()}  {text}")

    def clear_all_logs(self) -> None:
        self.log_text.clear()
        self.comment_text.clear()

    def append_log(self, text: str) -> None:
        self.log_text.append(f"{now_text()}  {text}")

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)
        self.append_log(f"[状態] {text}")

    def set_running_ui(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.url_line.setEnabled(not running)
        self.api_key_line.setEnabled(not running)
        self.voicevox_url_line.setEnabled(not running)
        self.speaker_spin.setEnabled(not running)
        self.max_length_spin.setEnabled(not running)
        self.speed_spin.setEnabled(not running)

    def show_error(self, text: str) -> None:
        self.append_log(f"[エラー] {text}")
        QMessageBox.warning(self.window, "LiveVoiceBridge エラー", text)

    def ensure_voicevox_running(self) -> bool:
        url = self.voicevox_url_line.text().strip().rstrip("/")
        if not url:
            return False

        # 既に起動しているか確認
        try:
            response = requests.get(f"{url}/speakers", timeout=1)
            if response.status_code == 200:
                return True
        except requests.RequestException:
            pass

        # 起動していない場合、パスが指定されていれば起動を試みる
        path = self.voicevox_path_line.text().strip()
        if not path or not os.path.exists(path):
            return False

        self.set_status("VOICEVOXを起動中...")
        QApplication.processEvents()

        try:
            creationflags = 0
            if platform.system() == "Windows":
                creationflags = 0x08000000  # CREATE_NO_WINDOW
            
            self.voicevox_process = subprocess.Popen(
                [path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags
            )
        except Exception as exc:
            self.show_error(f"VOICEVOXの起動に失敗しました: {exc}")
            return False

        # 起動を待つ（最大20秒）
        for _ in range(20):
            if self.voicevox_process.poll() is not None:
                self.show_error("VOICEVOXプロセスが起動直後に終了しました。")
                self.voicevox_process = None
                return False

            try:
                response = requests.get(f"{url}/speakers", timeout=1)
                if response.status_code == 200:
                    self.set_status("VOICEVOXの起動を確認しました。")
                    return True
            except requests.RequestException:
                pass
            time.sleep(1)
            QApplication.processEvents()

        self.show_error("VOICEVOXの起動を確認できませんでした。手動で起動してください。")
        return False

    def test_voicevox(self) -> None:
        url = self.voicevox_url_line.text().strip().rstrip("/")
        if not url:
            QMessageBox.warning(self.window, "入力不足", "VOICEVOX URLを入力してください。")
            return

        self.ensure_voicevox_running()

        try:
            response = requests.get(f"{url}/speakers", timeout=5)
            response.raise_for_status()
            speakers = response.json()
            lines: list[str] = []
            for speaker in speakers[:8]:
                name = speaker.get("name", "?")
                styles = speaker.get("styles", [])
                style_text = ", ".join(f"{s.get('name')}={s.get('id')}" for s in styles[:6])
                lines.append(f"{name}: {style_text}")
            self.append_log("VOICEVOX接続OK")
            self.append_log(" / ".join(lines) if lines else "speaker情報なし")
        except Exception as exc:
            self.show_error(f"VOICEVOXに接続できません: {exc}")

    def start(self) -> None:
        url_or_id = self.url_line.text().strip()
        api_key = self.api_key_line.text().strip()
        voicevox_url = self.voicevox_url_line.text().strip()

        if not url_or_id:
            QMessageBox.warning(self.window, "入力不足", "YouTube URLまたはVideo IDを入力してください。")
            return
        if not api_key:
            QMessageBox.warning(self.window, "入力不足", "YouTube Data API Keyを入力してください。")
            return
        if not voicevox_url:
            QMessageBox.warning(self.window, "入力不足", "VOICEVOX URLを入力してください。")
            return

        self.save_settings()
        self.ensure_voicevox_running()
        self.speech_queue = queue.Queue()
        self.speech_worker = SpeechWorker(
            speech_queue=self.speech_queue,
            voicevox_url=voicevox_url,
            speaker_id=self.speaker_spin.value(),
            speed=self.speed_spin.value(),
        )
        self.speech_worker.error.connect(self.show_error)
        self.speech_worker.start()

        self.chat_worker = ChatStreamWorker(
            speech_queue=self.speech_queue,
            youtube_url_or_id=url_or_id,
            api_key=api_key,
            skip_history=self.skip_history_check.isChecked(),
            read_author=self.read_author_check.isChecked(),
            read_super_chat=self.read_super_chat_check.isChecked(),
            max_length=self.max_length_spin.value(),
        )
        self.chat_worker.log.connect(self.append_comment)
        self.chat_worker.status.connect(self.set_status)
        self.chat_worker.error.connect(self.show_error)
        self.chat_worker.finished.connect(self.on_chat_finished)
        self.chat_worker.start()

        self.append_log("開始しました。")
        self.set_running_ui(True)

    def stop_all(self) -> None:
        if self.chat_worker is not None:
            self.chat_worker.stop()
            self.chat_worker.wait(1000)
            self.chat_worker = None
        if self.speech_worker is not None:
            self.speech_worker.stop()
            self.speech_worker.wait(1000)
            self.speech_worker = None

        # 自動起動したVOICEVOXプロセスがあれば終了
        if getattr(self, "voicevox_process", None) is not None:
            if self.voicevox_process.poll() is None:
                self.set_status("VOICEVOXを終了中...")
                QApplication.processEvents()
                self.voicevox_process.terminate()
                try:
                    self.voicevox_process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.voicevox_process.kill()
            self.voicevox_process = None

        self.status_label.setText("停止中")
        self.set_running_ui(False)

    def on_chat_finished(self) -> None:
        self.append_log("コメント受信を停止しました。")
        if self.speech_worker is not None:
            self.speech_worker.stop()
        self.chat_worker = None
        self.speech_worker = None
        self.set_running_ui(False)
        self.status_label.setText("停止中")

    def show(self) -> None:
        self.window.show()


def main() -> None:
    app = QApplication(sys.argv)
    controller = LiveVoiceBridgeApp()
    controller.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

from __future__ import annotations

import os
import platform
import queue
import subprocess
import sys
import time

import requests
from PySide6.QtCore import QFile, QObject, QSettings, Signal
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
)
from PySide6.QtGui import QAction

# core.workers から必要なものをインポート
from core.workers import (
    MAIN_UI_FILE,
    SETTINGS_UI_FILE,
    ICON_FILE,
    SpeechWorker,
    ChatStreamWorker,
    now_text,
)


class SettingsDialog(QDialog):
    # 設定が変更されたことをメインウィンドウへ通知するシグナル
    settings_changed = Signal()

    def __init__(self, parent_app: LiveVoiceBridgeApp):
        super().__init__()
        self.main_app = parent_app
        self.settings = QSettings("LiveVoiceBridge", "LiveVoiceBridge")

        # UIファイルの読み込み
        loader = QUiLoader()
        ui_file = QFile(str(SETTINGS_UI_FILE))
        if not ui_file.open(QFile.ReadOnly):
            raise RuntimeError(f"UIファイルを開けません: {SETTINGS_UI_FILE}")
        self.dialog_window = loader.load(ui_file, self)
        ui_file.close()

        # ウィジェットのバインド
        self.url_line: QLineEdit = self.dialog_window.findChild(QLineEdit, "urlLineEdit")
        self.api_key_line: QLineEdit = self.dialog_window.findChild(QLineEdit, "apiKeyLineEdit")
        self.voicevox_url_line: QLineEdit = self.dialog_window.findChild(QLineEdit, "voicevoxUrlLineEdit")
        self.speaker_spin: QSpinBox = self.dialog_window.findChild(QSpinBox, "speakerIdSpinBox")
        self.max_length_spin: QSpinBox = self.dialog_window.findChild(QSpinBox, "maxLengthSpinBox")
        self.speed_spin: QDoubleSpinBox = self.dialog_window.findChild(QDoubleSpinBox, "speedDoubleSpinBox")
        self.skip_history_check: QCheckBox = self.dialog_window.findChild(QCheckBox, "skipHistoryCheckBox")
        self.read_author_check: QCheckBox = self.dialog_window.findChild(QCheckBox, "readAuthorCheckBox")
        self.read_super_chat_check: QCheckBox = self.dialog_window.findChild(QCheckBox, "readSuperChatCheckBox")
        self.voicevox_path_line: QLineEdit = self.dialog_window.findChild(QLineEdit, "voicevoxPathLineEdit")
        self.voicevox_path_browse_button: QPushButton = self.dialog_window.findChild(QPushButton, "voicevoxPathBrowseButton")
        self.test_voicevox_button: QPushButton = self.dialog_window.findChild(QPushButton, "testVoicevoxButton")
        self.button_box: QDialogButtonBox = self.dialog_window.findChild(QDialogButtonBox, "buttonBox")

        self.load_settings()
        self.connect_signals()

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

        # URLはメイン画面に入力欄がないため、ダイアログ側で保持
        self.url_line.setText(self.settings.value("youtube_url", ""))

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
        self.settings.setValue("youtube_url", self.url_line.text().strip())

    def connect_signals(self) -> None:
        self.voicevox_path_browse_button.clicked.connect(self.browse_voicevox_path)
        self.test_voicevox_button.clicked.connect(self.test_voicevox)

        # OK / キャンセルボタン
        self.button_box.accepted.connect(self.accept_settings)
        self.button_box.rejected.connect(self.reject)

        # リアルタイム反映用の変更検知
        self.skip_history_check.stateChanged.connect(self.settings_changed.emit)
        self.read_author_check.stateChanged.connect(self.settings_changed.emit)
        self.read_super_chat_check.stateChanged.connect(self.settings_changed.emit)
        self.speaker_spin.valueChanged.connect(self.settings_changed.emit)
        self.speed_spin.valueChanged.connect(self.settings_changed.emit)
        self.max_length_spin.valueChanged.connect(self.settings_changed.emit)

    def accept_settings(self) -> None:
        self.save_settings()
        self.accept()

    def browse_voicevox_path(self) -> None:
        system = platform.system()
        filter_str = "Executable Files (*.exe);;All Files (*)" if system == "Windows" else "All Files (*)"
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "VOICEVOX 実行ファイルを選択",
            self.voicevox_path_line.text().strip(),
            filter_str
        )
        if file_path:
            self.voicevox_path_line.setText(file_path)

    def test_voicevox(self) -> None:
        url = self.voicevox_url_line.text().strip().rstrip("/")
        if not url:
            QMessageBox.warning(self, "入力不足", "VOICEVOX URLを入力してください。")
            return

        # VOICEVOX起動確認
        self.main_app.ensure_voicevox_running_with_path(
            url, self.voicevox_path_line.text().strip()
        )

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
            self.main_app.append_log("VOICEVOX接続OK")
            self.main_app.append_log(" / ".join(lines) if lines else "speaker情報なし")
        except Exception as exc:
            self.main_app.show_error(f"VOICEVOXに接続できません: {exc}")


class LiveVoiceBridgeApp(QObject):
    def __init__(self):
        super().__init__()
        loader = QUiLoader()
        ui_file = QFile(str(MAIN_UI_FILE))
        if not ui_file.open(QFile.ReadOnly):
            raise RuntimeError(f"UIファイルを開けません: {MAIN_UI_FILE}")
        self.window = loader.load(ui_file)
        ui_file.close()
        if self.window is None:
            raise RuntimeError("UIファイルの読み込みに失敗しました。")

        self.settings = QSettings("LiveVoiceBridge", "LiveVoiceBridge")
        self.speech_queue: queue.Queue = queue.Queue()
        self.chat_worker: ChatStreamWorker | None = None
        self.speech_worker: SpeechWorker | None = None
        self.voicevox_process: subprocess.Popen | None = None

        # ウィジェットのバインド
        self.start_button: QPushButton = self.window.findChild(QPushButton, "startButton")
        self.stop_button: QPushButton = self.window.findChild(QPushButton, "stopButton")
        self.clear_log_button: QPushButton = self.window.findChild(QPushButton, "clearLogButton")
        self.comment_text: QTextEdit = self.window.findChild(QTextEdit, "commentTextEdit")
        self.log_text: QTextEdit = self.window.findChild(QTextEdit, "logTextEdit")
        self.status_label: QLabel = self.window.findChild(QLabel, "statusLabel")

        # メニューバーのアクション取得
        self.action_settings: QAction = self.window.findChild(QAction, "action_settings")

        self.connect_signals()
        self.window.destroyed.connect(self.stop_all)

    def connect_signals(self) -> None:
        self.start_button.clicked.connect(self.start)
        self.stop_button.clicked.connect(self.stop_all)
        self.clear_log_button.clicked.connect(self.clear_all_logs)
        self.action_settings.triggered.connect(self.open_settings_dialog)

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

    def show_error(self, text: str) -> None:
        self.append_log(f"[エラー] {text}")
        QMessageBox.warning(self.window, "LiveVoiceBridge エラー", text)

    def open_settings_dialog(self) -> None:
        # ロールバック用に現在の設定をバックアップ
        backup_settings = {
            "api_key": self.settings.value("api_key", ""),
            "voicevox_url": self.settings.value("voicevox_url", "http://127.0.0.1:50021"),
            "voicevox_path": self.settings.value("voicevox_path", ""),
            "speaker_id": int(self.settings.value("speaker_id", 3)),
            "max_length": int(self.settings.value("max_length", 80)),
            "speed": float(self.settings.value("speed", 1.2)),
            "skip_history": self.settings.value("skip_history", True, type=bool),
            "read_author": self.settings.value("read_author", False, type=bool),
            "read_super_chat": self.settings.value("read_super_chat", True, type=bool),
            "youtube_url": self.settings.value("youtube_url", ""),
        }

        dialog = SettingsDialog(self)
        # リアルタイム反映の接続
        dialog.settings_changed.connect(lambda: self.update_live_settings_from_dialog(dialog))

        result = dialog.exec()
        if result == QDialog.Rejected:
            # キャンセルされた場合は設定値をロールバック
            for key, val in backup_settings.items():
                self.settings.setValue(key, val)
            self.append_log("設定変更がキャンセルされました。元の設定に戻します。")
            self.restore_settings_to_threads(backup_settings)

    def update_live_settings_from_dialog(self, dialog: SettingsDialog) -> None:
        # ダイアログで操作された最新値をスレッドへ即時反映
        if self.chat_worker is not None and self.chat_worker.isRunning():
            self.chat_worker.skip_history = dialog.skip_history_check.isChecked()
            self.chat_worker.read_author = dialog.read_author_check.isChecked()
            self.chat_worker.read_super_chat = dialog.read_super_chat_check.isChecked()
            self.chat_worker.max_length = dialog.max_length_spin.value()

        if self.speech_worker is not None and self.speech_worker.isRunning():
            self.speech_worker.speaker_id = dialog.speaker_spin.value()
            self.speech_worker.speed = dialog.speed_spin.value()

    def restore_settings_to_threads(self, backup: dict) -> None:
        # スレッドのパラメータをバックアップした元の値に復元
        if self.chat_worker is not None and self.chat_worker.isRunning():
            self.chat_worker.skip_history = backup["skip_history"]
            self.chat_worker.read_author = backup["read_author"]
            self.chat_worker.read_super_chat = backup["read_super_chat"]
            self.chat_worker.max_length = backup["max_length"]

        if self.speech_worker is not None and self.speech_worker.isRunning():
            self.speech_worker.speaker_id = backup["speaker_id"]
            self.speech_worker.speed = backup["speed"]

    def ensure_voicevox_running_with_path(self, url: str, path: str) -> bool:
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

    def start(self) -> None:
        url_or_id = self.settings.value("youtube_url", "")
        api_key = self.settings.value("api_key", "")
        voicevox_url = self.settings.value("voicevox_url", "http://127.0.0.1:50021")
        voicevox_path = self.settings.value("voicevox_path", "")

        if not url_or_id:
            QMessageBox.warning(self.window, "設定不足", "YouTube URL/動画IDが設定されていません。メニューの ツール->設定 から入力してください。")
            return
        if not api_key:
            QMessageBox.warning(self.window, "設定不足", "YouTube Data API Keyが設定されていません。メニューの ツール->設定 から入力してください。")
            return

        # VOICEVOXの自動起動
        self.ensure_voicevox_running_with_path(voicevox_url, voicevox_path)

        self.speech_queue = queue.Queue()
        self.speech_worker = SpeechWorker(
            speech_queue=self.speech_queue,
            voicevox_url=voicevox_url,
            speaker_id=int(self.settings.value("speaker_id", 3)),
            speed=float(self.settings.value("speed", 1.2)),
        )
        self.speech_worker.error.connect(self.show_error)
        self.speech_worker.start()

        self.chat_worker = ChatStreamWorker(
            speech_queue=self.speech_queue,
            youtube_url_or_id=url_or_id,
            api_key=api_key,
            skip_history=self.settings.value("skip_history", True, type=bool),
            read_author=self.settings.value("read_author", False, type=bool),
            read_super_chat=self.settings.value("read_super_chat", True, type=bool),
            max_length=int(self.settings.value("max_length", 80)),
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
    # Windowsのタスクバーでカスタムアイコンを正しく表示させるための設定
    if platform.system() == "Windows":
        import ctypes
        myappid = "Ikumyon.LiveVoiceBridge.App.1.0"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

    app = QApplication(sys.argv)

    # アプリのアイコンを設定
    if ICON_FILE.exists():
        from PySide6.QtGui import QIcon
        app.setWindowIcon(QIcon(str(ICON_FILE)))

    controller = LiveVoiceBridgeApp()
    controller.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

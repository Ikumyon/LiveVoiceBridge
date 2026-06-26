from __future__ import annotations

import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from PySide6.QtCore import QThread, Signal, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QVBoxLayout,
)

from core.app_config import EXE_DIR, EXTERNAL_LINK_ICON_FILE, X_ICON_FILE
from core.tts.engines.supertonic import SupertonicEngine


SUPERTONIC_REPO_URL = "https://huggingface.co/Supertone/supertonic-3"
SUPERTONIC_RESOLVE_URL = f"{SUPERTONIC_REPO_URL}/resolve/main"


class SupertonicModelDownloadWorker(QThread):
    progress = Signal(int, str)
    finished = Signal(bool, str)

    def __init__(self, model_dir: Path):
        super().__init__()
        self.model_dir = model_dir
        self._is_cancelled = False

    def cancel(self) -> None:
        self._is_cancelled = True

    def run(self) -> None:
        try:
            files = SupertonicEngine.REQUIRED_FILES
            total_files = len(files)
            self.model_dir.mkdir(parents=True, exist_ok=True)

            for index, relative_path in enumerate(files, start=1):
                if self._is_cancelled:
                    self.finished.emit(False, "キャンセルされました。")
                    return

                percent = int(((index - 1) / total_files) * 100)
                self.progress.emit(
                    percent,
                    f"ダウンロード中... ({index} / {total_files}) {relative_path}",
                )
                self._download_file(relative_path)

            self.progress.emit(100, "完了しました。")
            self.finished.emit(True, "SUPERTONIC 3モデルのダウンロードと配置が完了しました。")
        except Exception as exc:
            self.finished.emit(False, f"SUPERTONIC 3モデルのダウンロードに失敗しました: {exc}")

    def _download_file(self, relative_path: str) -> None:
        encoded_path = urllib.parse.quote(relative_path, safe="/")
        url = f"{SUPERTONIC_RESOLVE_URL}/{encoded_path}?download=true"
        destination = self.model_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)

        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=destination.suffix)
        temp_file.close()
        temp_path = Path(temp_file.name)

        try:
            request = urllib.request.Request(url, headers={"User-Agent": "LiveVoiceBridge"})
            with urllib.request.urlopen(request, timeout=30) as response:
                with open(temp_path, "wb") as handle:
                    while True:
                        if self._is_cancelled:
                            temp_path.unlink(missing_ok=True)
                            return
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
            temp_path.replace(destination)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise


class SupertonicModelDownloader:
    def __init__(self, parent_window, engine_settings: dict, settings_changed_signal: Signal):
        self.parent_window = parent_window
        self.engine_settings = engine_settings
        self.settings_changed_signal = settings_changed_signal
        self.progress_dialog: QProgressDialog | None = None
        self.download_worker: SupertonicModelDownloadWorker | None = None

    def start(self) -> None:
        if not self._show_license_dialog():
            return

        model_path_rel = "models/supertonic-3"
        model_dir = EXE_DIR / model_path_rel

        self.progress_dialog = QProgressDialog(
            "SUPERTONIC 3モデルのダウンロード準備中...",
            "キャンセル",
            0,
            100,
            self.parent_window,
        )
        self.progress_dialog.setWindowTitle("SUPERTONIC 3モデルのダウンロード")
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setAutoClose(True)

        self.download_worker = SupertonicModelDownloadWorker(model_dir)
        self.download_worker.progress.connect(self._on_download_progress)
        self.download_worker.finished.connect(self._on_download_finished)
        self.progress_dialog.canceled.connect(self.download_worker.cancel)

        self.download_worker.start()
        self.progress_dialog.exec()
        self._cleanup_worker()

    def _show_license_dialog(self) -> bool:
        dialog = QDialog(self.parent_window)
        dialog.setWindowTitle("ライセンスの確認")
        dialog.setMinimumWidth(400)

        layout = QVBoxLayout(dialog)

        label_title = QLabel("<h3>SUPERTONIC 3モデルのライセンス確認</h3>", dialog)
        label_title.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(label_title)

        label_desc = QLabel(
            "SUPERTONIC 3モデルをダウンロードします。<br><br>"
            "使用前にライセンスと配布元の情報を確認してください。"
            "以下のボタンでモデルページを開くと、ダウンロードボタンが有効になります。",
            dialog,
        )
        label_desc.setWordWrap(True)
        label_desc.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(label_desc)

        link_btn = QPushButton(" モデルページを開く (ブラウザ)", dialog)
        if EXTERNAL_LINK_ICON_FILE.exists():
            from core.ui.helpers import load_svg_icon

            link_btn.setIcon(load_svg_icon(EXTERNAL_LINK_ICON_FILE, link_btn))
        layout.addWidget(link_btn)

        btn_layout = QHBoxLayout()
        download_btn = QPushButton("同意してダウンロード", dialog)
        download_btn.setEnabled(False)

        cancel_btn = QPushButton(" キャンセル", dialog)
        if X_ICON_FILE.exists():
            from core.ui.helpers import load_svg_icon

            cancel_btn.setIcon(load_svg_icon(X_ICON_FILE, cancel_btn))

        btn_layout.addWidget(download_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        def on_link_clicked() -> None:
            QDesktopServices.openUrl(QUrl(SUPERTONIC_REPO_URL))
            download_btn.setEnabled(True)

        link_btn.clicked.connect(on_link_clicked)
        download_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)

        return dialog.exec() == QDialog.DialogCode.Accepted

    def _on_download_progress(self, percent: int, message: str) -> None:
        if self.progress_dialog:
            self.progress_dialog.setValue(percent)
            self.progress_dialog.setLabelText(message)

    def _on_download_finished(self, success: bool, message: str) -> None:
        if self.progress_dialog:
            self.progress_dialog.close()

        if success:
            QMessageBox.information(self.parent_window, "完了", message)
            self.engine_settings["supertonic"]["path"] = "models/supertonic-3"
            self.settings_changed_signal.emit()
        elif "キャンセル" in message:
            QMessageBox.information(self.parent_window, "キャンセル", message)
        else:
            QMessageBox.critical(self.parent_window, "エラー", message)

        self._cleanup_worker()

    def _cleanup_worker(self) -> None:
        if self.download_worker is None:
            return
        if self.download_worker.isRunning():
            self.download_worker.cancel()
            if not self.download_worker.wait(30000):
                self.download_worker.terminate()
                self.download_worker.wait()
        self.download_worker.deleteLater()
        self.download_worker = None

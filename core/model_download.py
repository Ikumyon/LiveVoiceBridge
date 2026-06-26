from __future__ import annotations

import os
import tempfile
import urllib.request
import tarfile
from pathlib import Path

from PySide6.QtCore import QThread, Signal, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QHBoxLayout,
    QProgressDialog,
    QMessageBox
)

from core.app_config import EXE_DIR, EXTERNAL_LINK_ICON_FILE, X_ICON_FILE


class ModelDownloadWorker(QThread):
    progress = Signal(int, str)  # 進捗率 (%), メッセージ
    finished = Signal(bool, str) # 成功したか, メッセージ

    def __init__(self, download_url: str, dest_dir: Path):
        super().__init__()
        self.download_url = download_url
        self.dest_dir = dest_dir
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            self.progress.emit(0, "ダウンロード中...")
            
            # 一時ファイルへダウンロード
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".tar.bz2")
            temp_file.close()
            temp_path = Path(temp_file.name)
            
            req = urllib.request.Request(self.download_url, headers={"User-Agent": "LiveVoiceBridge"})
            with urllib.request.urlopen(req, timeout=30) as response:
                total_size = int(response.info().get("Content-Length", 0))
                downloaded_size = 0
                block_size = 8192
                
                with open(temp_path, "wb") as f:
                    while True:
                        if self._is_cancelled:
                            self.finished.emit(False, "キャンセルされました。")
                            try:
                                temp_path.unlink(missing_ok=True)
                            except Exception:
                                pass
                            return
                            
                        buffer = response.read(block_size)
                        if not buffer:
                            break
                        f.write(buffer)
                        downloaded_size += len(buffer)
                        if total_size > 0:
                            pct = int((downloaded_size / total_size) * 80)
                            self.progress.emit(pct, f"ダウンロード中... ({downloaded_size // 1024} KB / {total_size // 1024} KB)")
            
            self.progress.emit(80, "アーカイブを展開中...")
            if self._is_cancelled:
                self.finished.emit(False, "キャンセルされました。")
                temp_path.unlink(missing_ok=True)
                return
                
            self.dest_dir.mkdir(parents=True, exist_ok=True)
            with tarfile.open(temp_path, "r:bz2") as tar:
                members = tar.getmembers()
                total_members = len(members)
                for idx, member in enumerate(members):
                    if self._is_cancelled:
                        self.finished.emit(False, "キャンセルされました。")
                        temp_path.unlink(missing_ok=True)
                        return
                    
                    tar.extract(member, path=self.dest_dir)
                    
                    if total_members > 0:
                        pct = 80 + int((idx / total_members) * 20)
                        self.progress.emit(pct, f"展開中... ({idx} / {total_members})")
            
            temp_path.unlink(missing_ok=True)
            self.progress.emit(100, "完了しました。")
            self.finished.emit(True, "モデルのダウンロードと配置が完了しました。")
            
        except Exception as e:
            self.finished.emit(False, f"エラーが発生しました: {e}")


class ModelDownloader:
    def __init__(self, parent_window, engine_settings: dict, settings_changed_signal: Signal):
        self.parent_window = parent_window
        self.engine_settings = engine_settings
        self.settings_changed_signal = settings_changed_signal
        self.progress_dialog = None
        self.download_worker = None

    def start(self) -> None:
        if not self._show_license_dialog():
            return
            
        download_url = (
            "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/"
            "sherpa-onnx-supertonic-3-tts-int8-2026-05-11.tar.bz2"
        )
        dest_dir = EXE_DIR / "models"
        
        self.progress_dialog = QProgressDialog("モデルのダウンロード準備中...", "キャンセル", 0, 100, self.parent_window)
        self.progress_dialog.setWindowTitle("モデルのダウンロード/更新")
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setAutoClose(True)
        
        self.download_worker = ModelDownloadWorker(download_url, dest_dir)
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
        
        label_title = QLabel("<h3>音声モデルのライセンス確認</h3>", dialog)
        label_title.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(label_title)
        
        label_desc = QLabel(
            "Supertonic 3 軽量版モデルをダウンロードします。<br><br>"
            "このモデルを使用する前に、利用規約およびライセンスを確認し、同意する必要があります。<br>"
            "以下のボタンをクリックしてライセンス情報（ブラウザで開きます）をご確認ください。<br>"
            "※ライセンスを確認すると、ダウンロードボタンが有効化されます。",
            dialog
        )
        label_desc.setWordWrap(True)
        label_desc.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(label_desc)
        
        # 外部リンクを開くボタン
        link_btn = QPushButton(" ライセンスページを開く (ブラウザ)", dialog)
        if EXTERNAL_LINK_ICON_FILE.exists():
            from core.ui.helpers import load_svg_icon
            link_btn.setIcon(load_svg_icon(EXTERNAL_LINK_ICON_FILE, link_btn))
        layout.addWidget(link_btn)
        
        # 下部ボタンレイアウト
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
        
        license_url = "https://github.com/k2-fsa/sherpa-onnx/blob/master/LICENSE"
        
        def on_link_clicked():
            QDesktopServices.openUrl(QUrl(license_url))
            download_btn.setEnabled(True)
            
        link_btn.clicked.connect(on_link_clicked)
        
        def on_download_clicked():
            dialog.accept()
            
        download_btn.clicked.connect(on_download_clicked)
        cancel_btn.clicked.connect(dialog.reject)
        
        return dialog.exec() == QDialog.DialogCode.Accepted

    def _on_download_progress(self, percent: int, message: str) -> None:
        if self.progress_dialog:
            self.progress_dialog.setValue(percent)
            self.progress_dialog.setLabelText(message)

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

    def _on_download_finished(self, success: bool, message: str) -> None:
        if self.progress_dialog:
            self.progress_dialog.close()
            
        if success:
            QMessageBox.information(self.parent_window, "完了", message)
            model_path_rel = "models/sherpa-onnx-supertonic-3-tts-int8-2026-05-11"
            self.engine_settings["supertonic_lightweight"]["path"] = model_path_rel
            self.settings_changed_signal.emit()
        else:
            if "キャンセル" in message:
                QMessageBox.information(self.parent_window, "キャンセル", message)
            else:
                QMessageBox.critical(self.parent_window, "エラー", message)

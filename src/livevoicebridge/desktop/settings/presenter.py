"""Own asynchronous settings operations; the view only edits a draft."""

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QDialog, QLabel, QMessageBox, QPlainTextEdit, QPushButton

from livevoicebridge.core.session.service import SessionService
from livevoicebridge.core.speech.models import Qwen3Config, TtsEngineKind
from livevoicebridge.desktop.dictionary.presenter import DictionaryPresenter
from livevoicebridge.desktop.settings.qwen import QwenSetup
from livevoicebridge.desktop.settings.view import SettingsDialog


class SettingsPresenter(QObject):
    discovery_completed = Signal(object, object, str)
    save_completed = Signal(str)

    def __init__(self, view: SettingsDialog, session: SessionService):
        super().__init__(view)
        self._view = view
        self._session = session
        self._closed = False
        self.discovery_completed.connect(self._on_discovered)
        self.save_completed.connect(self._on_saved)
        view.engines.speakers_requested.connect(self._discover)
        self._dictionary = DictionaryPresenter(
            view.dictionary, session.dictionary.repository, session.dictionary.editor
        )
        view.save_requested.connect(self._save)
        view.dialog_window.finished.connect(self._finish)
        self._qwen_setup: QwenSetup | None = None
        self._qwen_saved = session.settings.current.speech.engine(TtsEngineKind.QWEN3)
        self._qwen_phase = ""
        window = view.dialog_window
        self._qwen_label = window.findChild(QLabel, "qwen3StateLabel")
        self._qwen_log = window.findChild(QPlainTextEdit, "qwen3LogText")
        self._qwen_details = window.findChild(QPushButton, "qwen3LogButton")
        self._qwen_restart = window.findChild(QPushButton, "qwen3RestartButton")
        self._qwen_prepare = window.findChild(QPushButton, "qwen3SetupButton")
        self._qwen_details.toggled.connect(self._qwen_log.setVisible)
        self._qwen_restart.clicked.connect(self._restart_qwen)
        self._qwen_prepare.clicked.connect(self._prepare_qwen)
        self._qwen_timer = QTimer(self)
        self._qwen_timer.setInterval(500)
        self._qwen_timer.timeout.connect(self._refresh_qwen)
        self._qwen_timer.start()
        self._refresh_qwen()

    def _prepare_qwen(self):
        if self._session.qwen is None:
            return
        if self._qwen_setup is not None:
            self._qwen_setup.window.raise_()
            return
        self._qwen_setup = QwenSetup(
            self._session.qwen, self._view.dialog_window, self._view.engines.device.currentText()
        )
        self._qwen_setup.window.finished.connect(lambda _: setattr(self, "_qwen_setup", None))

    def _restart_qwen(self):
        self._session.restart_qwen()

    def _refresh_qwen(self):
        runtime = self._session.qwen
        if runtime is None or self._closed:
            return
        state = runtime.state
        self._qwen_label.setText(state.message)
        self._qwen_restart.setEnabled(
            not state.busy
            and self._view.engines.active is TtsEngineKind.QWEN3
            and bool(self._view.engines.model_line.text())
        )
        self._qwen_prepare.setEnabled(not state.busy)
        saved = self._session.settings.current.speech.engine(TtsEngineKind.QWEN3)
        if isinstance(saved, Qwen3Config) and isinstance(self._qwen_saved, Qwen3Config):
            if (saved.model_path, saved.device) != (self._qwen_saved.model_path, self._qwen_saved.device):
                self._view.engines.update_qwen(saved)
                self._qwen_saved = saved
        if state.phase == "ready" and self._qwen_phase != "ready" and self._view.engines.active is TtsEngineKind.QWEN3:
            self._view.engines.request_speakers()
        self._qwen_phase = state.phase
        if self._qwen_details.isChecked():
            text = runtime.read_log()
            if text != self._qwen_log.toPlainText():
                self._qwen_log.setPlainText(text)

    def _discover(self, config):
        if isinstance(config, Qwen3Config) and self._session.qwen is not None:
            if self._session.qwen.state.phase != "ready":
                self._view.engines.test_button.setEnabled(True)
                return
        source = self._view.engines.speaker_source()

        def complete(speakers, error):
            if not self._closed:
                self.discovery_completed.emit(source, speakers, error)

        self._session.discover(config, complete)

    def _on_discovered(self, source, speakers, error):
        if self._closed:
            return
        self._view.engines.test_button.setEnabled(True)
        if source == self._view.engines.speaker_source():
            self._view.engines.receive_speakers(speakers, error)

    def _save(self):
        self._view.dialog_window.setEnabled(False)

        def flushed(draft, error):
            if error or draft is None:
                self._on_saved(error or "辞書の準備が完了していません。")
                return
            baseline = self._qwen_saved if isinstance(self._qwen_saved, Qwen3Config) else None
            self._session.apply_settings(self._view.config, draft, baseline, self.save_completed.emit)

        self._dictionary.flush(flushed)

    def _on_saved(self, error):
        if self._closed:
            return
        self._view.dialog_window.setEnabled(True)
        if error:
            self._dictionary.resume()
            QMessageBox.critical(self._view.dialog_window, "保存エラー", error)
            return
        self._view.dialog_window.accept()

    def _finish(self, result):
        self._refresh_qwen()
        self._closed = True
        self._dictionary.close(result == QDialog.DialogCode.Accepted)
        self._qwen_timer.stop()
        if self._qwen_setup is not None:
            self._qwen_setup.window.reject()

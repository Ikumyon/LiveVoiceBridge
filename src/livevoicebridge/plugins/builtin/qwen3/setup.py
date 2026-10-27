"""Designer-defined provisioning dialog, driven by an application lifecycle port."""

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
)

from livevoicebridge.plugins.builtin.qwen3.contracts import QwenRuntime

from .ui_setup import create_form


class QwenSetup(QObject):
    def __init__(self, runtime: QwenRuntime, parent, device: str):
        super().__init__(parent)
        self.runtime = runtime
        self.window = create_form()
        self.window.setParent(parent, self.window.windowFlags())
        self.local = self.window.findChild(QRadioButton, "localRadio")
        self.download = self.window.findChild(QRadioButton, "downloadRadio")
        self.source = self.window.findChild(QLineEdit, "sourceLine")
        self.browse = self.window.findChild(QPushButton, "browseButton")
        self.device = self.window.findChild(QComboBox, "deviceCombo")
        self.device.setCurrentText(device)
        self.status = self.window.findChild(QLabel, "stateLabel")
        self.progress = self.window.findChild(QProgressBar, "progressBar")
        self.start = self.window.findChild(QPushButton, "startButton")
        self.cancel = self.window.findChild(QPushButton, "cancelButton")
        self.log = self.window.findChild(QPlainTextEdit, "logText")
        self.details = self.window.findChild(QPushButton, "detailsButton")
        self._started = False
        self._done = False
        self._last_log = ""
        self.local.toggled.connect(self.browse.setEnabled)
        self.browse.clicked.connect(self._browse)
        self.start.clicked.connect(self._start)
        self.cancel.clicked.connect(self._cancel)
        self.details.toggled.connect(self.log.setVisible)
        self.window.finished.connect(self._finish)
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._refresh)
        self.timer.start()
        self.window.open()

    def _browse(self):
        path = QFileDialog.getExistingDirectory(self.window, "Qwenモデルのフォルダーを選択")
        if path:
            self.source.setText(path)

    def _start(self):
        if self._done:
            self.window.accept()
            return
        if self.local.isChecked() and not self.source.text():
            self.status.setText("モデルのフォルダーを選択してください。")
            return
        self._started = True
        self.runtime.prepare(self.source.text() if self.local.isChecked() else "", self.device.currentText())
        self._refresh()

    def _cancel(self):
        if self.runtime.state.busy and self._started:
            self.runtime.cancel_preparation()
            self.status.setText("準備を中止しています…")
        else:
            self.window.reject()

    def _refresh(self):
        if not self._started:
            return
        state = self.runtime.state
        self.status.setText(state.message)
        self._done = bool(state.model_path) and state.phase in {"prepared", "loading", "warming", "ready"}
        self.progress.setVisible(state.busy)
        self.progress.setRange(0, 100 if state.progress is not None else 0)
        self.progress.setValue(state.progress or 0)
        self.start.setEnabled(not state.busy)
        self.start.setText("完了" if self._done else "再試行")
        self.cancel.setText("準備を中止" if state.busy else "閉じる")
        for widget in (self.download, self.local, self.device):
            widget.setEnabled(not state.busy)
        self.browse.setEnabled(not state.busy and self.local.isChecked())
        if self.details.isChecked():
            text = self.runtime.read_log()
            if text != self._last_log:
                self._last_log = text
                self.log.setPlainText(text)
                self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _finish(self, _result):
        self.timer.stop()
        if self._started and self.runtime.state.busy:
            self.runtime.cancel_preparation()
        self.window.deleteLater()
        self.deleteLater()

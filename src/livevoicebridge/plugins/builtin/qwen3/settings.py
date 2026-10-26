"""Qwen lifecycle controls owned by the bundled plugin."""

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QPushButton

from livevoicebridge.desktop.forms import load_ui_file
from livevoicebridge.plugins.contracts import EngineConfig

from .setup import QwenSetup


class QwenPage:
    def __init__(self, provider, parent, read_config):
        self.provider = provider
        self._read_config = read_config
        self.runtime = provider.runtime
        self.widget = load_ui_file(Path(__file__).with_suffix(".ui"))
        self._setup = None
        self._label = self.widget.findChild(QLabel, "stateLabel")
        self._log = self.widget.findChild(QPlainTextEdit, "logText")
        self._details = self.widget.findChild(QPushButton, "logButton")
        self._prepare = self.widget.findChild(QPushButton, "setupButton")
        self._restart = self.widget.findChild(QPushButton, "restartButton")
        self._prepare.clicked.connect(self._open_setup)
        self._restart.clicked.connect(self.runtime.restart)
        self._details.toggled.connect(self._log.setVisible)
        self._timer = QTimer(self.widget)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()
        self._refresh()

    def _open_setup(self):
        if self._setup is not None:
            self._setup.window.raise_()
            return
        config = self._read_config()
        self._setup = QwenSetup(self.runtime, self.widget, str(config.settings["device"]))
        self._setup.window.finished.connect(lambda _: setattr(self, "_setup", None))

    def _refresh(self):
        state = self.runtime.state
        self._label.setText(state.message)
        self._prepare.setEnabled(not state.busy)
        self._restart.setEnabled(not state.busy and bool(state.model_path))
        if self._details.isChecked():
            text = self.runtime.read_log()
            if text != self._log.toPlainText():
                self._log.setPlainText(text)

    def read(self, config: EngineConfig) -> EngineConfig:
        return config

    def close(self):
        self._timer.stop()
        if self._setup is not None:
            self._setup.window.reject()

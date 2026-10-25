"""Typed engine drafts and bindings to existing Designer controls."""

from dataclasses import replace
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QWidget,
)

from livevoicebridge.core.speech.models import (
    EngineConfig,
    Qwen3Config,
    Speaker,
    SpeechConfig,
    TtsEngineKind,
    update_engine,
)
from livevoicebridge.desktop.settings.speakers import SpeakerMenu

_FIELDS: dict[TtsEngineKind, dict[str, tuple[type, str]]] = {
    TtsEngineKind.VOICEVOX: {
        "url": (QLineEdit, "voicevoxUrlLineEdit"),
        "executable_path": (QLineEdit, "voicevoxPathLineEdit"),
        "speed": (QDoubleSpinBox, "voicevoxSpeedDoubleSpinBox"),
        "pitch": (QDoubleSpinBox, "voicevoxPitchDoubleSpinBox"),
        "intonation": (QDoubleSpinBox, "voicevoxIntonationDoubleSpinBox"),
        "volume": (QDoubleSpinBox, "voicevoxVolumeDoubleSpinBox"),
        "pause_length": (QDoubleSpinBox, "voicevoxPauseLengthDoubleSpinBox"),
        "pre_phoneme_length": (QDoubleSpinBox, "voicevoxPrePhonemeLengthDoubleSpinBox"),
        "post_phoneme_length": (QDoubleSpinBox, "voicevoxPostPhonemeLengthDoubleSpinBox"),
        "max_length": (QSpinBox, "voicevoxMaxLengthSpinBox"),
    },
    TtsEngineKind.COEIROINK: {
        "url": (QLineEdit, "coeiroinkUrlLineEdit"),
        "executable_path": (QLineEdit, "coeiroinkPathLineEdit"),
        "speed": (QDoubleSpinBox, "coeiroinkSpeedDoubleSpinBox"),
        "pitch": (QDoubleSpinBox, "coeiroinkPitchDoubleSpinBox"),
        "intonation": (QDoubleSpinBox, "coeiroinkIntonationDoubleSpinBox"),
        "volume": (QDoubleSpinBox, "coeiroinkVolumeDoubleSpinBox"),
        "pause_length": (QDoubleSpinBox, "coeiroinkPauseLengthDoubleSpinBox"),
        "pre_phoneme_length": (QDoubleSpinBox, "coeiroinkPrePhonemeLengthDoubleSpinBox"),
        "post_phoneme_length": (QDoubleSpinBox, "coeiroinkPostPhonemeLengthDoubleSpinBox"),
        "max_length": (QSpinBox, "coeiroinkMaxLengthSpinBox"),
    },
    TtsEngineKind.BOUYOMICHAN: {
        "url": (QLineEdit, "bouyomichanUrlLineEdit"),
        "executable_path": (QLineEdit, "bouyomichanPathLineEdit"),
        "speed": (QSpinBox, "bouyomichanSpeedSpinBox"),
        "pitch": (QSpinBox, "bouyomichanPitchSpinBox"),
        "volume": (QSpinBox, "bouyomichanVolumeSpinBox"),
        "max_length": (QSpinBox, "bouyomichanMaxLengthSpinBox"),
    },
    TtsEngineKind.QWEN3: {
        "model_path": (QLineEdit, "qwen3ModelLineEdit"),
        "device": (QComboBox, "qwen3DeviceCombo"),
        "volume": (QDoubleSpinBox, "qwen3VolumeSpinBox"),
        "max_length": (QSpinBox, "qwen3MaxLengthSpinBox"),
    },
}


class EngineEditor(QObject):
    changed = Signal()
    speakers_requested = Signal(object)

    def __init__(self, window: QWidget, config: SpeechConfig, executable_filter: str):
        super().__init__(window)
        self.window = window
        self.config = config
        self.active = config.active_engine
        self._configs = {engine.kind: engine for engine in config.engines}
        self._speaker_ids = {engine.kind: engine.speaker_id for engine in config.engines}
        self._executable_filter = executable_filter
        self._source_loaded: tuple[str, str, str] | None = None
        self._controls: dict[TtsEngineKind, dict[str, Any]] = {}
        for kind, fields in _FIELDS.items():
            controls = self._controls[kind] = {}
            for field, (widget_type, name) in fields.items():
                widget = controls[field] = window.findChild(widget_type, name)
                value = getattr(self._configs[kind], field)
                if isinstance(widget, QLineEdit):
                    widget.setText(value)
                    widget.textChanged.connect(lambda _: self.changed.emit())
                elif isinstance(widget, QComboBox):
                    widget.setCurrentText(value)
                    widget.currentTextChanged.connect(lambda _: self.changed.emit())
                else:
                    widget.setValue(value)
                    widget.valueChanged.connect(lambda _: self.changed.emit())
        for kind, name in (
            (TtsEngineKind.VOICEVOX, "voicevoxPathBrowseButton"),
            (TtsEngineKind.COEIROINK, "coeiroinkPathBrowseButton"),
            (TtsEngineKind.BOUYOMICHAN, "bouyomichanPathBrowseButton"),
        ):
            window.findChild(QPushButton, name).clicked.connect(lambda _, selected=kind: self._browse(selected))
        self.model_line: QLineEdit = self._controls[TtsEngineKind.QWEN3]["model_path"]
        self.device: QComboBox = self._controls[TtsEngineKind.QWEN3]["device"]
        self.test_button = window.findChild(QPushButton, "ttsTestButton")
        self.test_button.clicked.connect(self.request_speakers)
        self.speakers = SpeakerMenu(window)
        self.speakers.changed.connect(self._speaker_changed)
        self.speakers.requested.connect(self._discover_if_changed)
        self.combo = window.findChild(QComboBox, "ttsEngineComboBox")
        self.stack = window.findChild(QStackedWidget, "ttsEngineStackedWidget")
        self.combo.setCurrentText(self.active.value.upper())
        self._show_engine()
        self.combo.currentTextChanged.connect(self._select)

    def engine(self, kind: TtsEngineKind | None = None) -> EngineConfig:
        kind = self.active if kind is None else kind
        values: dict[str, Any] = {"speaker_id": self._speaker_ids[kind]}
        for field, widget in self._controls[kind].items():
            if isinstance(widget, QLineEdit):
                values[field] = widget.text().strip()
            elif isinstance(widget, QComboBox):
                values[field] = widget.currentText()
            else:
                values[field] = widget.value()
        return update_engine(self._configs[kind], values)

    def read(self) -> SpeechConfig:
        return replace(
            self.config, active_engine=self.active, engines=tuple(self.engine(kind) for kind in self._configs)
        )

    def update_qwen(self, config: Qwen3Config) -> None:
        self._configs[TtsEngineKind.QWEN3] = update_engine(
            self._configs[TtsEngineKind.QWEN3], {"model_path": config.model_path, "device": config.device}
        )
        self.model_line.setText(config.model_path)
        self.device.setCurrentText(config.device)

    def speaker_source(self) -> tuple[str, str, str]:
        config = self.engine()
        if isinstance(config, Qwen3Config):
            return config.kind.value, config.model_path, config.device
        return config.kind.value, config.url.rstrip("/"), config.executable_path

    def _discover_if_changed(self) -> None:
        if self.speaker_source() != self._source_loaded:
            self.request_speakers()

    def request_speakers(self) -> None:
        self._source_loaded = self.speaker_source()
        self.test_button.setEnabled(False)
        self.speakers_requested.emit(self.engine())

    def receive_speakers(self, speakers: tuple[Speaker, ...], error: str) -> None:
        self.test_button.setEnabled(True)
        if error:
            self._source_loaded = None
            QMessageBox.warning(self.window, "話者取得", error)
            return
        self.speakers.receive(speakers)

    def _speaker_changed(self) -> None:
        self._speaker_ids[self.active] = self.speakers.current_speaker_id
        self.changed.emit()

    def _select(self, name: str) -> None:
        selected = TtsEngineKind(name.lower())
        if selected == self.active:
            return
        self.active = selected
        self._source_loaded = None
        self._show_engine()
        self.changed.emit()

    def _show_engine(self) -> None:
        self.stack.setCurrentWidget(self.window.findChild(QWidget, self.active.value + "Page"))
        self.speakers.select_engine(self._speaker_ids[self.active])

    def _browse(self, kind: TtsEngineKind) -> None:
        line = self._controls[kind]["executable_path"]
        path, _ = QFileDialog.getOpenFileName(
            self.window, "音声合成エンジン実行ファイルを選択", line.text().strip(), self._executable_filter
        )
        if path:
            line.setText(path)

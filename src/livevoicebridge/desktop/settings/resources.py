"""Edit bounded resource settings using Designer controls."""

from PySide6.QtCore import QObject, QSignalBlocker, Signal
from PySide6.QtWidgets import QSlider, QSpinBox, QWidget

from livevoicebridge.core.settings.models import ResourceLimits


class ResourceEditor(QObject):
    changed = Signal()

    def __init__(self, window: QWidget, config: ResourceLimits):
        super().__init__(window)
        self.dialog_window = window
        self._bind_resource_widgets(config)

    def read(self) -> ResourceLimits:
        return ResourceLimits(**{key: spin.value() for key, (_, spin) in self._resource_controls.items()})

    def _bind_resource_widgets(self, config: ResourceLimits) -> None:
        self._resource_controls: dict[str, tuple[QSlider, QSpinBox]] = {}
        for name in ("comment_count", "log_lines", "audio_mib", "avatar_mib"):
            slider = self.dialog_window.findChild(QSlider, name + "Slider")
            spin = self.dialog_window.findChild(QSpinBox, name + "SpinBox")
            self._resource_controls[name] = (slider, spin)
            spin.setValue(getattr(config, name))
            slider.setValue(spin.value())
            slider.valueChanged.connect(lambda value, key=name: self._set_resource_value(key, value))
            spin.valueChanged.connect(lambda value, key=name: self._set_resource_value(key, value))

    def _set_resource_value(self, key: str, value: int) -> None:
        slider, spin = self._resource_controls[key]
        step = spin.singleStep()
        value = min(spin.maximum(), max(spin.minimum(), round(value / step) * step))
        with QSignalBlocker(slider), QSignalBlocker(spin):
            slider.setValue(value)
            spin.setValue(value)
        self.changed.emit()

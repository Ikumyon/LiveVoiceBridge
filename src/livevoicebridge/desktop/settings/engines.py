"""Provider-driven TTS settings using Designer field templates."""

from dataclasses import replace
from typing import Any

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from livevoicebridge.core.speech.models import EngineConfig, Speaker, SpeechConfig
from livevoicebridge.desktop.forms import load_form
from livevoicebridge.desktop.settings.speakers import SpeakerMenu
from livevoicebridge.plugins.contracts import SettingField
from livevoicebridge.plugins.manager import PluginManager
from livevoicebridge.plugins.ui import SettingsPage


class EngineEditor(QObject):
    changed = Signal()
    speakers_requested = Signal(object)

    def __init__(self, window: QWidget, config: SpeechConfig, executable_filter: str, plugins: PluginManager):
        super().__init__(window)
        self.window, self.config, self.plugins = window, config, plugins
        self.active = config.active_engine
        self._configs = {engine.engine_id: engine for engine in config.engines}
        self._saved = dict(self._configs)
        self._executable_filter = executable_filter
        self._source_loaded: EngineConfig | None = None
        self._rows: list[tuple[SettingField, QWidget, Any]] = []
        self._page: SettingsPage | None = None
        self.combo = window.findChild(QComboBox, "ttsEngineComboBox")
        self.layout = window.findChild(QVBoxLayout, "engineSettingsLayout")
        self.status = window.findChild(QLabel, "ttsUnavailableLabel")
        self.speaker_line = window.findChild(QLineEdit, "speakerIdLine")
        self.maximum = window.findChild(QSpinBox, "maximumSpin")
        self.test_button = window.findChild(QPushButton, "ttsTestButton")
        self.speakers = SpeakerMenu(window)
        self.speakers.changed.connect(self._speaker_changed)
        self.speakers.requested.connect(self.request_speakers)
        self.test_button.clicked.connect(lambda: self.request_speakers(force=True))
        self.speaker_line.textChanged.connect(self.changed.emit)
        self.maximum.valueChanged.connect(self.changed.emit)
        for key, provider in plugins.providers.items():
            self.combo.addItem(provider.name, key)
        if self.active not in plugins.providers:
            self.combo.addItem(f"{self.active}（利用不可）", self.active)
        self.combo.setCurrentIndex(self.combo.findData(self.active))
        self.combo.currentIndexChanged.connect(self._select)
        self._show_engine()

    def _clear(self) -> None:
        if self._page is not None:
            self._page.close()
            self._page = None
        self._rows.clear()
        while self.layout.count():
            item = self.layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

    def _show_engine(self) -> None:
        self._clear()
        config = self._configs[self.active]
        self.speaker_line.setText(config.speaker_id)
        self.maximum.setValue(config.max_length)
        self.speakers.select_engine(config.speaker_id)
        provider = self.plugins.providers.get(self.active)
        available = provider is not None
        for widget in (self.test_button, self.speaker_line, self.maximum, self.speakers.speaker_button):
            widget.setEnabled(available)
        self.status.setText(
            "" if available else "このTTSは利用できません。プラグインの状態を確認するか、別のTTSを選択してください。"
        )
        if provider is None:
            return
        for field in provider.fields:
            self._add_row(field, config.settings.get(field.key, field.default))
        factory = self.plugins.contexts[self.active].settings_page
        if factory is not None:
            try:
                self._page = factory(self.window, self.engine)
                self.layout.addWidget(self._page.widget)
            except Exception as exc:
                self.status.setText(f"追加設定画面を開けません: {exc}")
        self.layout.addStretch()

    def _add_row(self, field: SettingField, value) -> None:
        row = load_form("plugin_setting_row")
        row.findChild(QLabel, "titleLabel").setText(field.title)
        stack = row.findChild(QStackedWidget, "valueStack")
        kind = field.kind
        page = kind if kind in {"number", "integer", "choice", "bool"} else "text"
        stack.setCurrentWidget(row.findChild(QWidget, page + "Page"))
        control: Any
        if page == "text":
            control = row.findChild(QLineEdit, "textValue")
            control.setText(str(value))
            if kind == "secret":
                control.setEchoMode(QLineEdit.EchoMode.Password)
            control.textChanged.connect(self.changed.emit)
            browse = row.findChild(QPushButton, "browseButton")
            browse.setVisible(kind in {"file", "directory"})
            browse.clicked.connect(lambda: self._browse(field, control))
        elif page == "choice":
            control = row.findChild(QComboBox, "choiceValue")
            control.addItems(field.choices)
            control.setCurrentText(str(value))
            control.currentTextChanged.connect(self.changed.emit)
        elif page == "bool":
            control = row.findChild(QCheckBox, "boolValue")
            control.setChecked(bool(value))
            control.toggled.connect(self.changed.emit)
        else:
            control = row.findChild(QSpinBox if page == "integer" else QDoubleSpinBox, page + "Value")
            if page == "integer":
                control.setRange(int(field.minimum), int(field.maximum))
            else:
                control.setRange(field.minimum, field.maximum)
            control.setValue(value)
            control.valueChanged.connect(self.changed.emit)
        self._rows.append((field, row, control))
        self.layout.addWidget(row)

    def _browse(self, field: SettingField, control: QLineEdit) -> None:
        if field.kind == "directory":
            path = QFileDialog.getExistingDirectory(self.window, field.title, control.text())
        else:
            path, _ = QFileDialog.getOpenFileName(self.window, field.title, control.text(), self._executable_filter)
        if path:
            control.setText(path)

    def engine(self) -> EngineConfig:
        config = self._configs[self.active]
        if self.active not in self.plugins.providers:
            return config
        values = dict(config.settings)
        for field, _row, control in self._rows:
            if field.kind == "bool":
                value = control.isChecked()
            elif field.kind == "choice":
                value = control.currentText()
            elif field.kind in {"number", "integer"}:
                value = control.value()
            else:
                value = control.text()
            values[field.key] = value
        draft = replace(
            config, settings=values, speaker_id=self.speaker_line.text().strip(), max_length=self.maximum.value()
        )
        return self._page.read(draft) if self._page is not None else draft

    def read(self) -> SpeechConfig:
        self._configs[self.active] = self.engine()
        return replace(self.config, active_engine=self.active, engines=tuple(self._configs.values()))

    def apply_saved(self, config: SpeechConfig) -> None:
        """Refresh background results without replacing the user's draft."""
        try:
            self._configs[self.active] = self.engine()
        except Exception as exc:
            self.status.setText(str(exc))
            return
        for latest in config.engines:
            identifier = latest.engine_id
            before = self._saved.get(identifier)
            draft = self._configs.get(identifier)
            if before is None or draft is None:
                continue
            values = dict(draft.settings)
            for key, value in latest.settings.items():
                if before.settings.get(key) == value or values.get(key) != before.settings.get(key):
                    continue
                values[key] = value
                if identifier == self.active:
                    for field, _row, control in self._rows:
                        if field.key != key:
                            continue
                        if field.kind == "bool":
                            control.setChecked(bool(value))
                        elif field.kind == "choice":
                            control.setCurrentText(str(value))
                        elif field.kind in {"number", "integer"}:
                            control.setValue(value)
                        else:
                            control.setText(str(value))
            self._configs[identifier] = replace(draft, settings=values)
        self._saved = {engine.engine_id: engine for engine in config.engines}

    def _select(self, _index: int) -> None:
        self._configs[self.active] = self.engine()
        self.active = self.combo.currentData()
        self._source_loaded = None
        self._show_engine()
        self.changed.emit()

    def speaker_source(self) -> EngineConfig:
        return self.engine()

    def request_speakers(self, force: bool = False) -> None:
        if self.active not in self.plugins.providers:
            return
        source = self.engine()
        if not force and self._source_loaded == source:
            return
        self._source_loaded = source
        self.test_button.setEnabled(False)
        self.speakers_requested.emit(source)

    def receive_speakers(self, speakers: tuple[Speaker, ...], error: str) -> None:
        self.test_button.setEnabled(True)
        if error:
            self._source_loaded = None
            QMessageBox.warning(self.window, "話者取得", error)
        else:
            self.speakers.receive(speakers)

    def _speaker_changed(self) -> None:
        self.speaker_line.setText(self.speakers.current_speaker_id)
        self.changed.emit()

    def close(self) -> None:
        self._clear()


class PluginEditor(QObject):
    changed = Signal()

    def __init__(self, window: QWidget, plugins: PluginManager, enabled: tuple[tuple[str, bool], ...]):
        super().__init__(window)
        self._values = dict(enabled)
        self._plugins = plugins
        self._table = window.findChild(QTableWidget, "pluginsTable")
        self._restart = window.findChild(QLabel, "pluginsRestartLabel")
        self._table.setRowCount(len(plugins.inventory))
        for row, plugin in enumerate(plugins.inventory):
            selected = self._values.get(plugin.id, plugin.builtin)
            item = QTableWidgetItem()
            flags = Qt.ItemFlag.ItemIsEnabled
            if not plugin.error:
                flags |= Qt.ItemFlag.ItemIsUserCheckable
            item.setFlags(flags)
            item.setCheckState(Qt.CheckState.Checked if selected else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, plugin.id)
            self._table.setItem(row, 0, item)
            for column, value in enumerate(
                (
                    f"{plugin.name} / {plugin.id}",
                    "内蔵" if plugin.builtin else "外部",
                    plugin.version,
                    plugin.kind,
                    plugin.status,
                    plugin.error,
                ),
                1,
            ):
                self._table.setItem(row, column, QTableWidgetItem(value))
        self._table.resizeColumnsToContents()
        self._table.itemChanged.connect(self._changed)

    def _changed(self, item: QTableWidgetItem) -> None:
        if item.column() == 0:
            self._values[item.data(Qt.ItemDataRole.UserRole)] = item.checkState() == Qt.CheckState.Checked
            pending = any(self._values.get(info.id, info.builtin) != info.enabled for info in self._plugins.inventory)
            self._restart.setText("変更は保存後、アプリの再起動で反映されます。" if pending else "")
            self.changed.emit()

    def read(self) -> tuple[tuple[str, bool], ...]:
        return tuple(sorted(self._values.items()))

"""Compose settings editors; persistence and background work belong to presenters."""

import os
from dataclasses import replace

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QCheckBox, QDialogButtonBox, QLineEdit, QMessageBox, QToolButton

from livevoicebridge.core.settings.models import AppConfig
from livevoicebridge.desktop.dictionary.view import DictionaryView
from livevoicebridge.desktop.forms import load_form
from livevoicebridge.desktop.rendering.icons import load_svg_icon
from livevoicebridge.desktop.resources import EXTERNAL_LINK_ICON_FILE
from livevoicebridge.desktop.settings.engines import EngineEditor, PluginEditor
from livevoicebridge.desktop.settings.presentation import PresentationEditor
from livevoicebridge.desktop.settings.read_blocks import PlaceholderFrame, ReadBlockEditor
from livevoicebridge.desktop.settings.resources import ResourceEditor
from livevoicebridge.plugins.manager import PluginManager


class SettingsDialog(QObject):
    settings_changed = Signal()
    save_requested = Signal()

    def __init__(self, config: AppConfig, catalog: list, executable_filter: str, plugins: PluginManager):
        super().__init__()
        self.config = config
        self.dialog_window = load_form("settings_dialog", widgets=(PlaceholderFrame,))
        window = self.dialog_window
        self.engines = EngineEditor(window, config.speech, executable_filter, plugins)
        self.plugins = PluginEditor(window, plugins, config.application.plugin_enabled)
        self.read_blocks = ReadBlockEditor(window, config.speech.read_blocks)
        self.dictionary = DictionaryView(window, config.dictionary)
        self.presentation = PresentationEditor(window, config.presentation, catalog)
        self.resources = ResourceEditor(window, config.resources)
        for component in (self.engines, self.plugins, self.read_blocks, self.presentation, self.resources):
            component.changed.connect(self.settings_changed.emit)
        self.dictionary.settings_changed.connect(self.settings_changed.emit)
        self.api_key_line = window.findChild(QLineEdit, "apiKeyLineEdit")
        self.api_key_line.setText(config.streaming.youtube_api_key or os.environ.get("YOUTUBE_API_KEY", ""))
        self.skip_history = window.findChild(QCheckBox, "skipHistoryCheckBox")
        self.read_paid_events = window.findChild(QCheckBox, "readSuperChatCheckBox")
        self.check_updates = window.findChild(QCheckBox, "checkUpdatesCheckBox")
        for widget, value in (
            (self.skip_history, config.streaming.skip_history),
            (self.read_paid_events, config.streaming.read_paid_events),
            (self.check_updates, config.application.check_updates),
        ):
            widget.setChecked(value)
            widget.stateChanged.connect(lambda _: self.settings_changed.emit())
        api_button = window.findChild(QToolButton, "apiKeyButton")
        api_button.setIcon(load_svg_icon(EXTERNAL_LINK_ICON_FILE, api_button))
        api_button.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl("https://console.cloud.google.com/apis/library/youtube.googleapis.com")
            )
        )
        buttons = window.findChild(QDialogButtonBox, "buttonBox")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(window.reject)

    def _accept(self) -> None:
        current = self.config
        try:
            speech = replace(self.engines.read(), read_blocks=self.read_blocks.read())
        except Exception as exc:
            QMessageBox.warning(self.dialog_window, "TTS設定", str(exc))
            return
        self.config = replace(
            current,
            streaming=replace(
                current.streaming,
                youtube_api_key=self.api_key_line.text().strip(),
                skip_history=self.skip_history.isChecked(),
                read_paid_events=self.read_paid_events.isChecked(),
            ),
            speech=speech,
            presentation=self.presentation.read(),
            dictionary=self.dictionary.read(),
            resources=self.resources.read(),
            application=replace(
                current.application, check_updates=self.check_updates.isChecked(), plugin_enabled=self.plugins.read()
            ),
        )
        self.save_requested.emit()

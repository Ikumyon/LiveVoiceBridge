"""Own asynchronous settings operations; the view only edits a draft."""

from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QDialog

from livevoicebridge.core.dictionary.models import DictionaryEntry
from livevoicebridge.core.session.service import SessionService
from livevoicebridge.desktop.settings.view import SettingsDialog


class SettingsPresenter(QObject):
    discovery_completed = Signal(object, object, str)
    import_completed = Signal(object, str)

    def __init__(self, view: SettingsDialog, session: SessionService):
        super().__init__(view)
        self._view = view
        self._session = session
        self._closed = False
        self.discovery_completed.connect(self._on_discovered)
        self.import_completed.connect(self._on_imported)
        view.speakers_requested.connect(self._discover)
        view.import_requested.connect(self._import)
        view.dialog_window.finished.connect(self._finish)

    def _discover(self, config):
        source = self._view._current_speaker_source()

        def complete(speakers, error):
            if not self._closed:
                self.discovery_completed.emit(source, speakers, error)

        self._session.discover(config, complete)

    def _on_discovered(self, source, speakers, error):
        if self._closed:
            return
        self._view.tts_test_button.setEnabled(True)
        if source == self._view._current_speaker_source():
            self._view.speakers_received.emit(speakers, error)

    def _import(self, filename):
        def complete(entries, error):
            if not self._closed:
                self.import_completed.emit(entries, error)

        self._session.import_dictionary(Path(filename), complete)

    def _on_imported(self, entries, error):
        if not self._closed:
            self._view.import_received.emit(entries, error)

    def _finish(self, result):
        self._closed = True
        if result == QDialog.DialogCode.Accepted:
            groups = {
                name: tuple(DictionaryEntry(row["word"], row["reading"], row["pos"], row["comment"]) for row in entries)
                for name, entries in self._view.word_dict.items()
            }
            self._session.apply_settings(self._view.config, groups)

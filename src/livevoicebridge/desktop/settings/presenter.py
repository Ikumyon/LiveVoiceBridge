"""Own asynchronous settings operations; plugin pages own their additional UI."""

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QDialog, QMessageBox

from livevoicebridge.core.session.service import SessionService
from livevoicebridge.desktop.dictionary.presenter import DictionaryPresenter
from livevoicebridge.desktop.settings.view import SettingsDialog


class SettingsPresenter(QObject):
    discovery_completed = Signal(object, object, str)
    save_completed = Signal(str)

    def __init__(self, view: SettingsDialog, session: SessionService):
        super().__init__(view)
        self._view, self._session, self._closed = view, session, False
        self.discovery_completed.connect(self._on_discovered)
        self.save_completed.connect(self._on_saved)
        view.engines.speakers_requested.connect(self._discover)
        self._dictionary = DictionaryPresenter(
            view.dictionary,
            session.dictionary.repository,
            session.dictionary.editor,
        )
        view.save_requested.connect(self._save)
        view.dialog_window.finished.connect(self._finish)

    def _discover(self, config):
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
            for engine in self._view.config.speech.engines:
                provider = self._session.plugins.providers.get(engine.engine_id)
                if provider is not None:
                    try:
                        provider.validate(engine)
                    except (ValueError, TypeError) as exc:
                        self._on_saved(str(exc))
                        return
            self._session.apply_settings(self._view.config, draft, self.save_completed.emit)

        self._dictionary.flush(flushed)

    def _on_saved(self, error):
        if self._closed:
            return
        self._view.dialog_window.setEnabled(True)
        if error:
            self._dictionary.resume()
            QMessageBox.critical(self._view.dialog_window, "保存エラー", error)
        else:
            self._view.dialog_window.accept()

    def _finish(self, result):
        self._closed = True
        self._dictionary.close(result == QDialog.DialogCode.Accepted)
        self._view.engines.close()

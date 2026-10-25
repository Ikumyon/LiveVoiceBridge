"""Asynchronous dictionary editing; only bounded blocks reach the GUI thread."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, QSignalBlocker, Signal
from PySide6.QtWidgets import QDialogButtonBox, QMessageBox

from livevoicebridge.core.dictionary.models import DictionaryEntry, DictionaryGroup
from livevoicebridge.core.dictionary.ports import DictionaryRepository
from livevoicebridge.desktop.dictionary.view import DictionaryView


class DictionaryPresenter(QObject):
    completed = Signal(object, object, str)

    def __init__(self, view: DictionaryView, repository: DictionaryRepository, worker: ThreadPoolExecutor):
        super().__init__(view)
        self.view = view
        self.repository = repository
        self.draft: int | None = None
        self._closed = False
        self._groups: tuple[DictionaryGroup, ...] = ()
        self._worker = worker
        self._page_busy = False
        self._pending_page: tuple[int, int, int] | None = None
        self._edit_last: tuple[int, int] | None = None
        self._write_error = ""
        self._busy = True
        self._saving = False
        self._revision = -1
        self.completed.connect(self._completed)
        view.dictionary_requested.connect(self._action)
        view.word_model.block_requested.connect(self._request_page)
        view.word_model.entry_changed.connect(self._edit)
        self._controls(False)
        self._begin_future = self._worker.submit(repository.begin)

        def begun(future):
            try:
                draft, error = future.result(), ""
            except Exception as exc:
                draft, error = None, str(exc)
            if not self._closed:
                self.completed.emit(self._begun, draft, error)

        self._begin_future.add_done_callback(begun)

    def _submit(self, operation: Callable, complete: Callable) -> None:
        if self._closed:
            return

        def work():
            try:
                result, error = operation(), ""
            except Exception as exc:
                result, error = None, str(exc)
            if not self._closed:
                self.completed.emit(complete, result, error)

        self._worker.submit(work)

    def _completed(self, callback, result, error):
        if not self._closed:
            callback(result, error)

    def _controls(self, enabled: bool) -> None:
        self._busy = not enabled
        self.view.word_model.set_editable(enabled)
        self.view.button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(enabled and not self._saving)
        for widget in (
            self.view.group_combo,
            self.view.add_word_button,
            self.view.delete_word_button,
            self.view.import_word_button,
            self.view.add_group_button,
            self.view.rename_group_button,
            self.view.delete_group_button,
        ):
            widget.setEnabled(enabled)

    def _error(self, error: str) -> None:
        QMessageBox.critical(self.view.dialog_window, "辞書", error)

    def _begun(self, draft, error):
        if error:
            self._write_error = error
            self._error(error)
            return
        self.draft = draft
        self._refresh()

    def _refresh(self, selected: int | None = None, edit_last: bool = False) -> None:
        draft = self.draft
        if draft is None:
            return
        self._controls(False)
        if selected is None:
            selected = self.view.group_combo.currentData()

        def received(groups, error):
            self._controls(True)
            if error:
                self._error(error)
                return
            self._groups = groups
            self._revision = groups[0].revision if groups else -1
            combo = self.view.group_combo
            name = self.view.current_active_group_name
            with QSignalBlocker(combo):
                combo.clear()
                for group in groups:
                    combo.addItem(group.name, group.id)
                index = combo.findData(selected) if selected is not None else combo.findText(name)
                combo.setCurrentIndex(max(0, index))
            self.view.current_active_group_name = combo.currentText()
            if self.view._dictionary_view_loaded:
                self._select(combo.currentData())
                if edit_last and self.view.word_model.rowCount():
                    row = self.view.word_model.rowCount() - 1
                    self.view.word_table.scrollTo(self.view.word_model.index(row, 0))
                    self._edit_last = (self.view.word_model.generation, row)
                    self.view.word_model.entry(row)

        self._submit(lambda: self.repository.groups(draft), received)

    def _select(self, group_id: int | None) -> None:
        group = next((g for g in self._groups if g.id == group_id), None)
        self._pending_page = None
        self.view.word_model.set_group(group.id if group else 0, group.count if group else 0)

    def _request_page(self, generation: int, group: int, block: int) -> None:
        if self._closed or self._saving or self.draft is None:
            return
        self._pending_page = generation, group, block
        self._pump_page()

    def _pump_page(self) -> None:
        if self._page_busy or self._pending_page is None or self.draft is None or self._closed or self._saving:
            return
        generation, group, block = self._pending_page
        self._pending_page = None
        self._page_busy = True
        draft = self.draft
        model = self.view.word_model
        if generation != model.generation or model.has_block(block):
            self._page_busy = False
            return

        def received(page, error):
            self._page_busy = False
            if generation == model.generation:
                if error:
                    self._error(error)
                elif page.revision != self._revision:
                    self._refresh(group)
                else:
                    model.receive(generation, group, block, page.entries)
                    pending_edit = self._edit_last
                    if pending_edit is not None and pending_edit[0] == generation:
                        row = pending_edit[1]
                        if block * model.BLOCK_SIZE <= row < (block + 1) * model.BLOCK_SIZE:
                            self._edit_last = None
                            self.view.word_table.edit(model.index(row, 0))
            self._pump_page()

        self._submit(lambda: self.repository.page(draft, group, block * model.BLOCK_SIZE, model.BLOCK_SIZE), received)

    def _edit(self, entry: DictionaryEntry) -> None:
        draft = self.draft
        if draft is None:
            return

        def edited(_result, error):
            if error:
                self._write_error = error
                self._error(error)
                self._refresh()
            else:
                self.view.settings_changed.emit()

        self._submit(lambda: self.repository.edit(draft, entry), edited)

    def _action(self, action: str, value) -> None:
        if action == "load":
            if (
                self.draft is not None
                and self._groups
                and self.view.word_model.group != self.view.group_combo.currentData()
            ):
                self._select(self.view.group_combo.currentData())
            return
        if action == "select":
            if self.view._dictionary_view_loaded:
                self._select(value)
            return
        if self._busy or self.draft is None:
            return
        draft = self.draft
        group = self.view.group_combo.currentData()
        if group is None:
            return
        self._controls(False)

        def mutate():
            if action == "append":
                return self.repository.append(draft, group)
            if action == "delete":
                return self.repository.edit(draft, value, True)
            if action == "import":
                return self.repository.import_file(draft, group, Path(value))
            if action == "add_group":
                return self.repository.add_group(draft, value)
            if action == "rename_group":
                return self.repository.edit_group(draft, group, value)
            if action == "delete_group":
                return self.repository.edit_group(draft, group)
            raise ValueError(f"未対応の辞書操作: {action}")

        def mutated(result, error):
            if error:
                self._controls(True)
                self._error(error)
                return
            self.view.settings_changed.emit()
            self._refresh(result if action == "add_group" else group, edit_last=action == "append")
            if action == "import":
                QMessageBox.information(
                    self.view.dialog_window, "インポート", f"{result}件を取り込みました。OKで反映します。"
                )

        self._submit(mutate, mutated)

    def flush(self, complete: Callable[[int | None, str], None]) -> None:
        self._saving = True
        self._pending_page = None

        # The single worker guarantees all pending cell edits precede this barrier.
        def flushed(_result, error):
            complete(self.draft, error or self._write_error)

        self._submit(lambda: None, flushed)

    def resume(self) -> None:
        self._saving = False
        self._controls(not self._busy)
        self.view.word_model.retry()
        self.view.word_table.viewport().update()

    def close(self, committed: bool) -> None:
        self._closed = True
        self._pending_page = None
        if not committed:

            def discard():
                try:
                    self.repository.discard(self._begin_future.result())
                except Exception:
                    # Failed begin has no draft. Abandoned drafts are cleared on next startup.
                    pass

            self._worker.submit(discard)

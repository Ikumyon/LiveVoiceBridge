from pathlib import Path
from threading import RLock

from livevoicebridge.core.dictionary.models import DictionaryEntry, DictionarySnapshot
from livevoicebridge.core.dictionary.ports import DictionaryGroups, DictionaryRepository
from livevoicebridge.core.speech.models import DictionaryCommand, SpeechAction


class DictionaryService:
    def __init__(self, repository: DictionaryRepository):
        self._repository = repository
        self._lock = RLock()
        self._groups = repository.load()
        self._revision = 0
        self._snapshot = DictionarySnapshot(0, tuple(entry for group in self._groups.values() for entry in group))

    def groups(self) -> DictionaryGroups:
        with self._lock:
            return dict(self._groups)

    def snapshot(self) -> DictionarySnapshot:
        with self._lock:
            return self._snapshot

    def replace(self, groups: DictionaryGroups) -> None:
        with self._lock:
            if tuple(groups.items()) == tuple(self._groups.items()):
                return
            if not groups or any(not name.strip() for name in groups):
                raise ValueError("辞書グループを指定してください。")
            if any(not entry.word.strip() or not entry.reading.strip() for group in groups.values() for entry in group):
                raise ValueError("辞書の単語と読みを指定してください。")
            self._repository.save(groups)
            self._groups = dict(groups)
            self._revision += 1
            self._snapshot = DictionarySnapshot(
                self._revision, tuple(entry for group in self._groups.values() for entry in group)
            )

    def execute(self, command: DictionaryCommand) -> None:
        with self._lock:
            groups = dict(self._groups)
            entries = tuple(entry for entry in groups.get("配信コメント", ()) if entry.word != command.word)
            if command.action is SpeechAction.ADD_DICTIONARY:
                entries += (DictionaryEntry(command.word, command.reading, comment="コメント追加"),)
            groups["配信コメント"] = entries
            self.replace(groups)

    def import_file(self, path: Path) -> tuple[DictionaryEntry, ...]:
        return self._repository.import_file(path)

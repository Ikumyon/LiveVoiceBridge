from concurrent.futures import ThreadPoolExecutor

from livevoicebridge.core.dictionary.models import DictionarySnapshot
from livevoicebridge.core.dictionary.ports import DictionaryRepository
from livevoicebridge.core.speech.models import DictionaryCommand, SpeechAction


class DictionaryService:
    def __init__(self, repository: DictionaryRepository):
        self.repository = repository
        self.editor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dictionary-editor")

    def close(self) -> None:
        self.editor.shutdown(wait=True)

    def snapshot(self) -> DictionarySnapshot:
        return self.repository.snapshot()

    def execute(self, command: DictionaryCommand) -> None:
        reading = command.reading if command.action is SpeechAction.ADD_DICTIONARY else None
        self.repository.educate(command.word, reading)

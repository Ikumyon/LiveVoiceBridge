"""One synthesis lane feeds one ordered playback lane, without Qt."""

from collections.abc import Callable
from dataclasses import dataclass, fields, replace
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread

from livevoicebridge.core.speech.budget import AudioBudget
from livevoicebridge.core.speech.models import (
    AudioData,
    DictionaryCommand,
    EngineConfig,
    SoundEffect,
    SpeechPlan,
    SpeechProgress,
    Utterance,
    capabilities,
)
from livevoicebridge.core.speech.ports import (
    AudioOutput,
    AudioSynthesizer,
    ExternalSpeechOutput,
    SpeechDictionary,
    TextProcessor,
)


@dataclass(frozen=True, slots=True)
class _Playback:
    utterance: Utterance
    audio: AudioData


class SpeechPipeline:
    def __init__(
        self,
        session: int,
        revision: int,
        config: EngineConfig,
        engine: AudioSynthesizer | ExternalSpeechOutput,
        processor: TextProcessor,
        dictionary: SpeechDictionary,
        audio: AudioOutput,
        on_progress: Callable[[SpeechProgress], None],
        on_error: Callable[[str], None],
        limit: int = 100,
        audio_mib: int = 32,
        ready: Callable[[Event], object] | None = None,
    ):
        self.session = session
        self.revision = revision
        self._config = config
        self._engine = engine
        self._ready = ready
        self._processor = processor
        self._dictionary = dictionary
        self._audio = audio
        self._on_progress = on_progress
        self._on_error = on_error
        self._input: Queue[SpeechPlan] = Queue(limit)
        self._output: Queue[_Playback | SoundEffect | None] = Queue(limit)
        self._cancelled = Event()
        self._finished = Event()
        self._admission = Lock()
        self._accepting = True
        self._rejected = 0
        self._progress_lock = Lock()
        self._current_text = ""
        self._budget = AudioBudget(audio_mib * 1024 * 1024, self._cancelled)
        self._playback = Thread(target=self._play, name=f"playback-{session}")
        self._generation = Thread(target=self._generate, name=f"synthesis-{session}")

    def start(self) -> None:
        self._playback.start()
        self._generation.start()

    def set_revision(self, revision: int) -> None:
        self.revision = revision

    @property
    def accepting(self) -> bool:
        return self._accepting

    def set_audio_limit(self, mib: int) -> None:
        self._budget.set_limit(mib * 1024 * 1024)

    def submit(self, plan: SpeechPlan) -> bool:
        with self._admission:
            if not self._accepting:
                return False
            try:
                self._input.put_nowait(plan)
            except Full:
                self._rejected += 1
                self._notify()
                return False
        self._notify()
        return True

    def cancel(self) -> None:
        with self._admission:
            self._accepting = False
            self._cancelled.set()
        self._budget.wake()
        self._discard(self._input)
        self._discard(self._output)

    def join(self, timeout: float | None = None) -> bool:
        return self._finished.wait(timeout)

    def _discard(self, queue: Queue) -> None:
        while True:
            try:
                item = queue.get_nowait()
                if isinstance(item, _Playback):
                    self._budget.release(item.audio.byte_length)
            except Empty:
                return

    def _notify(self, text: str | None = None) -> None:
        with self._progress_lock:
            if text is not None:
                self._current_text = text
            current = self._current_text
        self._on_progress(
            SpeechProgress(
                self.session,
                self.revision,
                self._input.qsize(),
                current,
                self._rejected,
                not capabilities(self._config.kind).local_audio,
            )
        )

    def _enqueue(self, value: _Playback | SoundEffect | None) -> bool:
        while not self._cancelled.is_set():
            try:
                self._output.put(value, timeout=0.05)
                self._notify()
                return True
            except Full:
                continue
        return False

    def _supported(self, utterance: Utterance) -> Utterance:
        supported = capabilities(self._config.kind).controls
        ignored = {
            item.name: None
            for item in fields(utterance.controls)
            if getattr(utterance.controls, item.name) is not None and item.name not in supported
        }
        if ignored:
            self._on_error(f"未対応のコメント制御を省略しました: {', '.join(ignored)}")
        return replace(utterance, controls=replace(utterance.controls, **ignored))

    def _generate(self) -> None:
        audio: AudioData | None = None
        try:
            if self._ready is not None:
                try:
                    self._ready(self._cancelled)
                except Exception as exc:
                    if not self._cancelled.is_set():
                        self._on_error(str(exc))
                    self.cancel()
                    return
            while not self._cancelled.is_set():
                try:
                    plan = self._input.get(timeout=0.05)
                except Empty:
                    continue
                for item in plan.items:
                    if self._cancelled.is_set():
                        break
                    try:
                        if isinstance(item, DictionaryCommand):
                            self._dictionary.execute(item)
                        elif isinstance(item, SoundEffect):
                            self._enqueue(item)
                        else:
                            utterance = self._supported(item)
                            text = self._processor.prepare(utterance.text, self._dictionary.snapshot())
                            if not text.strip():
                                continue
                            if capabilities(self._config.kind).local_audio:
                                assert hasattr(self._engine, "synthesize")
                                reserved = self._budget.reserve()
                                if not reserved:
                                    break
                                try:
                                    audio = self._engine.synthesize(text, utterance.controls, self._config, reserved)
                                    if audio.byte_length > reserved:
                                        raise ValueError("合成音声が1音声の容量上限を超えました。")
                                    self._budget.release(reserved - audio.byte_length)
                                    reserved = audio.byte_length
                                    if self._enqueue(_Playback(utterance, audio)):
                                        reserved = 0
                                finally:
                                    audio = None
                                    if reserved:
                                        self._budget.release(reserved)
                            else:
                                assert hasattr(self._engine, "send")
                                self._notify(utterance.text)
                                try:
                                    self._engine.send(text, utterance.controls, self._config)
                                finally:
                                    self._notify("")
                    except Exception as exc:
                        self._on_error(str(exc))
        finally:
            self._enqueue(None)
            self._playback.join()
            self._notify("")
            self._finished.set()

    def _play(self) -> None:
        while not self._cancelled.is_set():
            try:
                item = self._output.get(timeout=0.05)
            except Empty:
                continue
            if item is None:
                return
            try:
                if self._cancelled.is_set():
                    return
                if isinstance(item, SoundEffect):
                    self._audio.sound(item.filename, item.overlap)
                else:
                    self._notify(item.utterance.text)
                    self._audio.play(item.audio, item.utterance.controls)
            except Exception as exc:
                self._on_error(str(exc))
            finally:
                if isinstance(item, _Playback):
                    self._budget.release(item.audio.byte_length)
                item = None
                self._notify("")

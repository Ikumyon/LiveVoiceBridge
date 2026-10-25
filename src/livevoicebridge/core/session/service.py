"""Serialize lifecycle and settings commands; workers never own session state."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from queue import Empty, Queue
from threading import BoundedSemaphore, Event, Lock, Thread

from livevoicebridge.core.chat.models import CommentEvent
from livevoicebridge.core.chat.planning import plan_comment
from livevoicebridge.core.chat.ports import StreamingSource
from livevoicebridge.core.dictionary.service import DictionaryService
from livevoicebridge.core.session.models import (
    ApplicationEvent,
    CommentReceived,
    LogMessage,
    MetricsCollected,
    RuntimeState,
    SessionChanged,
    SettingsApplied,
    ShutdownCompleted,
    UpdateAvailable,
)
from livevoicebridge.core.settings.models import AppConfig, PresentationConfig
from livevoicebridge.core.settings.service import SettingsService, validate
from livevoicebridge.core.speech.models import EngineConfig, Qwen3Config, Speaker, SpeechProgress, TtsEngineKind
from livevoicebridge.core.speech.pipeline import SpeechPipeline
from livevoicebridge.core.speech.ports import (
    AudioOutput,
    AudioSynthesizer,
    EngineFactory,
    ExternalSpeechOutput,
    TextProcessor,
)
from livevoicebridge.core.speech.qwen import QwenRuntime, QwenState
from livevoicebridge.core.telemetry.models import ApplicationIssue, ErrorKind
from livevoicebridge.core.telemetry.ports import MetricsProvider, UpdateProvider
from livevoicebridge.core.telemetry.store import MetricsStore


class SessionService:
    def __init__(
        self,
        settings: SettingsService,
        dictionary: DictionaryService,
        engine_factory: EngineFactory,
        source_factory: Callable[[], StreamingSource],
        audio: AudioOutput,
        processor: TextProcessor,
        metrics: MetricsProvider,
        updates: UpdateProvider,
        publish: Callable[[ApplicationEvent], None],
        avatar_loader: Callable[[str], bytes],
        qwen: QwenRuntime | None = None,
    ):
        self.settings = settings
        self.dictionary = dictionary
        self._engine_factory = engine_factory
        self._source_factory = source_factory
        self._audio = audio
        self._processor = processor
        self._metrics = metrics
        self.metrics_store = MetricsStore()
        self._updates = updates
        self._publish = publish
        self._avatar_loader = avatar_loader
        self.qwen = qwen
        self._auxiliary = ThreadPoolExecutor(max_workers=2, thread_name_prefix="desktop-data")
        self._media = ThreadPoolExecutor(max_workers=2, thread_name_prefix="avatars")
        self._avatar_slots = BoundedSemaphore(64)
        self._comment_slots = BoundedSemaphore(1000)
        self._commands: Queue[Callable[[], None] | None] = Queue()
        self._lock = Lock()
        self._intent = 0
        self._session = 0
        self._closing = False
        self._shutdown = Event()
        self._state = RuntimeState.IDLE
        self._connected = False
        self._source: StreamingSource | None = None
        self._engine: AudioSynthesizer | ExternalSpeechOutput | None = None
        self._pipeline: SpeechPipeline | None = None
        self._control = Thread(target=self._run, name="session-control")
        self._monitor = Thread(target=self._observe, name="system-metrics")
        self._control.start()
        self._monitor.start()

    def initialize_qwen(self) -> None:
        if self.qwen is not None:
            config = self.settings.current.speech.engine()
            self.qwen.configure(config if isinstance(config, Qwen3Config) else None)

    def qwen_prepared(self, model: str, device: str, generation: int) -> None:
        def apply() -> None:
            if self.qwen is None or self.qwen.state.generation != generation:
                return
            config = self.settings.current
            engines = tuple(
                replace(engine, model_path=model, device=device) if isinstance(engine, Qwen3Config) else engine
                for engine in config.speech.engines
            )
            self._apply(replace(config, speech=replace(config.speech, engines=engines)), None)

        self._post(apply)

    def qwen_changed(self, state: QwenState) -> None:
        self._post(lambda: self._qwen_changed(state))

    def restart_qwen(self) -> None:
        def restart() -> None:
            if self.qwen is None:
                return
            if self._pipeline is not None and self.settings.current.speech.active_engine is TtsEngineKind.QWEN3:
                self._pipeline.cancel()
            self.qwen.restart()

        self._post(restart)

    def _qwen_changed(self, state: QwenState) -> None:
        if self.qwen is None or state.generation != self.qwen.state.generation:
            return
        if self.settings.current.speech.active_engine is not TtsEngineKind.QWEN3:
            return
        if state.phase == "error" and self._pipeline is not None:
            self._pipeline.cancel()
        elif state.busy and self._pipeline is not None:
            self._pipeline.cancel()
        elif state.phase == "ready" and self._pipeline is not None and not self._pipeline.accepting:
            self._pipeline.join()
            self._pipeline = None
            if self._engine is not None:
                self._engine.close()
            if self._prepare(self._session):
                self._set_state(RuntimeState.RUNNING)

    @property
    def state(self) -> RuntimeState:
        with self._lock:
            return self._state

    def _next_intent(self) -> int:
        with self._lock:
            self._intent += 1
            return self._intent

    def _current(self, token: int) -> bool:
        with self._lock:
            return token == self._intent and not self._closing

    def _post(self, action: Callable[[], None]) -> None:
        with self._lock:
            if not self._closing:
                self._commands.put(action)

    def _set_state(self, state: RuntimeState) -> None:
        with self._lock:
            self._state = state
        self.metrics_store.set_connections(int(self._connected and state is RuntimeState.RUNNING))
        self._publish(SessionChanged(state, self._connected and state is RuntimeState.RUNNING))

    def _issue(self, message: str) -> None:
        self._publish(ApplicationIssue(ErrorKind.RECOVERABLE, "operation_failed", message))

    def _run(self) -> None:
        while True:
            action = self._commands.get()
            if action is None:
                return
            try:
                action()
            except Exception as exc:
                self._issue(str(exc))
                try:
                    self._dispose()
                except Exception as cleanup:
                    self._issue(str(cleanup))
                self._set_state(RuntimeState.ERROR)

    def start(self, source: str) -> None:
        token = self._next_intent()
        self._post(lambda: self._start(token, source))

    def _start(self, token: int, source: str) -> None:
        self._dispose()
        if not self._current(token):
            return
        config = self.settings.current
        if source.strip():
            config = replace(config, streaming=replace(config.streaming, youtube_source=source.strip()))
            self.settings.apply(config)
        if not config.streaming.youtube_source or not config.streaming.youtube_api_key:
            raise ValueError("YouTubeのURLとAPIキーを設定してください。")
        if not self._prepare(token):
            return
        self._source = self._source_factory()
        self._source.start(
            config.streaming,
            lambda event: self._queue_comment(token, event),
            lambda text: self._publish(LogMessage(text)) if self._current(token) else None,
            lambda text: self._post(lambda: self._source_failed(token, text)),
            lambda: self._post(lambda: self._source_closed(token)),
            lambda connected: self._post(lambda: self._connection_changed(token, connected)),
        )

    def _connection_changed(self, token: int, connected: bool) -> None:
        if self._current(token) and self._source is not None and self._connected != connected:
            self._connected = connected
            self._set_state(RuntimeState.RUNNING if connected else RuntimeState.STARTING)

    def _prepare(self, token: int) -> bool:
        self._set_state(RuntimeState.STARTING)
        self._session = token
        config = self.settings.current
        self._engine = self._engine_factory(config.speech.engine())
        if not isinstance(config.speech.engine(), Qwen3Config):
            self._engine.ensure_ready()
        if not self._current(token):
            self._dispose()
            self._set_state(RuntimeState.IDLE)
            return False
        self._pipeline = SpeechPipeline(
            token,
            self.settings.revision,
            config.speech.engine(),
            self._engine,
            self._processor,
            self.dictionary,
            self._audio,
            self._progress,
            self._issue,
            config.speech.queue_limit,
            config.resources.audio_mib,
            self.qwen.wait_ready if isinstance(config.speech.engine(), Qwen3Config) and self.qwen else None,
        )
        self._pipeline.start()
        return True

    def is_current_progress(self, progress: SpeechProgress) -> bool:
        return self._current(progress.session) and progress.revision == self.settings.revision

    def _progress(self, progress: SpeechProgress) -> None:
        if self.is_current_progress(progress):
            self._publish(progress)

    def test_comment(self, text: str) -> None:
        self._post(lambda: self._test(text))

    def _test(self, text: str) -> None:
        if self._pipeline is None:
            token = self._next_intent()
            if not self._prepare(token):
                return
            self._set_state(RuntimeState.RUNNING)
        self._receive(self._session, CommentEvent("テスト", text))

    def _queue_comment(self, token: int, event: CommentEvent) -> None:
        if not self._current(token):
            return
        if not self._comment_slots.acquire(blocking=False):
            self._publish(CommentReceived(event))
            self._issue("コメント処理待ちの上限に達したため読み上げを省略しました。")
            return

        def consume() -> None:
            try:
                self._receive(token, event)
            finally:
                self._comment_slots.release()

        self._post(consume)

    def _receive(self, token: int, event: CommentEvent) -> None:
        if not self._current(token):
            return
        self._publish(CommentReceived(event))
        config = self.settings.current
        plan = plan_comment(event, config.streaming, config.speech, self._processor)
        if plan is not None and self._pipeline is not None:
            if self._pipeline.accepting and not self._pipeline.submit(plan):
                self._issue("読み上げキューが満杯です。このコメントの読み上げを省略しました。")

    def _source_failed(self, token: int, message: str) -> None:
        if self._current(token):
            self._issue(message)
            self._dispose()
            self._set_state(RuntimeState.ERROR)

    def _source_closed(self, token: int) -> None:
        if self._current(token) and self._source is not None:
            self._dispose()
            self._set_state(RuntimeState.IDLE)

    def stop(self) -> None:
        self._next_intent()
        pipeline = self._pipeline
        if pipeline is not None:
            pipeline.cancel()
        self._post(self._stop)

    def _stop(self) -> None:
        self._set_state(RuntimeState.STOPPING)
        self._dispose()
        self._set_state(RuntimeState.IDLE)

    def _dispose(self) -> None:
        self._connected = False
        errors: list[str] = []
        source, self._source = self._source, None
        if source is not None:
            try:
                source.close()
            except Exception as exc:
                errors.append(str(exc))
        pipeline, self._pipeline = self._pipeline, None
        if pipeline is not None:
            pipeline.cancel()
            pipeline.join()
        engine, self._engine = self._engine, None
        if engine is not None:
            try:
                engine.close()
            except Exception as exc:
                errors.append(str(exc))
        if errors:
            raise RuntimeError(" / ".join(errors))

    def apply_settings(
        self,
        config: AppConfig,
        dictionary_draft: int | None = None,
        qwen_base: Qwen3Config | None = None,
        complete: Callable[[str], None] | None = None,
    ) -> None:
        def apply() -> None:
            draft = config
            # Provisioning saves independently of the settings draft. Merge on the
            # serialized command lane so an immediately closed dialog cannot undo it.
            latest = self.settings.current.speech.engine(TtsEngineKind.QWEN3)
            if qwen_base is not None and isinstance(latest, Qwen3Config):
                engines = tuple(
                    replace(
                        engine,
                        model_path=latest.model_path,
                        device=latest.device if engine.device == qwen_base.device else engine.device,
                    )
                    if isinstance(engine, Qwen3Config)
                    else engine
                    for engine in draft.speech.engines
                )
                draft = replace(draft, speech=replace(draft.speech, engines=engines))
            try:
                error = self._apply(draft, dictionary_draft)
            except Exception as exc:
                error = str(exc)
                self._issue(error)
            if complete is not None:
                complete(error)

        self._post(apply)

    def _apply(self, config: AppConfig, dictionary_draft: int | None) -> str:
        previous = self.settings.current
        try:
            validate(config)
            self.settings.apply(config)
        except Exception as exc:
            self._issue(str(exc))
            return str(exc)
        error = ""
        if dictionary_draft is not None:
            try:
                self.dictionary.repository.commit(dictionary_draft)
            except Exception as exc:
                error = f"設定は保存しましたが辞書の保存に失敗しました: {exc}"
                self._issue(error)
        try:
            self._apply_runtime(previous, config)
        except Exception as exc:
            self._issue(f"設定は保存しましたが実行状態の更新に失敗しました: {exc}")
        return error

    def _apply_runtime(self, previous: AppConfig, config: AppConfig) -> None:
        self._publish(SettingsApplied(config, self.settings.revision))
        self.initialize_qwen()
        if self._pipeline is not None:
            self._pipeline.set_audio_limit(config.resources.audio_mib)
        speech_changed = (
            previous.speech.active_engine != config.speech.active_engine
            or previous.speech.engine() != config.speech.engine()
            or previous.speech.read_blocks != config.speech.read_blocks
            or previous.speech.queue_limit != config.speech.queue_limit
        )
        if not speech_changed and previous.streaming == config.streaming:
            if self._pipeline is not None:
                self._pipeline.set_revision(self.settings.revision)
            return
        was_running = self._pipeline is not None
        was_connected = self._source is not None
        self._dispose()
        if was_running:
            token = self._next_intent()
            if was_connected:
                self._start(token, config.streaming.youtube_source)
            elif self._prepare(token):
                self._set_state(RuntimeState.RUNNING)

    def discover(self, config: EngineConfig, complete: Callable[[tuple[Speaker, ...], str], None]) -> None:
        with self._lock:
            if not self._closing:
                self._auxiliary.submit(self._discover, config, complete)

    def apply_presentation(self, presentation: PresentationConfig) -> None:
        def apply() -> None:
            self._apply(replace(self.settings.current, presentation=presentation), None)

        self._post(apply)

    def request_avatar(self, url: str, complete: Callable[[str, bytes], None]) -> None:
        def fetch() -> None:
            try:
                try:
                    content = self._avatar_loader(url)
                except Exception:
                    content = b""
                if not self._closing:
                    complete(url, content)
            finally:
                self._avatar_slots.release()

        with self._lock:
            if not self._closing:
                if not self._avatar_slots.acquire(blocking=False):
                    complete(url, b"")
                    return
                self._media.submit(fetch)

    def _discover(self, config: EngineConfig, complete: Callable[[tuple[Speaker, ...], str], None]) -> None:
        engine = None
        try:
            engine = self._engine_factory(config)
            complete(engine.speakers(), "")
        except Exception as exc:
            complete((), str(exc))
        finally:
            if engine is not None:
                try:
                    engine.close()
                except Exception as exc:
                    self._issue(str(exc))

    def check_updates(self) -> None:
        def check() -> None:
            try:
                version = self._updates.latest()
                if version and not self._closing:
                    self._publish(UpdateAvailable(version))
            except Exception as exc:
                if not self._closing:
                    self._publish(LogMessage(f"更新確認に失敗しました: {exc}"))

        with self._lock:
            if not self._closing:
                self._auxiliary.submit(check)

    def _observe(self) -> None:
        while not self._shutdown.is_set():
            try:
                for message in self._audio.drain_errors():
                    self._publish(LogMessage(message))
                self.metrics_store.record(self._metrics.collect())
                self._publish(MetricsCollected())
            except Exception as exc:
                self._publish(LogMessage(f"メトリクス取得失敗: {exc}"))
            self._shutdown.wait(1)

    def shutdown(self) -> None:
        with self._lock:
            if self._closing:
                return
            self._closing = True
            self._intent += 1
        self._shutdown.set()
        while True:
            try:
                self._commands.get_nowait()
            except Empty:
                break
        if self._pipeline is not None:
            self._pipeline.cancel()
        self._commands.put(self._shutdown_resources)

    def _shutdown_resources(self) -> None:
        try:
            for close in (*([self.qwen.close] if self.qwen else []), self._dispose, self._audio.close):
                try:
                    close()
                except Exception as exc:
                    self._issue(str(exc))
            self._auxiliary.shutdown(wait=True, cancel_futures=True)
            self._media.shutdown(wait=True, cancel_futures=True)
            self.dictionary.close()
            self._monitor.join()
            self._metrics.close()
        finally:
            self._publish(ShutdownCompleted())
            self._commands.put(None)

    def join(self, timeout: float = 10) -> bool:
        self._control.join(timeout)
        return not self._control.is_alive()

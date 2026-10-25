"""The only module allowed to connect desktop and concrete integrations."""

from importlib.metadata import version

from livevoicebridge.core.dictionary.service import DictionaryService
from livevoicebridge.core.session.service import SessionService
from livevoicebridge.core.settings.service import SettingsService
from livevoicebridge.core.speech.models import BouyomiConfig, CoeiroinkConfig, EngineConfig, Qwen3Config, VoicevoxConfig
from livevoicebridge.core.speech.ports import AudioSynthesizer, ExternalSpeechOutput
from livevoicebridge.core.speech.qwen import QwenState
from livevoicebridge.desktop.events import DesktopEvents
from livevoicebridge.desktop.shell.presenter import ShellPresenter
from livevoicebridge.desktop.shell.view import ShellView
from livevoicebridge.host.paths import AppPaths
from livevoicebridge.integrations.audio.output import SystemAudioOutput
from livevoicebridge.integrations.native.metrics import NativeMetricsProvider
from livevoicebridge.integrations.native.text import NativeTextProcessor
from livevoicebridge.integrations.qwen.runtime import QwenManager
from livevoicebridge.integrations.storage.config import JsonConfigRepository
from livevoicebridge.integrations.storage.dictionary import SqliteDictionaryRepository
from livevoicebridge.integrations.tts.bouyomichan import BouyomiChanEngine
from livevoicebridge.integrations.tts.coeiroink import CoeiroinkEngine
from livevoicebridge.integrations.tts.qwen3 import Qwen3Engine
from livevoicebridge.integrations.tts.voicevox import VoicevoxEngine
from livevoicebridge.integrations.updates.github import GitHubUpdateProvider
from livevoicebridge.integrations.youtube.avatars import load_avatar
from livevoicebridge.integrations.youtube.source import YouTubeSource


def create_engine(config: EngineConfig) -> AudioSynthesizer | ExternalSpeechOutput:
    if isinstance(config, CoeiroinkConfig):
        return CoeiroinkEngine(config)
    if isinstance(config, VoicevoxConfig):
        return VoicevoxEngine(config)
    if isinstance(config, BouyomiConfig):
        return BouyomiChanEngine(config)
    raise ValueError("Qwenのエンジン生成にはアプリ所有の管理サービスが必要です。")


def compose(paths: AppPaths) -> ShellPresenter:
    settings = SettingsService(JsonConfigRepository(paths.config))
    dictionary = DictionaryService(SqliteDictionaryRepository(paths.dictionary))
    view = ShellView()
    events = DesktopEvents()

    def qwen_changed(state: QwenState) -> None:
        events.publish(state)
        session.qwen_changed(state)

    qwen = QwenManager(
        paths.root,
        paths.qwen_assets,
        paths.qwen_service,
        qwen_changed,
        lambda model, device, generation: session.qwen_prepared(model, device, generation),
    )

    def engine_factory(config: EngineConfig) -> AudioSynthesizer | ExternalSpeechOutput:
        return Qwen3Engine(qwen) if isinstance(config, Qwen3Config) else create_engine(config)

    session = SessionService(
        settings,
        dictionary,
        engine_factory,
        YouTubeSource,
        SystemAudioOutput(paths.sounds),
        NativeTextProcessor(),
        NativeMetricsProvider(),
        GitHubUpdateProvider(version("livevoicebridge")),
        events.publish,
        load_avatar,
        qwen,
    )
    presenter = ShellPresenter(view, session, events, paths.executable_filter)
    session.initialize_qwen()
    return presenter

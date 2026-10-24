"""The only module allowed to connect desktop and concrete integrations."""

from livevoicebridge.core.dictionary.service import DictionaryService
from livevoicebridge.core.session.service import SessionService
from livevoicebridge.core.settings.service import SettingsService
from livevoicebridge.core.speech.models import EngineConfig, TtsEngineKind
from livevoicebridge.core.speech.ports import AudioSynthesizer, ExternalSpeechOutput
from livevoicebridge.desktop.events import DesktopEvents
from livevoicebridge.desktop.shell.presenter import ShellPresenter
from livevoicebridge.desktop.shell.view import ShellView
from livevoicebridge.host.paths import AppPaths
from livevoicebridge.integrations.audio.output import SystemAudioOutput
from livevoicebridge.integrations.native.metrics import NativeMetricsProvider
from livevoicebridge.integrations.native.text import NativeTextProcessor
from livevoicebridge.integrations.storage.config import JsonConfigRepository
from livevoicebridge.integrations.storage.dictionary import JsonDictionaryRepository
from livevoicebridge.integrations.tts.bouyomichan import BouyomiChanEngine
from livevoicebridge.integrations.tts.coeiroink import CoeiroinkEngine
from livevoicebridge.integrations.tts.qwen3 import Qwen3Engine
from livevoicebridge.integrations.tts.voicevox import VoicevoxEngine
from livevoicebridge.integrations.updates.github import GitHubUpdateProvider
from livevoicebridge.integrations.youtube.avatars import load_avatar
from livevoicebridge.integrations.youtube.source import YouTubeSource

VERSION = "0.99.2"


def create_engine(config: EngineConfig) -> AudioSynthesizer | ExternalSpeechOutput:
    if config.kind is TtsEngineKind.VOICEVOX:
        return VoicevoxEngine(config)
    if config.kind is TtsEngineKind.COEIROINK:
        return CoeiroinkEngine(config)
    if config.kind is TtsEngineKind.QWEN3:
        return Qwen3Engine(config)
    return BouyomiChanEngine(config)


def compose(paths: AppPaths) -> ShellPresenter:
    settings = SettingsService(JsonConfigRepository(paths.config))
    dictionary = DictionaryService(JsonDictionaryRepository(paths.dictionary))
    view = ShellView()
    events = DesktopEvents()
    session = SessionService(
        settings,
        dictionary,
        create_engine,
        YouTubeSource,
        SystemAudioOutput(paths.sounds),
        NativeTextProcessor(),
        NativeMetricsProvider(),
        GitHubUpdateProvider(VERSION),
        events.publish,
        load_avatar,
    )
    return ShellPresenter(view, session, events, paths.executable_filter)

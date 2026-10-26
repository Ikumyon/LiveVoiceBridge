"""The composition root connects desktop, plugins, and concrete integrations."""

from importlib.metadata import version

from livevoicebridge.core.dictionary.service import DictionaryService
from livevoicebridge.core.session.models import LogMessage
from livevoicebridge.core.session.service import SessionService
from livevoicebridge.core.settings.service import SettingsService
from livevoicebridge.desktop.events import DesktopEvents
from livevoicebridge.desktop.shell.presenter import ShellPresenter
from livevoicebridge.desktop.shell.view import ShellView
from livevoicebridge.host.paths import AppPaths
from livevoicebridge.integrations.audio.output import SystemAudioOutput
from livevoicebridge.integrations.native.metrics import NativeMetricsProvider
from livevoicebridge.integrations.native.text import NativeTextProcessor
from livevoicebridge.integrations.storage.config import JsonConfigRepository
from livevoicebridge.integrations.storage.dictionary import SqliteDictionaryRepository
from livevoicebridge.integrations.updates.github import GitHubUpdateProvider
from livevoicebridge.integrations.youtube.avatars import load_avatar
from livevoicebridge.integrations.youtube.source import YouTubeSource
from livevoicebridge.plugins.manager import PluginManager


def compose(paths: AppPaths) -> ShellPresenter:
    settings = SettingsService(JsonConfigRepository(paths.config))
    plugins = PluginManager(paths.root)
    settings.apply(plugins.load(settings.current))
    dictionary = DictionaryService(SqliteDictionaryRepository(paths.dictionary))
    view = ShellView()
    events = DesktopEvents()
    session = SessionService(
        settings,
        dictionary,
        plugins.create,
        YouTubeSource,
        SystemAudioOutput(paths.sounds),
        NativeTextProcessor(),
        NativeMetricsProvider(),
        GitHubUpdateProvider(version("livevoicebridge")),
        events.publish,
        load_avatar,
        plugins,
    )
    plugins.bind(
        session._post,
        session.save_plugin_config,
        lambda message: events.publish(LogMessage(message)),
        session.engine_changed,
    )
    presenter = ShellPresenter(view, session, events, paths.executable_filter)
    session.initialize_plugins()
    return presenter

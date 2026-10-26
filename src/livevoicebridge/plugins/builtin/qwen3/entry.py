from pathlib import Path
from threading import Event

from livevoicebridge.integrations.qwen.runtime import QwenManager
from livevoicebridge.plugins.api import PluginContext
from livevoicebridge.plugins.builtin.qwen3.contracts import QwenConfig
from livevoicebridge.plugins.contracts import EngineCapabilities, EngineConfig, EngineState, SettingField
from livevoicebridge.plugins.provider import Provider

from .engine import Qwen3Engine


class QwenProvider(Provider):
    def __init__(self, context: PluginContext):
        super().__init__(
            "qwen3",
            "Qwen3",
            EngineCapabilities(frozenset({"speaker_id", "volume", "echo", "yamabiko", "panning"}), True, True),
            (
                SettingField("model_path", "モデル", "directory"),
                SettingField("device", "実行デバイス", "choice", "GPU", choices=("GPU", "CPU")),
                SettingField("volume", "音量", "number", 1.0, 0.0, 2.0),
            ),
            lambda config: Qwen3Engine(self.runtime),
        )
        package = Path(__file__).resolve().parents[3]
        assets = package / "integrations/qwen/resources"
        source_service = context.root.parents[4] / "services/qwen3"
        service = assets / "service" if (assets / "service").exists() else source_service
        self.runtime = QwenManager(
            context.data.parents[2],
            assets,
            service,
            lambda state: context.publish_state(
                EngineState(
                    context.id,
                    state.phase,
                    state.message,
                    state.generation,
                    state.busy,
                )
            ),
            lambda model, device, generation: self._prepared(context, model, device, generation),
        )
        self._current: EngineConfig | None = None
        context.settings_page = self.page

    def _prepared(self, context: PluginContext, model: str, device: str, generation: int) -> None:
        if self.runtime.state.generation == generation:
            context.save_config({"model_path": model, "device": device}, generation)

    def validate(self, config: EngineConfig) -> None:
        super().validate(config)
        if not 0 <= int(config.speaker_id) <= 8:
            raise ValueError("Qwen3の話者IDが範囲外です。")

    def configure(self, config: EngineConfig | None) -> None:
        self._current = config
        self.runtime.configure(
            QwenConfig(str(config.settings["model_path"]), str(config.settings["device"])) if config else None
        )

    def wait_ready(self, cancelled: Event) -> object:
        return self.runtime.wait_ready(cancelled)

    def page(self, parent, read_config):
        from .settings import QwenPage

        return QwenPage(self, parent, read_config)

    def close(self) -> None:
        self.runtime.close()


def register(context: PluginContext) -> None:
    context.register(QwenProvider(context))

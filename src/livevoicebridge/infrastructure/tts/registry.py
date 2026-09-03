"""Typed access to the supported Python TTS engine implementations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import livevoicebridge.infrastructure.tts.factory as engine_factory
from livevoicebridge.application.models import EngineConfig, TtsEngineKind
from livevoicebridge.infrastructure.tts.base import BaseTTSEngine
from livevoicebridge.infrastructure.tts.runtime import ensure_tts_running


def backend_config(config: EngineConfig) -> dict[str, object]:
    path = config.model_path or config.executable_path
    return {
        "url": config.url,
        "path": path,
        "speaker_id": config.speaker_id,
        "speed": config.speed,
        "pitch": config.pitch,
        "intonation": config.intonation,
        "volume": config.volume,
        "pause_length": config.pause_length,
        "pre_phoneme_length": config.pre_phoneme_length,
        "post_phoneme_length": config.post_phoneme_length,
        "max_length": config.max_length,
        "num_steps": config.num_steps,
        "num_threads": config.num_threads,
        "device": config.device,
        "device_policy": config.device_policy,
        "device_priority": list(config.device_priority),
        "backend": config.backend,
    }


def config_from_backend(kind: TtsEngineKind, values: dict, existing: EngineConfig) -> EngineConfig:
    path = str(values.get("path", ""))
    local = kind in {TtsEngineKind.SUPERTONIC, TtsEngineKind.SUPERTONIC_LIGHTWEIGHT}
    return replace(
        existing,
        url=str(values.get("url", existing.url)),
        executable_path="" if local else path,
        model_path=path if local else "",
        speaker_id=int(values.get("speaker_id", existing.speaker_id)),
        speed=float(values.get("speed", existing.speed)),
        pitch=float(values.get("pitch", existing.pitch)),
        intonation=values.get("intonation", existing.intonation),
        volume=float(values.get("volume", existing.volume)),
        pause_length=values.get("pause_length", existing.pause_length),
        pre_phoneme_length=values.get("pre_phoneme_length", existing.pre_phoneme_length),
        post_phoneme_length=values.get("post_phoneme_length", existing.post_phoneme_length),
        max_length=int(values.get("max_length", existing.max_length)),
        num_steps=values.get("num_steps", existing.num_steps),
        device=str(values.get("device", existing.device)),
    )


class TtsEngineRegistry:
    def engine_class(self, kind: TtsEngineKind) -> type[BaseTTSEngine]:
        return engine_factory.get_engine_class(kind.value)

    def create(self, config: EngineConfig) -> BaseTTSEngine:
        path = config.model_path or config.executable_path
        engine = engine_factory.get_engine_instance(config.kind.value, config.url, path)
        configure_device = getattr(engine, "configure_device", None)
        if configure_device is not None:
            configure_device(config.device)
        return engine

    def display_name(self, kind: TtsEngineKind) -> str:
        return self.engine_class(kind).DISPLAY_NAME

    def ensure_ready(
        self,
        current: BaseTTSEngine | None,
        config: EngineConfig,
        status_callback: Callable[[str], None],
        error_callback: Callable[[str], None],
        process_events: Callable[[], None],
    ) -> tuple[BaseTTSEngine | None, bool]:
        path = config.model_path or config.executable_path
        return ensure_tts_running(
            current,
            config.url,
            path,
            config.kind.value,
            status_callback,
            error_callback,
            process_events,
            config.device,
        )

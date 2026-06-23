from __future__ import annotations

import os
from collections.abc import Callable

from core.tts.base import BaseTTSEngine
import core.tts.factory as tts_factory


def ensure_tts_running(
    current_engine: BaseTTSEngine | None,
    url: str,
    path: str,
    engine_type: str,
    set_status: Callable[[str], None],
    show_error: Callable[[str], None],
    process_events: Callable[[], None],
) -> tuple[BaseTTSEngine | None, bool]:
    if not url:
        return current_engine, False

    engine_type = engine_type.lower()

    if current_engine is not None:
        current_class = current_engine.__class__
        target_class = tts_factory.get_engine_class(engine_type)
        if current_class != target_class or current_engine.url != url:
            current_engine.terminate()
            current_engine = None

    if current_engine is None:
        current_engine = tts_factory.get_engine_instance(engine_type, url, path)

    if current_engine.is_running():
        return current_engine, True

    if not path or not os.path.exists(path):
        return current_engine, False

    engine_display_name = "COEIROINK" if engine_type == "coeiroink" else "VOICEVOX"
    set_status(f"{engine_display_name}を起動中...")
    process_events()

    success = current_engine.ensure_running()
    if success:
        set_status(f"{engine_display_name}の起動を確認しました。")
        return current_engine, True

    show_error(f"{engine_display_name}の起動を確認できませんでした。手動で起動してください。")
    return current_engine, False

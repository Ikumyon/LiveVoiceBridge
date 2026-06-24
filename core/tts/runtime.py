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
    engine_type = engine_type.lower()
    target_class = tts_factory.get_engine_class(engine_type)

    if target_class.REQUIRES_URL and not url:
        return current_engine, False

    if current_engine is not None:
        current_class = current_engine.__class__
        if current_class != target_class or (current_class.REQUIRES_URL and current_engine.url != url):
            current_engine.terminate()
            current_engine = None

    if current_engine is None:
        current_engine = tts_factory.get_engine_instance(engine_type, url, path)

    if current_engine.is_running():
        return current_engine, True

    # HTTPベースのエンジンの場合、実行ファイルパスが存在しなければ自動起動できないため即座にFalseを返す
    if target_class.REQUIRES_URL:
        if not path or not os.path.exists(path):
            return current_engine, False
    else:
        # ローカルエンジンの場合、パス検証はエンジン自身の is_running/ensure_running 内で行うためスルー
        pass

    engine_display_name = current_engine.DISPLAY_NAME
    set_status(f"{engine_display_name}を起動中...")
    process_events()

    success = current_engine.ensure_running()
    if success:
        set_status(f"{engine_display_name}の起動を確認しました。")
        return current_engine, True

    if current_engine.IS_LOCAL_ENGINE:
        show_error(f"{engine_display_name}の初期化に失敗しました。モデルフォルダのパスおよび依存関係を確認してください。")
    else:
        show_error(f"{engine_display_name}の起動を確認できませんでした。手動で起動してください。")
    return current_engine, False

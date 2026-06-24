from __future__ import annotations

import sys
from pathlib import Path


APP_VERSION = "1.0.0"

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys._MEIPASS)
else:
    APP_DIR = Path(__file__).resolve().parent.parent

CORE_DIR = APP_DIR / "core"
PROTO_FILE = CORE_DIR / "stream_list.proto"
PB2_FILE = CORE_DIR / "stream_list_pb2.py"
PB2_GRPC_FILE = CORE_DIR / "stream_list_pb2_grpc.py"

UI_DIR = APP_DIR / "ui"
MAIN_UI_FILE = UI_DIR / "main_window.ui"
SETTINGS_UI_FILE = UI_DIR / "settings_dialog.ui"

ICON_FILE = APP_DIR / "assets" / "icon.png"
SETTINGS_ICON_FILE = APP_DIR / "assets" / "settings.svg"
PIP_OFF_ICON_FILE = APP_DIR / "assets" / "picture-in-picture-2.svg"
PIP_ON_ICON_FILE = APP_DIR / "assets" / "picture-in-picture.svg"
TV_ICON_FILE = APP_DIR / "assets" / "tv.svg"
PIP_ICON_FILE = PIP_OFF_ICON_FILE

if getattr(sys, "frozen", False):
    EXE_DIR = Path(sys.executable).parent
else:
    EXE_DIR = Path(__file__).resolve().parent.parent

DICT_DIR = EXE_DIR / "dict"
CONFIG_FILE = EXE_DIR / "config.json"

DEFAULT_CONFIG = {
    "youtube_api_key": "",
    "youtube_url": "",
    "speed": 1.0,
    "skip_history": True,
    "read_super_chat": True,
    "max_length": 50,
    "dict_group": "デフォルト",
    "use_ime": False,
    "comment_opacity": 0.8,
    "comment_bg_color": "#1e1e1e",
    "comment_border_color": "#3c3c3c",
    "check_updates": True,
    "tts_engine": "voicevox",
    "voicevox": {
        "url": "http://127.0.0.1:50021",
        "path": "",
        "speaker_id": 1,
    },
    "coeiroink": {
        "url": "http://127.0.0.1:50032",
        "path": "",
        "speaker_id": 1,
    },
    "bouyomichan": {
        "url": "127.0.0.1:50001",
        "path": "",
        "speaker_id": 0,
    },
    "sherpa_supertonic": {
        "url": "local://sherpa-supertonic",
        "path": "models/sherpa-onnx-supertonic-3-ja-int8",
        "speaker_id": 0,
        "sample_rate": 24000,
        "speed": 1.0,
        "num_steps": 8,
        "num_threads": 2,
        "fallback_engine": "pyopenjtalk",
        "enable_fallback": True,
        "device_policy": "auto",
        "device_priority": ["NPU", "GPU", "CPU"],
        "backend": "sherpa_onnx"
    },
    "read_blocks": [
        {"type": "message"},
    ],
}

DEFAULT_WORD_LIST = [
    {"word": "✨", "reading": "きらきら", "pos": "名詞", "comment": "初期絵文字サンプル"},
    {"word": "😭", "reading": "うるうる", "pos": "名詞", "comment": "初期絵文字サンプル"},
    {"word": "😂", "reading": "うれしなき", "pos": "名詞", "comment": "初期絵文字サンプル"},
    {"word": "👍", "reading": "ぐっど", "pos": "名詞", "comment": "初期絵文字サンプル"},
    {"word": "🔥", "reading": "めらめら", "pos": "名詞", "comment": "初期絵文字サンプル"},
    {"word": "👏", "reading": "ぱちぱち", "pos": "名詞", "comment": "初期絵文字サンプル"},
    {"word": "w", "reading": "わら", "pos": "名詞", "comment": "初期単語サンプル"},
]

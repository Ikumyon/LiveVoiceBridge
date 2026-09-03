"""Filesystem locations shared by packaged adapters and presentation code."""

from __future__ import annotations

import sys
from pathlib import Path

APP_VERSION = "0.99.2"

if getattr(sys, "frozen", False):
    APP_DIR = Path(vars(sys)["_MEIPASS"])
    EXE_DIR = Path(sys.executable).parent
    PACKAGE_DIR = APP_DIR / "livevoicebridge"
else:
    PACKAGE_DIR = Path(__file__).resolve().parent
    APP_DIR = PACKAGE_DIR.parents[1]
    EXE_DIR = APP_DIR

STREAMING_DIR = PACKAGE_DIR / "infrastructure" / "streaming"
PROTO_FILE = STREAMING_DIR / "stream_list.proto"
PB2_FILE = STREAMING_DIR / "stream_list_pb2.py"
PB2_GRPC_FILE = STREAMING_DIR / "stream_list_pb2_grpc.py"

UI_DIR = APP_DIR / "ui"
MAIN_UI_FILE = UI_DIR / "main_window.ui"
SETTINGS_UI_FILE = UI_DIR / "settings_dialog.ui"
COMMENT_WINDOW_UI_FILE = UI_DIR / "comment_window.ui"
TASK_MANAGER_UI_FILE = UI_DIR / "task_manager.ui"

ASSET_DIR = APP_DIR / "assets"
ICON_FILE = ASSET_DIR / "icon.png"
SETTINGS_ICON_FILE = ASSET_DIR / "settings.svg"
PIP_OFF_ICON_FILE = ASSET_DIR / "picture-in-picture-2.svg"
PIP_ON_ICON_FILE = ASSET_DIR / "picture-in-picture.svg"
TV_ICON_FILE = ASSET_DIR / "tv.svg"
PIP_ICON_FILE = PIP_OFF_ICON_FILE
EXTERNAL_LINK_ICON_FILE = ASSET_DIR / "external-link.svg"
X_ICON_FILE = ASSET_DIR / "x.svg"

DICT_DIR = EXE_DIR / "dict"
CONFIG_FILE = EXE_DIR / "config.json"

DEFAULT_WORD_LIST = [
    {"word": "✨", "reading": "きらきら", "pos": "名詞", "comment": "初期絵文字サンプル"},
    {"word": "😭", "reading": "うるうる", "pos": "名詞", "comment": "初期絵文字サンプル"},
    {"word": "😂", "reading": "うれしなき", "pos": "名詞", "comment": "初期絵文字サンプル"},
    {"word": "👍", "reading": "ぐっど", "pos": "名詞", "comment": "初期絵文字サンプル"},
    {"word": "🔥", "reading": "めらめら", "pos": "名詞", "comment": "初期絵文字サンプル"},
    {"word": "👏", "reading": "ぱちぱち", "pos": "名詞", "comment": "初期絵文字サンプル"},
    {"word": "w", "reading": "わら", "pos": "名詞", "comment": "初期単語サンプル"},
]

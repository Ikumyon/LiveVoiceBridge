"""Read-only package resources; no user data lives here."""

from pathlib import Path

RESOURCE_DIR = Path(__file__).resolve().parent
UI_DIR = RESOURCE_DIR / "forms"
ASSET_DIR = RESOURCE_DIR / "icons"
MAIN_UI_FILE = UI_DIR / "main_window.ui"
SETTINGS_UI_FILE = UI_DIR / "settings_dialog.ui"
COMMENT_WINDOW_UI_FILE = UI_DIR / "comment_window.ui"
TASK_MANAGER_UI_FILE = UI_DIR / "task_manager.ui"
ICON_FILE = ASSET_DIR / "icon.png"
SETTINGS_ICON_FILE = ASSET_DIR / "settings.svg"
PIP_OFF_ICON_FILE = ASSET_DIR / "picture-in-picture-2.svg"
PIP_ON_ICON_FILE = ASSET_DIR / "picture-in-picture.svg"
PIP_ICON_FILE = PIP_OFF_ICON_FILE
TV_ICON_FILE = ASSET_DIR / "tv.svg"
EXTERNAL_LINK_ICON_FILE = ASSET_DIR / "external-link.svg"
X_ICON_FILE = ASSET_DIR / "x.svg"

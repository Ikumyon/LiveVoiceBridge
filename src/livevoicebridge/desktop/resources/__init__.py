"""Read-only package resources; no user data lives here."""

from pathlib import Path

RESOURCE_DIR = Path(__file__).resolve().parent
ASSET_DIR = RESOURCE_DIR / "icons"
ICON_FILE = ASSET_DIR / "icon.png"
SETTINGS_ICON_FILE = ASSET_DIR / "settings.svg"
PIP_OFF_ICON_FILE = ASSET_DIR / "picture-in-picture-2.svg"
PIP_ON_ICON_FILE = ASSET_DIR / "picture-in-picture.svg"
TV_ICON_FILE = ASSET_DIR / "tv.svg"
EXTERNAL_LINK_ICON_FILE = ASSET_DIR / "external-link.svg"

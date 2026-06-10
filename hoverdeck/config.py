"""Application paths.

App data lives under %APPDATA%/HoverDeck on Windows (production) and falls
back to ./data next to the repo in development / on other platforms.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "HoverDeck"

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _data_dir() -> Path:
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / APP_NAME
    return PROJECT_ROOT / "data"


DATA_DIR: Path = _data_dir()
DECKS_DIR: Path = DATA_DIR / "decks"
MACROS_DIR: Path = DATA_DIR / "macros"
VAULT_DIR: Path = DATA_DIR / "vault"
SETTINGS_FILE: Path = DATA_DIR / "settings.json"
LOG_FILE: Path = DATA_DIR / "hoverdeck.log"

ASSETS_DIR: Path = PROJECT_ROOT / "assets"
FONTS_DIR: Path = ASSETS_DIR / "fonts"
ICONS_DIR: Path = ASSETS_DIR / "icons"
SCRIPTS_DIR: Path = PROJECT_ROOT / "scripts"


def ensure_dirs() -> None:
    """Create all runtime directories that the app expects to exist."""
    for path in (DATA_DIR, DECKS_DIR, MACROS_DIR, VAULT_DIR, SCRIPTS_DIR):
        path.mkdir(parents=True, exist_ok=True)

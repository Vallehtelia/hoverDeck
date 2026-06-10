"""Load/save Settings as hand-editable JSON with safe defaults."""
from __future__ import annotations

import json
from pathlib import Path

from hoverdeck.core.models import Settings
from hoverdeck.utils.logging import get_logger

log = get_logger("settings_store")


class SettingsStore:
    def __init__(self, settings_file: Path) -> None:
        self._path = settings_file

    def load(self) -> Settings:
        """Load settings; write defaults on first run; never crash on bad JSON."""
        if not self._path.exists():
            settings = Settings()
            self.save(settings)
            return settings
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return Settings.from_dict(data)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            log.error("Settings file is unreadable (%s) — using defaults. "
                      "Fix or delete %s.", exc, self._path)
            return Settings()

    def save(self, settings: Settings) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(settings.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self._path)

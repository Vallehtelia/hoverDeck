"""Load/save Settings as hand-editable JSON with safe defaults.

The AI API key is the one secret here and is NEVER written into settings.json.
It lives in an OS-encrypted secret store (DPAPI on Windows) next to the file and
is hydrated onto ``Settings.ai_api_key`` at load time. A legacy plaintext key
still present in settings.json is migrated out on first load.
"""
from __future__ import annotations

import json
from pathlib import Path

from hoverdeck.core.models import Settings
from hoverdeck.security.secret_store import SecretStore
from hoverdeck.utils.logging import get_logger

log = get_logger("settings_store")

_AI_API_KEY = "ai_api_key"


class SettingsStore:
    def __init__(self, settings_file: Path) -> None:
        self._path = settings_file
        self._secrets = SecretStore(settings_file.parent)

    def load(self) -> Settings:
        """Load settings; write defaults on first run; never crash on bad JSON."""
        if not self._path.exists():
            settings = Settings()
            self.save(settings)
            return settings
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            settings = Settings.from_dict(data)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            log.error("Settings file is unreadable (%s) — using defaults. "
                      "Fix or delete %s.", exc, self._path)
            return Settings()

        legacy_key = data.get(_AI_API_KEY) if isinstance(data, dict) else ""
        if legacy_key:
            # One-time migration: move the plaintext key into the encrypted
            # secret store and rewrite settings.json without it.
            settings.ai_api_key = legacy_key
            self.save(settings)
            log.info("Migrated the AI API key out of settings.json into "
                     "encrypted storage.")
        else:
            settings.ai_api_key = self._secrets.get(_AI_API_KEY) or ""
        return settings

    def save(self, settings: Settings) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Encrypt the key at rest; never persist it in the plaintext JSON.
        self._secrets.set(_AI_API_KEY, settings.ai_api_key)
        data = settings.to_dict()
        data[_AI_API_KEY] = ""
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self._path)

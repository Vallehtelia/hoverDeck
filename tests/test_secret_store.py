"""SecretStore + SettingsStore key-at-rest tests (Phase 1 BYO-key hardening).

Pure Python, zero Qt. On this (non-Windows) test host the secret store uses its
base64 fallback; the round-trip and migration behaviour is identical to the
DPAPI path on Windows. The load-bearing guarantee under test: the API key is
NEVER written into settings.json in plaintext.
"""
from __future__ import annotations

import json
from pathlib import Path

from hoverdeck.core.models import Settings
from hoverdeck.security.secret_store import SECRETS_FILE, SecretStore
from hoverdeck.storage.settings_store import SettingsStore

KEY = "sk-test-SECRET-abc123"


# -- SecretStore ----------------------------------------------------------

def test_secret_round_trip(tmp_path: Path) -> None:
    store = SecretStore(tmp_path)
    store.set("ai_api_key", KEY)
    assert store.get("ai_api_key") == KEY


def test_secret_missing_returns_none(tmp_path: Path) -> None:
    assert SecretStore(tmp_path).get("ai_api_key") is None


def test_secret_clear_and_empty_set(tmp_path: Path) -> None:
    store = SecretStore(tmp_path)
    store.set("ai_api_key", KEY)
    store.clear("ai_api_key")
    assert store.get("ai_api_key") is None
    # Setting an empty value is treated as a clear, not a stored "".
    store.set("ai_api_key", KEY)
    store.set("ai_api_key", "")
    assert store.get("ai_api_key") is None


def test_secret_not_stored_verbatim(tmp_path: Path) -> None:
    """Even the fallback must not leave the raw key as plain text on disk."""
    store = SecretStore(tmp_path)
    store.set("ai_api_key", KEY)
    blob = (tmp_path / SECRETS_FILE).read_text(encoding="utf-8")
    assert KEY not in blob


# -- SettingsStore integration -------------------------------------------

def test_save_keeps_key_out_of_settings_json(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    settings = Settings(ai_api_key=KEY)
    store.save(settings)

    raw = path.read_text(encoding="utf-8")
    assert KEY not in raw                       # never in plaintext JSON
    assert json.loads(raw)["ai_api_key"] == ""  # blanked marker

    # A fresh store hydrates the key back from the encrypted secret store.
    assert SettingsStore(path).load().ai_api_key == KEY


def test_legacy_plaintext_key_is_migrated(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    # Simulate an old install: key sitting in plaintext settings.json.
    path.write_text(json.dumps({"ai_provider": "anthropic", "ai_api_key": KEY}),
                    encoding="utf-8")

    loaded = SettingsStore(path).load()
    assert loaded.ai_api_key == KEY                       # still usable

    raw = path.read_text(encoding="utf-8")
    assert KEY not in raw                                 # scrubbed from JSON
    assert json.loads(raw)["ai_api_key"] == ""

    # Persisted to the secret store, so a later load still finds it.
    assert SettingsStore(path).load().ai_api_key == KEY


def test_no_key_is_graceful(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    store.save(Settings())                 # no key set
    assert store.load().ai_api_key == ""   # empty, no crash, no secrets entry

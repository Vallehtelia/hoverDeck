"""Vault crypto tests (PLAN.md §5 + §8.C). Pure Python, zero Qt."""
from __future__ import annotations

from pathlib import Path

from hoverdeck.core.models import Action, Deck
from hoverdeck.core.steps import DelayStep
from hoverdeck.security import pin as pinlib
from hoverdeck.security.vault import VaultStore


# ------------------------------------------------------------ key derivation
def test_derive_key_is_deterministic_per_salt() -> None:
    salt = pinlib.new_salt()
    key_a = pinlib.derive_key("4711", salt)
    key_b = pinlib.derive_key("4711", salt)
    assert key_a == key_b
    assert len(key_a) == pinlib.KEY_BYTES


def test_derive_key_differs_by_pin_and_salt() -> None:
    salt = pinlib.new_salt()
    assert pinlib.derive_key("4711", salt) != pinlib.derive_key("4712", salt)
    assert pinlib.derive_key("4711", salt) != pinlib.derive_key("4711", pinlib.new_salt())


def test_new_salt_is_random() -> None:
    assert pinlib.new_salt() != pinlib.new_salt()
    assert len(pinlib.new_salt()) == pinlib.SALT_BYTES


# ---------------------------------------------------------------- verify_pin
def test_verify_pin_accepts_correct_and_rejects_wrong() -> None:
    salt = pinlib.new_salt()
    token = pinlib.make_verify_token(pinlib.derive_key("123456", salt))
    assert pinlib.verify_pin("123456", salt, token) is True
    assert pinlib.verify_pin("123457", salt, token) is False
    assert pinlib.verify_pin("0000", salt, token) is False
    assert pinlib.verify_pin("123456", pinlib.new_salt(), token) is False
    assert pinlib.verify_pin("123456", salt, b"garbage") is False


# --------------------------------------------------------------- vault store
def _hidden_deck() -> Deck:
    from hoverdeck.security.vault import _empty_vault_deck

    action = Action(id="secret", name="Secret key", icon="✓",
                    steps=[DelayStep(ms=10)])
    hidden = _empty_vault_deck()
    hidden.actions[action.id] = action
    hidden.pages[0].slots[0] = action.id
    return hidden


def test_vault_setup_save_load_round_trip(tmp_path: Path) -> None:
    store = VaultStore(tmp_path / "vault")
    assert store.exists() is False

    created = store.setup("4711")
    assert store.exists() is True
    assert created.pages[0].slots == {}

    hidden = _hidden_deck()
    assert store.save("4711", hidden) is True

    loaded = store.load("4711")
    assert loaded == hidden
    assert loaded.actions["secret"].steps == [DelayStep(ms=10)]


def test_wrong_pin_returns_none_not_exception(tmp_path: Path) -> None:
    store = VaultStore(tmp_path / "vault")
    store.setup("4711")
    assert store.load("9999") is None     # wrong PIN: silent rejection
    assert store.load("471") is None
    assert store.save("9999", _hidden_deck()) is False  # wrong PIN can't write


def test_load_before_setup_returns_none(tmp_path: Path) -> None:
    assert VaultStore(tmp_path / "vault").load("4711") is None


def test_vault_blob_is_actually_encrypted(tmp_path: Path) -> None:
    store = VaultStore(tmp_path / "vault")
    store.setup("4711")
    store.save("4711", _hidden_deck())
    blob = (tmp_path / "vault" / "vault.enc").read_bytes()
    assert b"secret" not in blob
    assert b"Secret key" not in blob

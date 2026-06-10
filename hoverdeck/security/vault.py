"""The encrypted vault: the hidden page AND its actions, as one Fernet blob.

The vault stores a one-page Deck (not a bare Page) so that hidden keys'
actions never appear in the plaintext deck.json. Wrong PIN -> load() returns
None; it never raises, so the UI can show "Wrong code." and nothing else.

Files under <vault_dir>/:
    vault.enc   Fernet-encrypted JSON of the one-page Deck
    salt.bin    16 random bytes (PBKDF2 salt)
    verify.tok  encrypted verification token (see security.pin)

The PIN and derived key are never logged or persisted.
"""
from __future__ import annotations

import json
from pathlib import Path

from cryptography.fernet import InvalidToken

from hoverdeck.core.models import Deck, Page
from hoverdeck.security import pin as pinlib
from hoverdeck.utils.logging import get_logger

log = get_logger("vault")

VAULT_FILE = "vault.enc"
SALT_FILE = "salt.bin"
VERIFY_FILE = "verify.tok"

VAULT_PAGE_ID = "vault"


def _empty_vault_deck(rows: int = 2, cols: int = 3) -> Deck:
    page = Page(id=VAULT_PAGE_ID, name="Vault", rows=rows, cols=cols, slots={})
    return Deck(pages=[page], actions={})


class VaultStore:
    """Encrypt/decrypt the hidden deck under ``vault_dir``."""

    def __init__(self, vault_dir: Path) -> None:
        self._dir = vault_dir
        self._blob = vault_dir / VAULT_FILE
        self._salt = vault_dir / SALT_FILE
        self._verify = vault_dir / VERIFY_FILE

    def exists(self) -> bool:
        return self._blob.exists() and self._salt.exists() and self._verify.exists()

    def setup(self, pin: str, rows: int = 2, cols: int = 3) -> Deck:
        """First-time setup: new salt, empty hidden deck encrypted with ``pin``."""
        self._dir.mkdir(parents=True, exist_ok=True)
        salt = pinlib.new_salt()
        key = pinlib.derive_key(pin, salt)
        self._write_atomic(self._salt, salt)
        self._write_atomic(self._verify, pinlib.make_verify_token(key))
        deck = _empty_vault_deck(rows, cols)
        self._encrypt_and_write(key, deck)
        log.info("Vault created.")
        return deck

    def load(self, pin: str) -> Deck | None:
        """Decrypt the hidden deck. Wrong PIN -> None (no exception, no detail)."""
        if not self.exists():
            return None
        salt = self._salt.read_bytes()
        token = self._verify.read_bytes()
        if not pinlib.verify_pin(pin, salt, token):
            return None
        key = pinlib.derive_key(pin, salt)
        try:
            payload = pinlib.fernet_for(key).decrypt(self._blob.read_bytes())
        except (InvalidToken, ValueError):
            # Verifier passed but the blob didn't decrypt: corrupted on disk.
            log.error("Vault blob is unreadable — the file may be corrupted.")
            return None
        return Deck.from_dict(json.loads(payload.decode("utf-8")))

    def save(self, pin: str, deck: Deck) -> bool:
        """Re-encrypt the whole hidden deck. Returns False on a wrong PIN."""
        if not self.exists():
            return False
        salt = self._salt.read_bytes()
        if not pinlib.verify_pin(pin, salt, self._verify.read_bytes()):
            return False
        self._encrypt_and_write(pinlib.derive_key(pin, salt), deck)
        return True

    # ------------------------------------------------------------ internals
    def _encrypt_and_write(self, key: bytes, deck: Deck) -> None:
        payload = json.dumps(deck.to_dict(), ensure_ascii=False).encode("utf-8")
        self._write_atomic(self._blob, pinlib.fernet_for(key).encrypt(payload))

    @staticmethod
    def _write_atomic(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)

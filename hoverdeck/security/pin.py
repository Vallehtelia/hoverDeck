"""PIN -> encryption key derivation and verification. Zero Qt, no logging
of secrets — the PIN and derived key never leave this process.

The PIN's 4-6 digit format is enforced in the UI; this layer treats it as an
opaque passphrase.
"""
from __future__ import annotations

import base64
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

PBKDF2_ITERATIONS = 300_000
KEY_BYTES = 32
SALT_BYTES = 16

VERIFY_PLAINTEXT = b"HOVERDECK_VAULT_OK"


def new_salt() -> bytes:
    """A fresh random salt, generated once per vault setup."""
    return os.urandom(SALT_BYTES)


def derive_key(pin: str, salt: bytes) -> bytes:
    """PBKDF2-HMAC-SHA256(pin, salt, 300k) -> 32 raw bytes."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KEY_BYTES,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return kdf.derive(pin.encode("utf-8"))


def fernet_for(key: bytes) -> Fernet:
    """Wrap a raw 32-byte key for Fernet (which wants urlsafe base64)."""
    return Fernet(base64.urlsafe_b64encode(key))


def make_verify_token(key: bytes) -> bytes:
    """An encrypted known constant: lets us check a PIN without touching the blob."""
    return fernet_for(key).encrypt(VERIFY_PLAINTEXT)


def verify_pin(pin: str, salt: bytes, token: bytes) -> bool:
    """True only if the PIN-derived key decrypts the verification token."""
    try:
        plaintext = fernet_for(derive_key(pin, salt)).decrypt(token)
    except (InvalidToken, ValueError):
        return False
    return plaintext == VERIFY_PLAINTEXT

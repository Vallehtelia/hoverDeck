"""At-rest storage for small secrets — currently just the user's AI API key.

Zero Qt, no logging of secret values. On Windows the value is encrypted with
**DPAPI** (tied to the logged-in Windows user) via the ``utils.win`` seam, so it
is unreadable by another user or on another machine. On non-Windows platforms
there is no per-user OS keystore we can rely on, so the value is stored
base64-obfuscated only (NOT encryption) and a one-time warning is logged — those
builds are dev/non-Windows, never the shipped product.

The store lives in ``<dir>/secrets.json`` as
``{name: {"scheme": "dpapi"|"plain", "value": "<base64>"}}``.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

from hoverdeck.utils import win
from hoverdeck.utils.logging import get_logger

log = get_logger("secret_store")

SECRETS_FILE = "secrets.json"
_SCHEME_DPAPI = "dpapi"
_SCHEME_PLAIN = "plain"   # base64 only — obfuscation, NOT encryption (dev/non-Windows)


class SecretStore:
    """Store/read/clear named secrets, OS-encrypted at rest where possible."""

    def __init__(self, directory: Path) -> None:
        self._path = directory / SECRETS_FILE
        self._warned_plain = False

    def set(self, name: str, value: str) -> None:
        """Store ``value`` under ``name`` (empty value clears it)."""
        if not value:
            self.clear(name)
            return
        raw = value.encode("utf-8")
        blob = win.protect_bytes(raw)
        if blob is not None:
            entry = {"scheme": _SCHEME_DPAPI,
                     "value": base64.b64encode(blob).decode("ascii")}
        else:
            if not self._warned_plain:
                log.warning(
                    "No OS secret encryption here — storing %r base64-only "
                    "(expected on dev/non-Windows; the shipped Windows build "
                    "uses DPAPI).", name,
                )
                self._warned_plain = True
            entry = {"scheme": _SCHEME_PLAIN,
                     "value": base64.b64encode(raw).decode("ascii")}
        data = self._read()
        data[name] = entry
        self._write(data)

    def get(self, name: str) -> str | None:
        """Return the secret for ``name``, or ``None`` if unset/unreadable."""
        entry = self._read().get(name)
        if not isinstance(entry, dict):
            return None
        try:
            blob = base64.b64decode(entry.get("value", ""))
        except (ValueError, TypeError):
            return None
        scheme = entry.get("scheme")
        if scheme == _SCHEME_DPAPI:
            raw = win.unprotect_bytes(blob)
            return raw.decode("utf-8") if raw is not None else None
        if scheme == _SCHEME_PLAIN:
            return blob.decode("utf-8", "replace")
        return None

    def clear(self, name: str) -> None:
        """Remove ``name`` from the store (no-op if absent)."""
        data = self._read()
        if name in data:
            del data[name]
            self._write(data)

    # -- file I/O ----------------------------------------------------------

    def _read(self) -> dict:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.error("Secrets file unreadable (%s) — treating as empty.", exc)
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._path)

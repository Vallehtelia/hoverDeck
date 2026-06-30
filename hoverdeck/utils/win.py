"""Windows helpers — the only OS-specific seam in the codebase."""
from __future__ import annotations

import sys

from hoverdeck.utils.logging import get_logger

log = get_logger("win")

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE = "HoverDeck"


def get_active_window_title() -> str:
    """Title of the foreground window; '' when unavailable (non-Windows, no
    foreground window, or pywin32 missing)."""
    if sys.platform != "win32":
        return ""
    try:
        import win32gui  # type: ignore[import-not-found]

        return win32gui.GetWindowText(win32gui.GetForegroundWindow()) or ""
    except Exception:
        return ""


# Alias used by the profile-switcher in app.py.
get_foreground_title = get_active_window_title


def autostart_command() -> str:
    """The command the Run key should launch (frozen exe or dev pythonw)."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
    main_py = sys.path[0] or "."
    return f'"{pythonw}" "{main_py}\\main.py"'


def set_autostart(enabled: bool, command: str | None = None) -> bool:
    """Write/delete HKCU\\...\\Run\\HoverDeck. Returns success. No-op off Windows."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            if enabled:
                winreg.SetValueEx(
                    key, _RUN_VALUE, 0, winreg.REG_SZ, command or autostart_command()
                )
            else:
                try:
                    winreg.DeleteValue(key, _RUN_VALUE)
                except FileNotFoundError:
                    pass
        return True
    except OSError as exc:
        log.warning("Autostart could not be updated: %s", exc)
        return False


def get_autostart() -> bool:
    """True if the HoverDeck Run key exists. Always False off Windows."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.QueryValueEx(key, _RUN_VALUE)
        return True
    except OSError:
        return False


def protect_bytes(data: bytes) -> bytes | None:
    """DPAPI-encrypt ``data`` for the current Windows user.

    Returns the encrypted blob, or ``None`` when DPAPI is unavailable
    (non-Windows, or pywin32 missing) so the caller can fall back.
    """
    if sys.platform != "win32":
        return None
    try:
        import win32crypt  # type: ignore[import-not-found]

        # (data, description, entropy, reserved, prompt_struct, flags)
        return win32crypt.CryptProtectData(data, "HoverDeck", None, None, None, 0)
    except Exception as exc:  # noqa: BLE001 - any DPAPI failure -> fall back
        log.warning("DPAPI encrypt failed (%s) - secret not OS-encrypted.", exc)
        return None


def unprotect_bytes(blob: bytes) -> bytes | None:
    """DPAPI-decrypt a blob produced by :func:`protect_bytes`.

    Returns the plaintext bytes, or ``None`` if unavailable or the blob
    can't be decrypted (e.g. it was copied from another user/machine).
    """
    if sys.platform != "win32":
        return None
    try:
        import win32crypt  # type: ignore[import-not-found]

        _description, data = win32crypt.CryptUnprotectData(blob, None, None, None, 0)
        return data
    except Exception as exc:  # noqa: BLE001 - wrong user/corrupt -> treat as unset
        log.warning("DPAPI decrypt failed (%s) - treating secret as unset.", exc)
        return None

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

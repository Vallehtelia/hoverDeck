"""Tests for the launch step — pure Python, no Qt."""
from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from hoverdeck.core.context import ExecutionContext
from hoverdeck.core.steps.launch import LaunchStep, _APP_EXTENSIONS


# ---------------------------------------------------------------------------
# resolved_mode / auto detection
# ---------------------------------------------------------------------------

def test_auto_url():
    assert LaunchStep(target="https://example.com").resolved_mode() == "url"
    assert LaunchStep(target="http://example.com").resolved_mode() == "url"


def test_auto_app_extensions():
    for ext in (".exe", ".bat", ".cmd", ".ps1", ".py", ".sh"):
        step = LaunchStep(target=f"myscript{ext}")
        assert step.resolved_mode() == "app", f"expected app for {ext}"


def test_auto_file_for_other_extensions():
    for ext in (".pdf", ".xlsx", ".mp3", ".png", ".txt", ".docx"):
        step = LaunchStep(target=f"myfile{ext}")
        assert step.resolved_mode() == "file", f"expected file for {ext}"


def test_explicit_mode_overrides_auto():
    step = LaunchStep(target="https://example.com", mode="app")
    assert step.resolved_mode() == "app"

    step2 = LaunchStep(target="myfile.exe", mode="url")
    assert step2.resolved_mode() == "url"

    step3 = LaunchStep(target="myfile.exe", mode="file")
    assert step3.resolved_mode() == "file"


def test_auto_no_extension_is_file():
    step = LaunchStep(target="/some/path/without_ext")
    assert step.resolved_mode() == "file"


# ---------------------------------------------------------------------------
# Platform-specific open dispatching
# ---------------------------------------------------------------------------

def test_file_mode_uses_startfile_on_windows(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sys, "platform", "win32")
    called_with: list[str] = []

    import hoverdeck.core.steps.launch as _mod
    # raising=False: os.startfile doesn't exist on non-Windows at module level
    monkeypatch.setattr(_mod.os, "startfile", lambda p: called_with.append(p), raising=False)
    LaunchStep(target="report.pdf", mode="file").execute(ExecutionContext())
    assert called_with == ["report.pdf"]


def test_file_mode_uses_xdg_open_on_non_windows(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sys, "platform", "linux")
    popen_calls: list[list[str]] = []

    import hoverdeck.core.steps.launch as _mod
    monkeypatch.setattr(_mod, "_is_wsl", lambda: False)  # not WSL2 → use xdg-open
    monkeypatch.setattr(
        _mod.subprocess, "Popen",
        lambda args, **kw: popen_calls.append(args),
    )
    LaunchStep(target="document.pdf", mode="file").execute(ExecutionContext())
    assert popen_calls and popen_calls[0][0] == "xdg-open"


def test_ps1_launches_with_powershell(monkeypatch: pytest.MonkeyPatch):
    popen_calls: list[list[str]] = []
    import hoverdeck.core.steps.launch as _mod
    monkeypatch.setattr(
        _mod.subprocess, "Popen",
        lambda args, **kw: popen_calls.append(list(args)),
    )
    LaunchStep(target="script.ps1", mode="app").execute(ExecutionContext())
    assert popen_calls
    assert popen_calls[0][0] == "powershell"
    assert "-File" in popen_calls[0]
    assert "script.ps1" in popen_calls[0]


def test_py_launches_with_sys_executable(monkeypatch: pytest.MonkeyPatch):
    popen_calls: list[list[str]] = []
    import hoverdeck.core.steps.launch as _mod
    monkeypatch.setattr(
        _mod.subprocess, "Popen",
        lambda args, **kw: popen_calls.append(list(args)),
    )
    LaunchStep(target="myscript.py", mode="app").execute(ExecutionContext())
    assert popen_calls
    assert popen_calls[0][0] == sys.executable
    assert "myscript.py" in popen_calls[0]


def test_empty_target_raises_friendly_error():
    from hoverdeck.core.steps.base import StepError
    with pytest.raises(StepError, match="no target"):
        LaunchStep().execute(ExecutionContext())


def test_serialization_round_trip():
    step = LaunchStep(target="https://example.com", mode="url")
    from hoverdeck.core.steps import step_from_dict
    restored = step_from_dict(step.to_dict())
    assert restored == step


def test_app_extensions_set_contents():
    assert ".exe" in _APP_EXTENSIONS
    assert ".ps1" in _APP_EXTENSIONS
    assert ".py"  in _APP_EXTENSIONS
    assert ".pdf" not in _APP_EXTENSIONS


def test_wsl_file_uses_explorer(monkeypatch: pytest.MonkeyPatch):
    """On WSL2, file-mode converts the path via wslpath and calls explorer.exe."""
    import hoverdeck.core.steps.launch as _mod

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(_mod, "_is_wsl", lambda: True)

    run_calls: list[list[str]] = []
    popen_calls: list[list[str]] = []

    import subprocess as _sp

    class _FakeResult:
        returncode = 0
        stdout = "\\\\wsl.localhost\\Ubuntu\\root\\file.png\n"

    monkeypatch.setattr(
        _mod.subprocess, "run",
        lambda args, **kw: (_sp.CompletedProcess(args, 0, stdout="\\\\wsl.localhost\\Ubuntu\\root\\file.png\n")
                            if args[0] == "wslpath" else _FakeResult()),
    )
    monkeypatch.setattr(
        _mod.subprocess, "Popen",
        lambda args, **kw: popen_calls.append(list(args)),
    )

    LaunchStep(target="/root/file.png", mode="file").execute(ExecutionContext())
    assert popen_calls and popen_calls[0][0] == "explorer.exe"
    assert "wsl.localhost" in popen_calls[0][1]

"""Phase 3 steps (shell, launch) and condition evaluators. Zero Qt."""
from __future__ import annotations

import datetime as dt
import sys

import pytest

from hoverdeck.core.ai_builder import URL_PLACEHOLDER, substitute_placeholders
from hoverdeck.core.conditions.file_exists import FileExistsCondition
from hoverdeck.core.conditions.pixel_color import (
    parse_hex_color,
    within_tolerance,
)
from hoverdeck.core.conditions.time_window import (
    TimeWindowCondition,
    in_window,
    parse_hhmm,
)
from hoverdeck.core.context import ExecutionContext
from hoverdeck.core.steps import LaunchStep, ShellStep, step_from_dict
from hoverdeck.core.steps.base import StepError


# --------------------------------------------------------------------- shell
def test_shell_step_captures_output() -> None:
    ctx = ExecutionContext()
    ShellStep(command=f'"{sys.executable}" -c "print(42)"').execute(ctx)
    assert "42" in ctx.last_output


def test_shell_step_exit_code_error_copy() -> None:
    step = ShellStep(
        command=f'"{sys.executable}" -c "import sys; print(\'boom\', file=sys.stderr); sys.exit(7)"'
    )
    with pytest.raises(StepError, match=r"Command failed \(exit 7\) — .*boom"):
        step.execute(ExecutionContext())


def test_shell_step_empty_command_is_friendly() -> None:
    with pytest.raises(StepError, match="no command — type one in Edit"):
        ShellStep().execute(ExecutionContext())


def test_shell_step_timeout() -> None:
    step = ShellStep(
        command=f'"{sys.executable}" -c "import time; time.sleep(5)"',
        timeout_ms=200,
    )
    with pytest.raises(StepError, match="ran longer than 200 ms"):
        step.execute(ExecutionContext())


# -------------------------------------------------------------------- launch
def test_launch_mode_auto_resolution() -> None:
    assert LaunchStep(target="https://example.com").resolved_mode() == "url"
    assert LaunchStep(target="HTTP://example.com").resolved_mode() == "url"
    assert LaunchStep(target="C:/tools/thing.exe").resolved_mode() == "app"
    assert LaunchStep(target="https://x", mode="app").resolved_mode() == "app"


def test_launch_missing_app_error_copy() -> None:
    step = LaunchStep(target="/does/not/exist/app", mode="app")
    with pytest.raises(StepError,
                       match="Could not open /does/not/exist/app — check the path or URL."):
        step.execute(ExecutionContext())


def test_launch_empty_target_is_friendly() -> None:
    with pytest.raises(StepError, match="no target"):
        LaunchStep().execute(ExecutionContext())


def test_url_substitution_lands_in_launch_step() -> None:
    data = {"type": "launch", "target": URL_PLACEHOLDER, "mode": "url"}
    step = step_from_dict(substitute_placeholders(data, ["https://dash.example.com"]))
    assert isinstance(step, LaunchStep)
    assert step.target == "https://dash.example.com"


# --------------------------------------------------------------- pixel_color
def test_parse_hex_color() -> None:
    assert parse_hex_color("#F5A623") == (245, 166, 35)
    assert parse_hex_color("f5a623") == (245, 166, 35)
    with pytest.raises(ValueError):
        parse_hex_color("#zzz")


def test_within_tolerance_math() -> None:
    assert within_tolerance((100, 100, 100), (100, 100, 100), 0)
    assert within_tolerance((100, 100, 100), (110, 90, 105), 10)
    assert not within_tolerance((100, 100, 100), (111, 100, 100), 10)
    assert not within_tolerance((0, 0, 0), (0, 0, 255), 254)


# --------------------------------------------------------------- file_exists
def test_file_exists_condition(tmp_path) -> None:
    target = tmp_path / "flag.txt"
    cond = FileExistsCondition(path=str(target))
    ctx = ExecutionContext()
    assert cond.evaluate(ctx) is False
    target.write_text("here")
    assert cond.evaluate(ctx) is True
    assert FileExistsCondition(path="").evaluate(ctx) is False


# --------------------------------------------------------------- time_window
def test_time_window_normal_range() -> None:
    start, end = parse_hhmm("09:00"), parse_hhmm("17:00")
    assert in_window(dt.time(12, 0), start, end)
    assert in_window(dt.time(9, 0), start, end)
    assert not in_window(dt.time(8, 59), start, end)
    assert not in_window(dt.time(17, 1), start, end)


def test_time_window_overnight_range() -> None:
    start, end = parse_hhmm("22:00"), parse_hhmm("06:00")
    assert in_window(dt.time(23, 30), start, end)
    assert in_window(dt.time(2, 0), start, end)
    assert in_window(dt.time(22, 0), start, end)
    assert not in_window(dt.time(12, 0), start, end)
    assert not in_window(dt.time(21, 59), start, end)


def test_time_window_condition_round_trip() -> None:
    cond = TimeWindowCondition(start="22:00", end="06:00")
    from hoverdeck.core.conditions import condition_from_dict

    assert condition_from_dict(cond.to_dict()) == cond

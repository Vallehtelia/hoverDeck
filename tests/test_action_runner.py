"""Action runner + step chain tests — pure Python, no Qt."""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from hoverdeck.core.action_runner import ActionRunner, RunnerCallbacks
from hoverdeck.core.conditions import WindowTitleCondition
from hoverdeck.core.context import ExecutionContext
from hoverdeck.core.models import Action
from hoverdeck.core.steps import (
    ConditionStep,
    DelayStep,
    RunScriptStep,
    step_from_dict,
)
from hoverdeck.core.steps.base import StepError
from hoverdeck.core.steps.key_macro import parse_combo


@dataclass
class Recorder:
    """Collects callback invocations in order."""

    events: list[tuple] = field(default_factory=list)

    def callbacks(self) -> RunnerCallbacks:
        return RunnerCallbacks(
            on_started=lambda aid: self.events.append(("started", aid)),
            on_step_done=lambda aid, i, d: self.events.append(("step_done", aid, i, d)),
            on_finished=lambda aid: self.events.append(("finished", aid)),
            on_cancelled=lambda aid: self.events.append(("cancelled", aid)),
            on_error=lambda aid, i, msg: self.events.append(("error", aid, i, msg)),
        )


def _action(*steps, action_id: str = "a1") -> Action:
    return Action(id=action_id, name="Test", steps=list(steps))


def test_chain_runs_in_order_and_reports() -> None:
    rec = Recorder()
    runner = ActionRunner()
    action = _action(
        RunScriptStep(inline_code='print("one")'),
        DelayStep(ms=1),
        RunScriptStep(inline_code='print("two")'),
    )
    ctx = runner.run(action, rec.callbacks())

    kinds = [e[0] for e in rec.events]
    assert kinds == ["started", "step_done", "step_done", "step_done", "finished"]
    assert rec.events[0][1] == "a1"
    assert ctx.last_output.strip() == "two"


def test_failing_script_emits_error_not_finished() -> None:
    rec = Recorder()
    action = _action(
        RunScriptStep(inline_code="import sys; sys.exit(3)"),
        DelayStep(ms=1),  # must never run
    )
    ActionRunner().run(action, rec.callbacks())

    kinds = [e[0] for e in rec.events]
    assert kinds == ["started", "error"]
    error = rec.events[-1]
    assert error[2] == 0  # failed at step index 0
    assert "—" in error[3]  # user-facing copy: what happened + what to do


def test_missing_script_has_friendly_message() -> None:
    step = RunScriptStep(path="does/not/exist.py")
    with pytest.raises(StepError, match="Script not found — check the path in Edit."):
        step.execute(ExecutionContext())


def test_cancel_stops_the_chain() -> None:
    rec = Recorder()
    ctx = ExecutionContext()
    ctx.cancel()
    action = _action(RunScriptStep(inline_code='print("never")'))
    ActionRunner().run(action, rec.callbacks(), ctx=ctx)

    kinds = [e[0] for e in rec.events]
    assert kinds == ["started", "cancelled"]  # cancelled, no step ran, no success flash
    assert ctx.last_output == ""


def test_duplicate_run_is_ignored() -> None:
    runner = ActionRunner()
    action = _action(DelayStep(ms=200), action_id="dup")
    first = runner.run_async(action)
    import time

    time.sleep(0.05)  # let the first run register
    rec = Recorder()
    runner.run(action, rec.callbacks())  # synchronous duplicate
    assert rec.events == []  # ignored entirely
    first.join(timeout=2)
    assert not runner.is_running("dup")


def test_action_serialization_round_trip() -> None:
    action = _action(
        RunScriptStep(path="hello.py", args=["--fast"]),
        DelayStep(ms=250),
    )
    restored = Action.from_dict(action.to_dict())
    assert restored == action
    assert isinstance(restored.steps[0], RunScriptStep)
    assert isinstance(restored.steps[1], DelayStep)


def test_step_from_dict_rejects_unknown_type() -> None:
    with pytest.raises(ValueError, match="Unknown step type"):
        step_from_dict({"type": "teleport"})


def test_condition_step_round_trip_preserves_nesting() -> None:
    step = ConditionStep(
        cond=WindowTitleCondition(mode="contains", value="Photoshop"),
        then=[DelayStep(ms=10)],
        orelse=[RunScriptStep(inline_code="print('else')")],
    )
    restored = step_from_dict(step.to_dict())
    assert restored == step
    assert isinstance(restored, ConditionStep)
    assert isinstance(restored.cond, WindowTitleCondition)
    assert isinstance(restored.then[0], DelayStep)


def test_condition_step_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "hoverdeck.core.conditions.window_title.get_active_window_title",
        lambda: "My Photoshop window",
    )
    step = ConditionStep(
        cond=WindowTitleCondition(mode="contains", value="photoshop"),
        then=[RunScriptStep(inline_code="print('then ran')")],
        orelse=[RunScriptStep(inline_code="print('else ran')")],
    )
    ctx = ExecutionContext()
    step.execute(ctx)
    assert ctx.last_output.strip() == "then ran"

    monkeypatch.setattr(
        "hoverdeck.core.conditions.window_title.get_active_window_title",
        lambda: "Terminal",
    )
    step.execute(ctx)
    assert ctx.last_output.strip() == "else ran"


def test_condition_step_without_condition_is_a_friendly_error() -> None:
    with pytest.raises(StepError, match="no condition — set one in Edit"):
        ConditionStep().execute(ExecutionContext())


def test_parse_combo_normalizes_and_validates() -> None:
    assert parse_combo("Ctrl + Shift+S") == ["ctrl", "shift", "s"]
    assert parse_combo("F5") == ["f5"]
    with pytest.raises(StepError, match='Unknown key "blorp"'):
        parse_combo("ctrl+blorp")


def test_repeat_loops_until_cancelled() -> None:
    """repeat=True keeps cycling; cancel() from another thread stops it cleanly."""
    import threading
    import time

    counter: list[int] = [0]

    @dataclass
    class CountStep:
        TYPE = "count"

        def describe(self) -> str:
            return "count"

        def execute(self, ctx: ExecutionContext) -> None:
            counter[0] += 1

        def to_dict(self) -> dict:
            return {"type": self.TYPE}

    runner = ActionRunner()
    action = Action(id="loop1", name="Loop", steps=[CountStep()], repeat=True)
    rec = Recorder()

    def _cancel_after_delay() -> None:
        # Wait until the action has run at least 3 times, then cancel.
        while counter[0] < 3:
            time.sleep(0.001)
        runner.cancel("loop1")

    t = threading.Thread(target=_cancel_after_delay, daemon=True)
    t.start()
    runner.run(action, rec.callbacks())
    t.join(timeout=2)

    kinds = [e[0] for e in rec.events]
    assert kinds[0] == "started"
    assert kinds[-1] == "cancelled"       # ended with cancel, not success
    assert "finished" not in kinds        # no green flash
    assert counter[0] >= 3               # looped multiple times


def test_repeat_false_runs_once() -> None:
    """repeat=False (default) still finishes normally after one pass."""
    counter: list[int] = [0]

    @dataclass
    class CountStep:
        TYPE = "count"

        def describe(self) -> str:
            return "count"

        def execute(self, ctx: ExecutionContext) -> None:
            counter[0] += 1

        def to_dict(self) -> dict:
            return {"type": self.TYPE}

    action = Action(id="once1", name="Once", steps=[CountStep()], repeat=False)
    rec = Recorder()
    ActionRunner().run(action, rec.callbacks())

    kinds = [e[0] for e in rec.events]
    assert kinds == ["started", "step_done", "finished"]
    assert counter[0] == 1

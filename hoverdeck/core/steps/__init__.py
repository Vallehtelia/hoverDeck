"""Step types and the type registry used for (de)serialization."""
from __future__ import annotations

from typing import Any

from hoverdeck.core.steps.base import Step, StepError
from hoverdeck.core.steps.condition import ConditionStep
from hoverdeck.core.steps.delay import DelayStep
from hoverdeck.core.steps.key_macro import KeyMacroStep
from hoverdeck.core.steps.launch import LaunchStep
from hoverdeck.core.steps.run_macro import RunMacroStep
from hoverdeck.core.steps.run_script import RunScriptStep
from hoverdeck.core.steps.shell import ShellStep

STEP_REGISTRY: dict[str, type[Step]] = {
    cls.TYPE: cls
    for cls in (
        RunScriptStep,
        RunMacroStep,
        KeyMacroStep,
        ShellStep,
        LaunchStep,
        DelayStep,
        ConditionStep,
    )
}


def step_from_dict(data: dict[str, Any]) -> Step:
    """Build the right Step subclass from its serialized dict."""
    step_type = data.get("type", "")
    cls = STEP_REGISTRY.get(step_type)
    if cls is None:
        raise ValueError(f"Unknown step type: {step_type!r}")
    return cls.from_dict(data)


__all__ = [
    "Step",
    "StepError",
    "STEP_REGISTRY",
    "step_from_dict",
    "RunScriptStep",
    "RunMacroStep",
    "KeyMacroStep",
    "ShellStep",
    "LaunchStep",
    "DelayStep",
    "ConditionStep",
]

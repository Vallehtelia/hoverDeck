"""Data models: Action, Macro, Page, Deck, Settings — all JSON round-trippable.

Step subclasses live in hoverdeck.core.steps; this module only knows them
through the type registry, so adding a step type never touches models.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from hoverdeck.core.steps import Step, step_from_dict
from hoverdeck.utils.logging import get_logger

_log = get_logger("models")


@dataclass
class Action:
    """A named chain of steps, bound to a deck key."""

    id: str
    name: str
    icon: str = ""          # glyph/emoji or path to a png
    color: str = ""         # hex tint; "" = default keycap
    steps: list[Step] = field(default_factory=list)
    repeat: bool = False    # loop the step chain until the button is pressed again

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "icon": self.icon,
            "color": self.color,
            "steps": [s.to_dict() for s in self.steps],
            "repeat": self.repeat,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Action":
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            icon=data.get("icon", ""),
            color=data.get("color", ""),
            steps=[step_from_dict(s) for s in data.get("steps", [])],
            repeat=bool(data.get("repeat", False)),
        )


def action_from_dict_safe(data: Any) -> Action | None:
    """Build an Action from possibly-malformed data (e.g. AI-produced JSON).

    Returns None and logs the problem instead of raising, so callers can show
    a friendly error and keep going.
    """
    if not isinstance(data, dict):
        _log.warning("Action data is not an object: %r", type(data).__name__)
        return None
    try:
        action = Action.from_dict(data)
    except (KeyError, ValueError, TypeError) as exc:
        _log.warning("Action data did not match the schema: %s", exc)
        return None
    if not action.id or not action.name:
        _log.warning("Action data is missing an id or a name.")
        return None
    return action


@dataclass
class MacroEvent:
    """One recorded input event with its offset from recording start."""

    kind: str            # key | mouse
    action: str          # press | release | move | click | scroll
    data: dict[str, Any] = field(default_factory=dict)
    t_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MacroEvent":
        return cls(
            kind=data["kind"],
            action=data["action"],
            data=data.get("data", {}),
            t_ms=data.get("t_ms", 0),
        )


@dataclass
class Macro:
    """A recorded input sequence (Phase 2 records/plays these)."""

    id: str
    name: str
    events: list[MacroEvent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "events": [e.to_dict() for e in self.events],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Macro":
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            events=[MacroEvent.from_dict(e) for e in data.get("events", [])],
        )


@dataclass
class Page:
    """One rows×cols grid of slots; a slot index maps to an action id."""

    id: str
    name: str
    rows: int = 2
    cols: int = 3
    slots: dict[int, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "rows": self.rows,
            "cols": self.cols,
            # JSON object keys are strings; normalize on the way out.
            "slots": {str(i): a for i, a in self.slots.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Page":
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            rows=int(data.get("rows", 2)),
            cols=int(data.get("cols", 3)),
            slots={int(i): a for i, a in data.get("slots", {}).items()},
        )


@dataclass
class Deck:
    """All visible pages plus the actions they reference."""

    pages: list[Page] = field(default_factory=list)
    actions: dict[str, Action] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pages": [p.to_dict() for p in self.pages],
            "actions": {aid: a.to_dict() for aid, a in self.actions.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Deck":
        return cls(
            pages=[Page.from_dict(p) for p in data.get("pages", [])],
            actions={
                aid: Action.from_dict(a) for aid, a in data.get("actions", {}).items()
            },
        )


@dataclass
class WindowProfile:
    """Auto-switch to a specific page when the foreground window title matches."""

    id: str
    name: str
    window_pattern: str
    match_mode: Literal["contains", "equals", "regex"] = "contains"
    page_id: str = ""

    def matches(self, title: str) -> bool:
        """Return True if *title* satisfies this profile's pattern."""
        try:
            if self.match_mode == "contains":
                return self.window_pattern.lower() in title.lower()
            if self.match_mode == "equals":
                return self.window_pattern.lower() == title.lower()
            if self.match_mode == "regex":
                return bool(re.search(self.window_pattern, title))
        except re.error:
            pass
        return False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WindowProfile":
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            window_pattern=data.get("window_pattern", ""),
            match_mode=data.get("match_mode", "contains"),
            page_id=data.get("page_id", ""),
        )


@dataclass
class SecretTrigger:
    """How the hidden vault is summoned (Phase 4)."""

    type: str = "long_press"
    target: str = "handle"
    hold_ms: int = 1500

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SecretTrigger":
        return cls(
            type=data.get("type", "long_press"),
            target=data.get("target", "handle"),
            hold_ms=int(data.get("hold_ms", 1500)),
        )


@dataclass
class Settings:
    """App-wide settings, persisted as hand-editable JSON."""

    grid_rows: int = 2
    grid_cols: int = 3
    button_size: int = 72
    opacity: float = 1.0
    scale: float = 1.0
    theme: str = "sahkokeskus"
    autostart: bool = False
    relock_timeout_s: int = 60
    reduce_motion: bool = False
    peek_enabled: bool = False
    peek_edge: str = "right"          # left | right | top | bottom
    peek_offset: int = 120            # position along the tucked edge, px
    ai_provider: str = "anthropic"    # anthropic | openai
    ai_api_key: str = ""              # stored locally; sent only to the provider
    ai_panel_mode: str = "slide"      # slide | floating
    secret_trigger: SecretTrigger = field(default_factory=SecretTrigger)
    global_hotkeys: dict[str, str] = field(default_factory=dict)
    profiles: list[WindowProfile] = field(default_factory=list)
    last_browse_dir: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["secret_trigger"] = self.secret_trigger.to_dict()
        data["profiles"] = [p.to_dict() for p in self.profiles]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Settings":
        defaults = cls()
        return cls(
            grid_rows=int(data.get("grid_rows", defaults.grid_rows)),
            grid_cols=int(data.get("grid_cols", defaults.grid_cols)),
            button_size=int(data.get("button_size", defaults.button_size)),
            opacity=float(data.get("opacity", defaults.opacity)),
            scale=float(data.get("scale", defaults.scale)),
            theme=data.get("theme", defaults.theme),
            autostart=bool(data.get("autostart", defaults.autostart)),
            relock_timeout_s=int(data.get("relock_timeout_s", defaults.relock_timeout_s)),
            reduce_motion=bool(data.get("reduce_motion", defaults.reduce_motion)),
            peek_enabled=bool(data.get("peek_enabled", defaults.peek_enabled)),
            peek_edge=data.get("peek_edge", defaults.peek_edge),
            peek_offset=int(data.get("peek_offset", defaults.peek_offset)),
            ai_provider=data.get("ai_provider", defaults.ai_provider),
            ai_api_key=data.get("ai_api_key", defaults.ai_api_key),
            ai_panel_mode=data.get("ai_panel_mode", defaults.ai_panel_mode),
            secret_trigger=SecretTrigger.from_dict(data.get("secret_trigger", {})),
            global_hotkeys=dict(data.get("global_hotkeys", {})),
            profiles=[
                WindowProfile.from_dict(p) for p in data.get("profiles", [])
            ],
            last_browse_dir=str(data.get("last_browse_dir", "")),
        )

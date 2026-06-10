"""Tests for active-window profiles — pure Python, no Qt."""
from __future__ import annotations

import uuid

import pytest

from hoverdeck.core.models import Settings, WindowProfile


def _profile(
    pattern: str,
    mode: str = "contains",
    page_id: str = "p1",
    name: str = "Test",
) -> WindowProfile:
    return WindowProfile(
        id=uuid.uuid4().hex[:8],
        name=name,
        window_pattern=pattern,
        match_mode=mode,  # type: ignore[arg-type]
        page_id=page_id,
    )


# ---------------------------------------------------------------------------
# WindowProfile.matches()
# ---------------------------------------------------------------------------

def test_contains_case_insensitive():
    p = _profile("photoshop", "contains")
    assert p.matches("Adobe Photoshop 2024")
    assert p.matches("PHOTOSHOP")
    assert not p.matches("GIMP")


def test_equals_case_insensitive():
    p = _profile("notepad", "equals")
    assert p.matches("notepad")
    assert p.matches("Notepad")
    assert p.matches("NOTEPAD")
    assert not p.matches("Notepad++")


def test_regex_match():
    p = _profile(r"Visual Studio Code.*", "regex")
    assert p.matches("Visual Studio Code - myproject")
    assert not p.matches("Visual Studio 2022")


def test_regex_no_match():
    p = _profile(r"\bpython\b", "regex")
    assert p.matches("python 3.11")
    assert not p.matches("pythonista")


def test_invalid_regex_returns_false():
    p = _profile(r"[invalid(", "regex")
    assert not p.matches("anything")


def test_contains_empty_pattern_always_matches():
    p = _profile("", "contains")
    assert p.matches("anything")
    assert p.matches("")


def test_equals_empty_pattern_matches_empty_title():
    p = _profile("", "equals")
    assert p.matches("")
    assert not p.matches("something")


# ---------------------------------------------------------------------------
# First-match-wins ordering
# ---------------------------------------------------------------------------

def _find_first(profiles: list[WindowProfile], title: str) -> WindowProfile | None:
    for p in profiles:
        if p.matches(title):
            return p
    return None


def test_first_match_wins():
    p1 = _profile("Photoshop", page_id="ps_page")
    p2 = _profile("Adobe", page_id="adobe_page")
    result = _find_first([p1, p2], "Adobe Photoshop 2024")
    assert result is p1


def test_no_match_returns_none():
    profiles = [_profile("Photoshop"), _profile("Premiere")]
    assert _find_first(profiles, "Notepad") is None


# ---------------------------------------------------------------------------
# Settings round-trip with profiles
# ---------------------------------------------------------------------------

def test_settings_profiles_round_trip():
    s = Settings(profiles=[
        WindowProfile(id="abc", name="PS", window_pattern="photoshop",
                      match_mode="contains", page_id="pg1"),
    ])
    restored = Settings.from_dict(s.to_dict())
    assert len(restored.profiles) == 1
    p = restored.profiles[0]
    assert p.id == "abc"
    assert p.name == "PS"
    assert p.window_pattern == "photoshop"
    assert p.match_mode == "contains"
    assert p.page_id == "pg1"


def test_settings_last_browse_dir_round_trip():
    s = Settings(last_browse_dir="/home/user/Documents")
    restored = Settings.from_dict(s.to_dict())
    assert restored.last_browse_dir == "/home/user/Documents"


def test_settings_last_browse_dir_default_is_empty():
    s = Settings()
    assert s.last_browse_dir == ""


def test_settings_empty_profiles_round_trip():
    s = Settings()
    restored = Settings.from_dict(s.to_dict())
    assert restored.profiles == []

"""AI builder tests: safe parsing, URL capture/substitution, mocked sends."""
from __future__ import annotations

import asyncio
import json
from typing import Callable

import pytest

from hoverdeck.core.ai_builder import (
    AIBuilder,
    AIBuilderError,
    BuilderContext,
    NO_KEY_ERROR,
    URL_PLACEHOLDER,
    extract_json_block,
    substitute_placeholders,
)
from hoverdeck.core.models import Action, action_from_dict_safe
from hoverdeck.core.steps import DelayStep, LaunchStep


# ----------------------------------------------------- action_from_dict_safe
def test_safe_parse_valid_action() -> None:
    data = {
        "id": "a1",
        "name": "Open editor",
        "icon": "▶",
        "color": "",
        "steps": [{"type": "delay", "ms": 250}],
    }
    action = action_from_dict_safe(data)
    assert isinstance(action, Action)
    assert action.steps == [DelayStep(ms=250)]


def test_safe_parse_malformed_inputs_return_none() -> None:
    assert action_from_dict_safe("not a dict") is None
    assert action_from_dict_safe(None) is None
    assert action_from_dict_safe(["list"]) is None
    assert action_from_dict_safe({"id": "x", "name": "y",
                                  "steps": [{"type": "teleport"}]}) is None


def test_safe_parse_missing_fields_return_none() -> None:
    assert action_from_dict_safe({"name": "No id"}) is None
    assert action_from_dict_safe({"id": "a", "name": ""}) is None


# --------------------------------------------------------- pasted URL capture
def test_context_absorbs_urls() -> None:
    ctx = BuilderContext()
    new = ctx.absorb("open https://example.com/page?x=1 and also http://foo.bar")
    assert new == ["https://example.com/page?x=1", "http://foo.bar"]
    assert ctx.pasted_urls == new
    assert len(ctx.pasted_info) == 1

    # Re-pasting the same URL doesn't duplicate it.
    assert ctx.absorb("again: https://example.com/page?x=1") == []
    assert len(ctx.pasted_urls) == 2


def test_context_ignores_plain_text() -> None:
    ctx = BuilderContext()
    assert ctx.absorb("no links here") == []
    assert ctx.pasted_urls == []
    assert ctx.pasted_info == []


# ------------------------------------------------------------- substitution
def test_placeholder_substitution_walks_nested_structures() -> None:
    data = {
        "name": "Open site",
        "steps": [
            {"type": "launch", "target": URL_PLACEHOLDER},
            {"type": "delay", "ms": 100},
            {"nested": [{"target": URL_PLACEHOLDER}]},
        ],
    }
    out = substitute_placeholders(data, ["https://example.com"])
    assert out["steps"][0]["target"] == "https://example.com"
    assert out["steps"][2]["nested"][0]["target"] == "https://example.com"
    assert out["steps"][1]["ms"] == 100  # non-strings untouched


def test_placeholder_left_alone_without_urls() -> None:
    data = {"target": URL_PLACEHOLDER}
    assert substitute_placeholders(data, []) == data


# ------------------------------------------------------------- fence parser
def test_extract_json_block_uses_fences() -> None:
    text = "Here you go:\n```json\n{\"a\": 1}\n```\nConfirm?"
    assert json.loads(extract_json_block(text) or "") == {"a": 1}
    assert extract_json_block("no fences at all") is None
    assert extract_json_block("```json\nunterminated") is None


# ------------------------------------------------------- send (mocked HTTP)
def _mocked_builder(reply: str) -> AIBuilder:
    builder = AIBuilder("anthropic", "key-123")

    async def fake_call(messages: list[dict[str, str]],
                        on_chunk: Callable[[str], None] | None,
                        max_tokens: int = 0) -> str:
        if on_chunk is not None:
            on_chunk(reply)
        return reply

    builder._call_api = fake_call  # type: ignore[method-assign]
    return builder


def test_send_parses_action_and_substitutes_url() -> None:
    reply = (
        "Done! This opens your site.\n"
        "```json\n"
        + json.dumps({
            "name": "Open dashboard",
            "icon": "▶",
            "steps": [{"type": "launch", "target": URL_PLACEHOLDER}],
        })
        + "\n```\nShall I add it to the deck?"
    )
    builder = _mocked_builder(reply)
    ctx = BuilderContext()
    response = asyncio.run(builder.send("here: https://dash.example.com", ctx))

    assert response.ready_to_save is True
    assert response.partial_action is not None
    assert response.partial_action.id  # filled in when the agent omits it
    launch = response.partial_action.steps[0]
    assert isinstance(launch, LaunchStep)
    assert launch.target == "https://dash.example.com"
    assert ctx.partial_action is response.partial_action
    assert response.clarifying_questions == ["Shall I add it to the deck?"]
    # Both turns recorded.
    assert [m["role"] for m in builder.conversation_history] == ["user", "assistant"]


def test_send_without_json_is_a_question_turn() -> None:
    builder = _mocked_builder("Which browser should it open?")
    response = asyncio.run(builder.send("open my site", BuilderContext()))
    assert response.ready_to_save is False
    assert response.partial_action is None
    assert response.clarifying_questions == ["Which browser should it open?"]


def test_send_with_bad_json_is_not_ready() -> None:
    builder = _mocked_builder("```json\n{not json}\n```")
    response = asyncio.run(builder.send("go", BuilderContext()))
    assert response.ready_to_save is False
    assert response.partial_action is None


def test_streaming_chunks_reach_callback() -> None:
    builder = _mocked_builder("streamed reply")
    chunks: list[str] = []
    response = asyncio.run(
        builder.send("hi", BuilderContext(), on_chunk=chunks.append)
    )
    assert chunks == ["streamed reply"]
    assert response.reply == "streamed reply"


def test_missing_api_key_raises_friendly_error() -> None:
    builder = AIBuilder("anthropic", "")
    with pytest.raises(AIBuilderError, match=NO_KEY_ERROR.replace(".", r"\.")):
        asyncio.run(builder.send("hello", BuilderContext()))
    assert builder.conversation_history == []  # failed turn rolled back


# ------------------------------------------------ suggestions + scripts
from hoverdeck.core.ai_builder import parse_script, parse_suggestions


def test_parse_suggestions_block() -> None:
    text = 'Which browser?\n```suggestions\n["Firefox", "Chrome", "Edge"]\n```'
    assert parse_suggestions(text) == ["Firefox", "Chrome", "Edge"]
    assert parse_suggestions("no block") == []
    assert parse_suggestions("```suggestions\nnot json\n```") == []
    assert parse_suggestions('```suggestions\n{"a": 1}\n```') == []


def test_parse_suggestions_caps_at_four() -> None:
    text = '```suggestions\n["a","b","c","d","e","f"]\n```'
    assert parse_suggestions(text) == ["a", "b", "c", "d"]


def test_parse_script_block() -> None:
    text = (
        "Here is the script:\n```script\n# file: hello_typer.py\n"
        "import time\nprint('hi')\n```\nSave it and tell me."
    )
    script = parse_script(text)
    assert script is not None
    assert script.filename == "hello_typer.py"
    assert script.code == "import time\nprint('hi')\n"


def test_parse_script_normalizes_name() -> None:
    text = "```script\n# file: scripts/sub\\dir\\typer\nprint(1)\n```"
    script = parse_script(text)
    assert script is not None
    assert script.filename == "typer.py"   # bare name; .py appended


def test_parse_script_rejects_malformed() -> None:
    assert parse_script("no block") is None
    assert parse_script("```script\nprint('no header')\n```") is None
    assert parse_script("```script\n# file: empty.py\n\n```") is None


def test_send_carries_suggestions_and_script() -> None:
    reply = (
        "Should it run on startup?\n"
        '```suggestions\n["Yes", "No"]\n```\n'
        "```script\n# file: job.py\nprint('job')\n```"
    )
    builder = _mocked_builder(reply)
    response = asyncio.run(builder.send("make a job key", BuilderContext()))
    assert response.suggestions == ["Yes", "No"]
    assert response.script is not None and response.script.filename == "job.py"
    assert response.ready_to_save is False


# ------------------------------------------------ slot targeting + script reads
from hoverdeck.core.ai_builder import parse_script_request


def test_parse_script_request() -> None:
    assert parse_script_request("```show_script hello.py\n```") == "hello.py"
    assert parse_script_request("```show_script\nhidden/x.py\n```") == "hidden/x.py"
    assert parse_script_request("no block") is None
    assert parse_script_request("```show_script\n\n```") is None


def test_send_extracts_target_slot() -> None:
    reply = (
        "Placed in slot 3 as asked.\n```json\n"
        + json.dumps({
            "name": "Spot",
            "icon": "▶",
            "slot": 3,
            "steps": [{"type": "delay", "ms": 10}],
        })
        + "\n```"
    )
    builder = _mocked_builder(reply)
    response = asyncio.run(builder.send("slot 3 please", BuilderContext()))
    assert response.ready_to_save is True
    assert response.target_slot == 3
    # "slot" was stripped before validation, so the Action parsed cleanly.
    assert response.partial_action is not None


def test_session_note_reaches_system_prompt() -> None:
    builder = AIBuilder("anthropic", "key")
    ctx = BuilderContext(deck_slot_count=6, free_slots=[2, 5],
                         existing_scripts=["a.py", "hidden/b.py"])
    seen: dict[str, str] = {}

    async def fake_call(messages, on_chunk, max_tokens=0):
        seen["system"] = builder._system()
        return "ok"

    builder._call_api = fake_call  # type: ignore[method-assign]
    asyncio.run(builder.send("hi", ctx))
    assert "free slot indexes: [2, 5]" in seen["system"]
    assert "hidden/b.py" in seen["system"]


def test_parse_script_request_bare_and_fenced() -> None:
    # Bare line (what models actually do).
    assert parse_script_request("Let me look.\nshow_script open_gmail.py\n") == "open_gmail.py"
    assert parse_script_request("show_script hidden/sec.py") == "hidden/sec.py"
    assert parse_script_request("`show_script open_gmail.py`") == "open_gmail.py"
    # Fenced form still works.
    assert parse_script_request("```show_script\nfoo.py\n```") == "foo.py"
    # Prose that merely mentions the tool must NOT trigger it.
    assert parse_script_request("I'll use show_script to fetch the file.") is None
    assert parse_script_request("just chatting") is None


from hoverdeck.core.ai_builder import DEFAULT_MODEL


def test_builder_uses_default_model_when_unset() -> None:
    assert AIBuilder("anthropic", "k")._model() == DEFAULT_MODEL["anthropic"]
    assert AIBuilder("openai", "k")._model() == DEFAULT_MODEL["openai"]


def test_builder_uses_chosen_model() -> None:
    assert AIBuilder("anthropic", "k", "claude-opus-4-1-20250805")._model() \
        == "claude-opus-4-1-20250805"


# ------------------------------------------------ script catalog (reuse info)
from hoverdeck.core.script_catalog import catalog, summarize


def test_script_summarize_prefers_docstring(tmp_path) -> None:
    f = tmp_path / "type_text.py"
    f.write_text('"""Type the text in args[0], char by char."""\nimport sys\n')
    assert summarize(f) == "Type the text in args[0], char by char."


def test_script_summarize_falls_back_to_comment(tmp_path) -> None:
    f = tmp_path / "ping.py"
    f.write_text("#!/usr/bin/env python\n# Ping a host from args[0].\nimport sys\n")
    assert summarize(f) == "Ping a host from args[0]."
    g = tmp_path / "bare.py"
    g.write_text("import sys\nprint(1)\n")
    assert summarize(g) == ""


def test_catalog_lists_name_and_purpose(tmp_path) -> None:
    (tmp_path / "type_text.py").write_text('"""Types args[0]."""\n')
    (tmp_path / "z_blank.py").write_text("x = 1\n")
    hidden = tmp_path / "hidden"
    hidden.mkdir()
    (hidden / "secret.py").write_text('"""Vault-only thing."""\n')

    visible = catalog(tmp_path, include_hidden=False)
    assert "type_text.py — Types args[0]." in visible
    assert "z_blank.py" in visible  # no desc → bare name
    assert not any(e.startswith("hidden/") for e in visible)

    with_hidden = catalog(tmp_path, include_hidden=True)
    assert "hidden/secret.py — Vault-only thing." in with_hidden


def test_session_note_renders_script_catalog() -> None:
    ctx = BuilderContext(
        deck_slot_count=6, free_slots=[1],
        existing_scripts=["type_text.py — Types args[0].", "open_gmail.py"],
    )
    note = ctx.session_note()
    assert "REUSE one by its exact name" in note
    assert "• type_text.py — Types args[0]." in note


from hoverdeck.core.script_catalog import join_docstring, split_docstring


def test_split_docstring_separates_purpose_from_body() -> None:
    src = '"""Type args[0] char by char."""\nimport sys\nprint(sys.argv[1])\n'
    desc, body = split_docstring(src)
    assert desc == "Type args[0] char by char."
    assert body == "import sys\nprint(sys.argv[1])\n"


def test_split_docstring_no_docstring_is_lossless() -> None:
    src = "import os\nprint('hi')\n"
    assert split_docstring(src) == ("", src)
    # syntax error → don't touch it
    bad = "def (:\n"
    assert split_docstring(bad) == ("", bad)


def test_join_docstring_rebuilds_and_roundtrips() -> None:
    body = "import sys\nprint(sys.argv[1])\n"
    out = join_docstring("Type args[0].", body)
    assert out.startswith('"""Type args[0]."""\n')
    desc2, body2 = split_docstring(out)
    assert desc2 == "Type args[0]." and body2 == body
    # empty description → just the body, no stray docstring
    assert join_docstring("", body) == body


def test_edit_description_then_save_roundtrip() -> None:
    original = '"""Old purpose."""\nprint(1)\n'
    desc, body = split_docstring(original)
    assert desc == "Old purpose."
    updated = join_docstring("New, clearer purpose with args[0].", body)
    assert split_docstring(updated)[0] == "New, clearer purpose with args[0]."

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

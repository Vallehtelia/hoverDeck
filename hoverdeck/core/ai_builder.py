"""The AI macro builder: a chat agent that turns plain language into Actions.

Pure async logic, zero Qt — the panel (ui/ai_builder_panel.py) owns all UI.
Talks to Anthropic or OpenAI over httpx, streams replies, extracts a fenced
```json action block, validates it with action_from_dict_safe, and substitutes
pasted URLs into placeholder fields.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx

from hoverdeck.core.models import Action, action_from_dict_safe
from hoverdeck.utils.logging import get_logger

log = get_logger("ai_builder")

ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
OPENAI_MODEL = "gpt-4o"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

MAX_TOKENS = 2048
TIMEOUT_S = 60.0

URL_PLACEHOLDER = "PASTE_URL_HERE"
_URL_RE = re.compile(r"https?://[^\s\"'<>\)\]]+")

SYSTEM_PROMPT = """\
You are the macro-building assistant inside HoverDeck, a desktop deck of keys \
where each key runs an "action": an ordered chain of steps.

Available step types (JSON, discriminated by "type"):
- {"type": "run_script", "path": "scripts/name.py", "args": [], "inline_code": null}
- {"type": "key_macro", "keys": ["ctrl+shift+s"]}
- {"type": "delay", "ms": 500}
- {"type": "run_macro", "macro_id": "<id of an existing saved macro>"}
- {"type": "condition", "cond": {"type": "window_title", "mode": "contains", \
"value": "..."}, "then": [steps], "else": [steps]}
- {"type": "launch", "target": "<app path or URL>"}

Rules:
1. Ask exactly ONE clarifying question at a time. Keep questions short and concrete.
2. When (and only when) you have everything you need, output the action as a single \
fenced block: ```json ... ``` containing {"name": "...", "icon": "<one glyph>", \
"color": "", "steps": [...]}. Briefly describe what it does and ask the user to \
confirm before they add it to the deck.
3. If the user requests changes after seeing the action, output a corrected \
```json block in the same format.
4. NEVER ask for passwords, API keys, or other secrets. For login or credential \
steps, use a run_script step with a placeholder path like "scripts/login_site.py" \
and explain that the user fills in their credentials in that local file themselves.
5. If a step needs a URL the user has not pasted yet, either ask for it, or use the \
exact placeholder string "PASTE_URL_HERE" — HoverDeck replaces it with the URL the \
user pasted in this chat.
6. Use only the step types listed above. Keep actions short and reliable; prefer a \
delay between steps that need the screen to settle.
"""

INTRO_MESSAGE = (
    "What do you want to automate? Describe it in plain language — I'll ask "
    "questions until I have everything I need, then build it for you."
)


class AIBuilderError(RuntimeError):
    """User-facing builder failure (message follows the §4.4 copy rules)."""


NO_KEY_ERROR = "No API key — add one in Settings."
CONNECTION_ERROR = "Connection failed — check your key and network."


@dataclass
class BuilderContext:
    """What the builder knows about the deck and this conversation."""

    partial_action: Action | None = None
    existing_macros: list[str] = field(default_factory=list)
    deck_slot_count: int = 0
    pasted_urls: list[str] = field(default_factory=list)
    pasted_info: list[str] = field(default_factory=list)

    def absorb(self, text: str) -> list[str]:
        """Capture URLs (and the text around them) pasted into the chat.

        Returns the newly discovered URLs.
        """
        found = [u for u in _URL_RE.findall(text) if u not in self.pasted_urls]
        if found:
            self.pasted_urls.extend(found)
            self.pasted_info.append(text)
        return found


@dataclass
class BuilderResponse:
    reply: str
    partial_action: Action | None = None
    ready_to_save: bool = False
    clarifying_questions: list[str] = field(default_factory=list)


def extract_json_block(text: str) -> str | None:
    """Pull the contents of the first ```json fenced block (str.split, no regex)."""
    for fence in ("```json", "``` json"):
        if fence in text:
            after = text.split(fence, 1)[1]
            if "```" in after:
                return after.split("```", 1)[0].strip()
    return None


def substitute_placeholders(node: Any, urls: list[str]) -> Any:
    """Replace PASTE_URL_HERE-style values with the first pasted URL."""
    if isinstance(node, dict):
        return {k: substitute_placeholders(v, urls) for k, v in node.items()}
    if isinstance(node, list):
        return [substitute_placeholders(v, urls) for v in node]
    if isinstance(node, str) and URL_PLACEHOLDER in node and urls:
        log.info("Substituted pasted URL %s into the action.", urls[0])
        return urls[0]
    return node


class AIBuilder:
    """Stateless except for the running conversation history."""

    def __init__(self, provider: str, api_key: str) -> None:
        self.provider = provider
        self.api_key = api_key
        self.conversation_history: list[dict[str, str]] = []

    # ------------------------------------------------------------- public
    async def send(
        self,
        user_message: str,
        context: BuilderContext,
        on_chunk: Callable[[str], None] | None = None,
    ) -> BuilderResponse:
        """Send one user message; returns the parsed agent response.

        With on_chunk set, the reply is streamed and on_chunk is called per
        text fragment as it arrives (from the calling thread's event loop).
        """
        context.absorb(user_message)
        self.conversation_history.append({"role": "user", "content": user_message})
        try:
            reply = await self._call_api(self.conversation_history, on_chunk)
        except Exception:
            self.conversation_history.pop()  # keep history consistent for a retry
            raise
        self.conversation_history.append({"role": "assistant", "content": reply})
        return self._parse_reply(reply, context)

    async def test_connection(self) -> None:
        """Minimal ping; raises AIBuilderError if the provider is unreachable."""
        await self._call_api([{"role": "user", "content": "ping"}], None, max_tokens=8)

    # ------------------------------------------------------------ parsing
    def _parse_reply(self, reply: str, context: BuilderContext) -> BuilderResponse:
        questions = [
            line.strip() for line in reply.splitlines() if line.strip().endswith("?")
        ]
        response = BuilderResponse(reply=reply, clarifying_questions=questions)

        block = extract_json_block(reply)
        if block is None:
            return response
        try:
            data = json.loads(block)
        except json.JSONDecodeError as exc:
            log.warning("Agent JSON block did not parse: %s", exc)
            return response

        if isinstance(data, dict) and isinstance(data.get("action"), dict):
            data = data["action"]
        data = substitute_placeholders(data, context.pasted_urls)
        if isinstance(data, dict) and not data.get("id"):
            data["id"] = uuid.uuid4().hex[:8]

        action = action_from_dict_safe(data)
        if action is not None:
            response.partial_action = action
            response.ready_to_save = True
            context.partial_action = action
        return response

    # ---------------------------------------------------------- transport
    async def _call_api(
        self,
        messages: list[dict[str, str]],
        on_chunk: Callable[[str], None] | None,
        max_tokens: int = MAX_TOKENS,
    ) -> str:
        if not self.api_key:
            raise AIBuilderError(NO_KEY_ERROR)
        if self.provider == "anthropic":
            url = ANTHROPIC_URL
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            }
            body: dict[str, Any] = {
                "model": ANTHROPIC_MODEL,
                "max_tokens": max_tokens,
                "system": SYSTEM_PROMPT,
                "messages": messages,
            }
        elif self.provider == "openai":
            url = OPENAI_URL
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "content-type": "application/json",
            }
            body = {
                "model": OPENAI_MODEL,
                "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": SYSTEM_PROMPT}, *messages],
            }
        else:
            raise AIBuilderError(
                f'Unknown AI provider "{self.provider}" — pick one in Settings.'
            )

        try:
            if on_chunk is None:
                return await self._request(url, headers, body)
            return await self._request_streaming(url, headers, body, on_chunk)
        except AIBuilderError:
            raise
        except httpx.HTTPError as exc:
            log.warning("AI request failed: %s", exc)
            raise AIBuilderError(CONNECTION_ERROR) from exc

    async def _request(
        self, url: str, headers: dict[str, str], body: dict[str, Any]
    ) -> str:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            response = await client.post(url, headers=headers, json=body)
            if response.status_code != 200:
                log.warning("AI provider returned %d: %s",
                            response.status_code, response.text[:300])
                raise AIBuilderError(CONNECTION_ERROR)
            data = response.json()
        if self.provider == "anthropic":
            return "".join(
                block.get("text", "")
                for block in data.get("content", [])
                if block.get("type") == "text"
            )
        return data["choices"][0]["message"]["content"] or ""

    async def _request_streaming(
        self,
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
        on_chunk: Callable[[str], None],
    ) -> str:
        body = {**body, "stream": True}
        parts: list[str] = []
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            async with client.stream("POST", url, headers=headers, json=body) as response:
                if response.status_code != 200:
                    detail = (await response.aread()).decode("utf-8", "replace")[:300]
                    log.warning("AI provider returned %d: %s",
                                response.status_code, detail)
                    raise AIBuilderError(CONNECTION_ERROR)
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[len("data:"):].strip()
                    if not payload or payload == "[DONE]":
                        continue
                    try:
                        event = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    text = self._delta_text(event)
                    if text:
                        parts.append(text)
                        on_chunk(text)
        return "".join(parts)

    def _delta_text(self, event: dict[str, Any]) -> str:
        if self.provider == "anthropic":
            if event.get("type") == "content_block_delta":
                return event.get("delta", {}).get("text", "") or ""
            return ""
        choices = event.get("choices") or []
        if choices:
            return choices[0].get("delta", {}).get("content") or ""
        return ""

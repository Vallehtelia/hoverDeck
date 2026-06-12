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

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

# Curated current models offered in Settings (the dropdown is fixed-choice).
# The RECOMMENDED one balances cost against reliably following this app's
# structured tool protocol (fenced json / script / suggestions / show_script).
MODEL_CHOICES = {
    "anthropic": [
        "claude-sonnet-4-6",            # recommended: strong tool use, mid cost
        "claude-opus-4-8",              # most capable, priciest
        "claude-haiku-4-5-20251001",    # cheap, fast
        "claude-fable-5",
    ],
    "openai": [
        "gpt-5.4-mini",                 # recommended: strong tool use, low cost
        "gpt-5.5",                      # most capable
        "gpt-5.5-pro",
        "gpt-5.4",                      # affordable full model
        "gpt-5.4-pro",
        "gpt-5.4-nano",                 # cheapest, simple high-volume tasks
    ],
}
RECOMMENDED_MODEL = {"anthropic": "claude-sonnet-4-6", "openai": "gpt-5.4-mini"}
# A blank ai_model setting falls back to the recommended model.
DEFAULT_MODEL = dict(RECOMMENDED_MODEL)
ANTHROPIC_MODEL = RECOMMENDED_MODEL["anthropic"]   # back-compat aliases
OPENAI_MODEL = RECOMMENDED_MODEL["openai"]
# Where a new user generates an API key, per provider.
API_KEY_URL = {
    "anthropic": "https://console.anthropic.com/settings/keys",
    "openai": "https://platform.openai.com/api-keys",
}

MAX_TOKENS = 2048
TIMEOUT_S = 60.0

URL_PLACEHOLDER = "PASTE_URL_HERE"
_URL_RE = re.compile(r"https?://[^\s\"'<>\)\]]+")

SYSTEM_PROMPT = """\
You are the macro-building assistant inside HoverDeck, a desktop deck of keys \
where each key runs an "action": an ordered chain of steps.

Available step types (JSON, discriminated by "type"):
- {"type": "launch", "target": "<app name/path or URL>", "args": [], "mode": "auto"} \
— opens an app, file or URL and returns immediately (fire-and-forget; safe for GUI \
apps). This is the RIGHT way to open programs, incl. with flags: pass command-line \
switches in "args". A bare app name resolves automatically (no full path needed), so \
a browser in private mode is e.g. {"type":"launch","target":"firefox","mode":"app",\
"args":["-private-window","https://example.com"]} (chrome/msedge: --incognito / \
-inprivate). Use "args" only with mode "app".
- {"type": "shell", "command": "...", "cwd": null, "timeout_ms": 10000} — runs a \
command line via cmd.exe and WAITS for it, capturing output. Use ONLY for commands \
that finish and return (git, echo, build/CLI tools). NEVER use it to open a GUI app \
or browser — it would block until that app closes. Open apps with "launch" instead.
- {"type": "run_script", "path": "name.py", "args": [], "inline_code": null} — runs a \
Python script (args make it reusable, e.g. a type_text.py that types args[0]).
- {"type": "key_macro", "keys": ["ctrl+shift+s", "alt+f4"]} — sends key COMBOS only \
(not free typed text — type text with a small run_script).
- {"type": "delay", "ms": 500}
- {"type": "run_macro", "macro_id": "<id of an existing saved macro>"}
- {"type": "condition", "cond": {"type": "window_title", "mode": "contains", \
"value": "..."}, "then": [steps], "else": [steps]}

Rules:
1. Ask exactly ONE clarifying question at a time. Keep questions short and concrete. \
When the likely answers are guessable (a choice of app or browser, yes/no, a usual \
option), ALSO append a fenced block ```suggestions ["answer 1", "answer 2"] ``` with \
2-4 short tappable answers — the user can always type their own instead. Never put \
guessed file paths or URLs in suggestions; ask for those as free text.
2. When (and only when) you have everything you need, output the action as a single \
fenced block: ```json ... ``` containing {"name": "...", "icon": "<one glyph or \
emoji>", "color": "<'' or #RRGGBB>", "steps": [...]}. A NEW key with that name, icon \
and colour appears on a free deck slot when the USER presses the green ADD TO DECK \
button — you never add it yourself, so don't claim it's added. Say it's ready and ask \
them to press ADD TO DECK (or request changes).
3. If the user requests changes after seeing the action, output a corrected \
```json block in the same format.
4. NEVER ask for passwords, API keys, or other secrets. For login or credential \
steps, use a run_script step with a placeholder path like "scripts/login_site.py" \
and explain that the user fills in their credentials in that local file themselves.
5. If a step needs a URL or a file path the user has not given yet, ask for it. \
URLs may use the exact placeholder string "PASTE_URL_HERE" — HoverDeck replaces it \
with the URL the user pasted in this chat. Never invent paths.
6. COMPOSE the automation from several small steps — that's the whole point of an \
action. e.g. "open Firefox incognito to a site, then type a note in Notepad" = \
[launch firefox, mode app, args ["-private-window", <url>]], [delay 4000], \
[launch notepad], [delay 1500], [run_script type_text.py with args [the text]]. \
Reach for a step before a script; only write code for what steps can't do. Prefer \
ONE delay between steps that need the screen/app to settle.
7. A run_script step may ONLY reference a script that (a) appears in the existing \
scripts list above — use its EXACT name and documented args — or (b) one you wrote and \
the user saved THIS session (you'll get "Script saved as <path>"). NEVER invent or \
assume a script filename. If an existing script fits, reuse it; otherwise write a new \
one. Write scripts only for logic steps can't express (typing arbitrary text, \
file/data work, web requests). Keep each SMALL and single-purpose. ALWAYS make them \
REUSABLE by PARAMETERS: every value that could vary between uses (text to type, a \
path, a URL, a count, a delay) MUST be a sys.argv argument with a sensible default — \
do NOT bake such values into the code. Validate argv and print a clear usage line to \
stderr + exit(1) if required args are missing. The run_script step then passes the \
specifics via its "args". Its FIRST line must be a module docstring stating what it \
does AND each argument, e.g. \"\"\"Type args[0] char by char; args[1]=per-char \
seconds (default 0.05).\"\"\" — that's what makes it reusable later. Emit scripts \
one per message as a fenced ```script block whose FIRST line is exactly \
"# file: <short_name>.py", then the code (docstring first). Mention any pip packages \
it needs (the user installs them in Scripts → Install package).
8. You are given the deck's current state below (free slot indexes, saved macros, \
existing scripts). If the user asks for a specific position, add "slot": <one of \
the free indexes> to the action JSON; otherwise omit it and HoverDeck uses the \
first free slot.
9. PREFER UPDATING an existing script over writing a new one when the change \
belongs there. To read a script's current contents, put "show_script <name>" on \
its OWN line (e.g. show_script open_gmail.py) in the same message — don't announce \
it first, don't ask the user to do anything. HoverDeck runs it automatically and \
sends you the file contents (or "There is no script named …" if it's missing, in \
which case offer to create it). Then output a ```script block with the SAME file \
name to update it. Each tool line is acted on as soon as you send the message, so \
request what you need and stop; you'll get the results, then continue.
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
    free_slots: list[int] = field(default_factory=list)
    existing_scripts: list[str] = field(default_factory=list)  # incl. hidden/<n>
    pasted_urls: list[str] = field(default_factory=list)
    pasted_info: list[str] = field(default_factory=list)

    def session_note(self) -> str:
        """The deck-state addendum appended to the system prompt each turn."""
        lines = ["Current deck state:"]
        lines.append(f"- Page slots: {self.deck_slot_count}; "
                     f"free slot indexes: {self.free_slots or 'none'}")
        lines.append(f"- Saved macros: {self.existing_macros or 'none'}")
        if self.existing_scripts:
            lines.append("- Existing scripts (REUSE one by its exact name + args if it "
                         "fits; only write a new script if none does):")
            for entry in self.existing_scripts:
                lines.append(f"    • {entry}")
        else:
            lines.append("- Existing scripts: none")
        return "\n".join(lines)

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
class ScriptProposal:
    """A Python script the agent wrote, awaiting the user's review + save."""

    filename: str
    code: str


@dataclass
class BuilderResponse:
    reply: str
    partial_action: Action | None = None
    ready_to_save: bool = False
    clarifying_questions: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)   # tappable answers
    script: ScriptProposal | None = None                   # awaiting review
    script_request: str | None = None    # agent wants to read this script
    target_slot: int | None = None       # user-chosen slot for the action


def extract_block(text: str, tag: str) -> str | None:
    """Pull the contents of the first ```<tag> fenced block (no regex)."""
    for fence in (f"```{tag}", f"``` {tag}"):
        if fence in text:
            after = text.split(fence, 1)[1]
            if "```" in after:
                return after.split("```", 1)[0].strip()
    return None


def extract_json_block(text: str) -> str | None:
    """Pull the contents of the first ```json fenced block."""
    return extract_block(text, "json")


def parse_suggestions(text: str) -> list[str]:
    """The agent's tappable answers: a ```suggestions block with a JSON array."""
    block = extract_block(text, "suggestions")
    if not block:
        return []
    try:
        data = json.loads(block)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [str(item).strip() for item in data if str(item).strip()][:4]


_SHOW_SCRIPT_RE = re.compile(
    r"(?mi)^\s*[`*]*\s*show_script[`*: ]+\s*([\w./\\-]+\.py)\b"
)


def parse_script_request(text: str) -> str | None:
    """Find a request to read an existing script.

    Accepts the fenced ```show_script name``` form OR a bare line like
    ``show_script open_gmail.py`` (models often skip the fence), but only when
    it stands as its own directive — never from prose that merely mentions it.
    """
    block = extract_block(text, "show_script")
    if block:
        name = block.strip().splitlines()[0].strip().strip("`*")
        if name:
            return name
    match = _SHOW_SCRIPT_RE.search(text)
    return match.group(1) if match else None


def parse_script(text: str) -> ScriptProposal | None:
    """A ```script block: first line '# file: name.py', then the code."""
    block = extract_block(text, "script")
    if not block:
        return None
    first, _, rest = block.partition("\n")
    first = first.strip()
    if not first.lower().startswith("# file:"):
        return None
    filename = first.split(":", 1)[1].strip()
    if not filename:
        return None
    if not filename.endswith(".py"):
        filename += ".py"
    # Keep just the name — the user picks normal/hidden placement on save.
    filename = filename.replace("\\", "/").split("/")[-1]
    code = rest.strip("\n")
    if not code.strip():
        return None
    return ScriptProposal(filename=filename, code=code + "\n")


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

    def __init__(self, provider: str, api_key: str, model: str = "") -> None:
        self.provider = provider
        self.api_key = api_key
        self.model = model
        self.conversation_history: list[dict[str, str]] = []
        self._system_extra = ""   # per-session deck state, refreshed each send

    def _model(self) -> str:
        return self.model or DEFAULT_MODEL.get(self.provider, ANTHROPIC_MODEL)

    def _system(self) -> str:
        if self._system_extra:
            return f"{SYSTEM_PROMPT}\n\n{self._system_extra}"
        return SYSTEM_PROMPT

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
        self._system_extra = context.session_note()
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
        response = BuilderResponse(
            reply=reply,
            clarifying_questions=questions,
            suggestions=parse_suggestions(reply),
            script=parse_script(reply),
            script_request=parse_script_request(reply),
        )

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
        if isinstance(data, dict):
            slot = data.pop("slot", None)   # user-targeted placement, optional
            if isinstance(slot, int) and slot >= 0:
                response.target_slot = slot
            if not data.get("id"):
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
                "model": self._model(),
                "max_tokens": max_tokens,
                "system": self._system(),
                "messages": messages,
            }
        elif self.provider == "openai":
            url = OPENAI_URL
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "content-type": "application/json",
            }
            body = {
                "model": self._model(),
                # GPT-5.x renamed this; older models still accept it too.
                "max_completion_tokens": max_tokens,
                "messages": [{"role": "system", "content": self._system()}, *messages],
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

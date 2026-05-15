"""Pure helpers extracted from src/agent.py so they're unit-testable offline.

agent.py imports `claude_agent_sdk` at module scope (ClaudeAgentOptions and
its hook input types are used in function signatures). Putting these helpers
in their own SDK-free module means tests can exercise them directly without
the SDK installed.

The helpers stay simple and pure: each one is a dict/string transform with
no I/O beyond what's documented. agent.py re-exports them.

Called by:
  - agent.py:load_system_prompt / make_pre_tool_use_hook / make_post_tool_use_hook
  - agent.py:reply (via accumulate_tokens)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from src.audit import sha256_short

REPO_ROOT = Path(__file__).resolve().parent.parent
SYSTEM_PROMPT_PATH = REPO_ROOT / "docs" / "00-agent-identity.md"

# Fields whose values are free-form text and must be hashed before they hit
# the audit log. Anything else in tool_input passes through untouched.
HASHABLE_FIELDS: frozenset[str] = frozenset({"subject", "body", "text", "content"})


def load_system_prompt(
    *,
    path: Path | None = None,
    user_name: str | None = None,
) -> str:
    """Read docs/00-agent-identity.md and substitute the {USER_NAME} placeholder.

    docs/00 contains other `{...}` placeholders ({today}, {YYYY-MM-DD}) that
    are meant for the runtime agent — NOT Python format args. Use literal
    `.replace` so only the one variable we own is substituted; everything
    else passes through verbatim.
    """
    target = path or SYSTEM_PROMPT_PATH
    raw = target.read_text(encoding="utf-8")
    name = user_name if user_name is not None else os.environ["USER_NAME"]
    return raw.replace("{USER_NAME}", name)


def hash_input(tool_input: dict[str, Any]) -> dict[str, Any]:
    """Replace any subject/body-shaped string fields with their sha256_short hash.

    Used by the PostToolUse hook so raw email subjects, bodies, post text,
    and memory content NEVER hit the audit JSONL. Non-string values and
    keys outside `HASHABLE_FIELDS` pass through untouched.
    """
    hashed: dict[str, Any] = {}
    for key, value in tool_input.items():
        if key in HASHABLE_FIELDS and isinstance(value, str):
            hashed[f"{key}_hash"] = sha256_short(value)
        else:
            hashed[key] = value
    return hashed


def extract_sdk_session_id(event: Any) -> str | None:
    """Pull the SDK's session_id out of a SystemMessage(subtype='init') event.

    Tolerant of both event shapes the Claude Agent SDK may emit:
      - Object-style: `event.subtype == "init"` and `event.data["session_id"]`
        (matches the docs example: `isinstance(message, SystemMessage)`)
      - Dict-style: `event["subtype"] == "init"` and `event["session_id"]`

    Returns `None` when the event isn't an init message or has no id —
    never raises, so the caller can `if sid := extract_sdk_session_id(e):`
    without try/except. NOT testing both shapes leaves CI exposed to a
    silent regression if the SDK schema shifts between releases.
    """
    subtype = getattr(event, "subtype", None)
    if subtype is None and isinstance(event, dict):
        subtype = event.get("subtype")
    if subtype != "init":
        return None
    # Check three locations in order of likelihood:
    #   1. obj.data["session_id"]    — SDK SystemMessage path (docs example)
    #   2. dict["data"]["session_id"] — same shape but emitted as plain dict
    #   3. dict["session_id"]         — flattened dict form
    data = getattr(event, "data", None)
    if data is None and isinstance(event, dict):
        data = event.get("data")
    if isinstance(data, dict) and data.get("session_id"):
        return str(data["session_id"])
    if isinstance(event, dict) and event.get("session_id"):
        return str(event["session_id"])
    return None


def accumulate_tokens(event: Any, totals: dict[str, int]) -> None:
    """Best-effort token accumulator across SDK event variants.

    The Claude Agent SDK emits multiple event shapes — Assistant messages,
    Result messages — that may carry a `.usage` field with `input_tokens`
    and `output_tokens`. We tolerate either an object (`event.usage.input_tokens`)
    or a dict (`event["usage"]["input_tokens"]`) and silently skip events
    that don't have usage. NEVER raises — token tracking shouldn't take
    down a turn if the SDK schema shifts.

    `totals` is mutated in place: keys "input" and "output" are incremented.
    """
    usage = getattr(event, "usage", None)
    if usage is None and isinstance(event, dict):
        usage = event.get("usage")
    if usage is None:
        return
    in_tok = getattr(usage, "input_tokens", None)
    out_tok = getattr(usage, "output_tokens", None)
    if in_tok is None and isinstance(usage, dict):
        in_tok = usage.get("input_tokens")
        out_tok = usage.get("output_tokens")
    if in_tok:
        totals["input"] += int(in_tok)
    if out_tok:
        totals["output"] += int(out_tok)

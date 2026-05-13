"""Claude Agent SDK orchestration.

Loads `docs/00-agent-identity.md` as the runtime system prompt. That file is the
agent's L1 constitution; modifying it is a Tier 3 forbidden action. CLAUDE.md
is Claude Code dev guidance and is NOT loaded here.
"""

from __future__ import annotations

import os
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, query

REPO_ROOT = Path(__file__).resolve().parent.parent
SYSTEM_PROMPT_PATH = REPO_ROOT / "docs" / "00-agent-identity.md"


def load_system_prompt() -> str:
    raw = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    # docs/00 contains other `{...}` placeholders ({today}, {YYYY-MM-DD}) that
    # are meant for the agent at runtime — not Python format args. Use literal
    # replace so we only substitute the one variable we own.
    return raw.replace("{USER_NAME}", os.environ["USER_NAME"])


def build_options() -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        model=os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-6-2026V2"),
        max_turns=10,
        permission_mode="default",
        allowed_tools=[],
        system_prompt=load_system_prompt(),
    )


async def reply(user_message: str) -> str:
    """W1 hello-world: send one turn, collect text response."""
    options = build_options()
    chunks: list[str] = []
    async for event in query(prompt=user_message, options=options):
        text = getattr(event, "text", None)
        if text:
            chunks.append(text)
    return "".join(chunks) or "(empty response)"

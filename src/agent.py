"""Claude Agent SDK orchestration.

Loads `docs/00-agent-identity.md` as the runtime system prompt. That file is the
agent's L1 constitution; modifying it is a Tier 3 forbidden action. CLAUDE.md
is Claude Code dev guidance and is NOT loaded here.

Hook wiring:
- PreToolUse   → src.permissions.classify(): Tier 1 allow, Tier 3 deny with
                 fixed refusal message, Tier 2 routed to "ask".
- can_use_tool → src.tier2_confirm.await_decision(): sends a Telegram
                 inline-button confirm and awaits user reply (5-min timeout
                 auto-rejects). Only attached when a ConfirmRegistry +
                 notifier are provided; otherwise Tier 2 falls through to
                 the SDK's default ask path.
- PostToolUse  → src.audit.AuditLogger: one JSONL event per call, with
                 tool_input hashed to subject_hash / body_hash per docs/04 §E.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    ClaudeAgentOptions,
    HookContext,
    HookMatcher,
    PermissionResultAllow,
    PermissionResultDeny,
    PostToolUseHookInput,
    PreToolUseHookInput,
    ToolPermissionContext,
    query,
)

from src.audit import AuditEvent, AuditLogger, TokenUsage, sha256_short
from src.permissions import Tier, classify, refusal_message
from src.tier2_confirm import DEFAULT_CONFIRM_TIMEOUT, ConfirmRegistry, OnSubmit, await_decision
from src.tools.bluesky_mcp import build_server as build_bluesky_server
from src.tools.gmail_mcp import build_server as build_gmail_server
from src.tools.memory_mcp import build_server as build_memory_server

REPO_ROOT = Path(__file__).resolve().parent.parent
SYSTEM_PROMPT_PATH = REPO_ROOT / "docs" / "00-agent-identity.md"


def load_system_prompt() -> str:
    raw = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    # docs/00 contains other `{...}` placeholders ({today}, {YYYY-MM-DD}) that
    # are meant for the agent at runtime — not Python format args. Use literal
    # replace so we only substitute the one variable we own.
    return raw.replace("{USER_NAME}", os.environ["USER_NAME"])


def _hash_input(tool_input: dict[str, Any]) -> dict[str, Any]:
    """Replace any subject/body-shaped fields with their sha256_short hash."""
    hashed: dict[str, Any] = {}
    for key, value in tool_input.items():
        if key in {"subject", "body", "text", "content"} and isinstance(value, str):
            hashed[f"{key}_hash"] = sha256_short(value)
        else:
            hashed[key] = value
    return hashed


def make_pre_tool_use_hook(session_id: str):
    """Closure-capture the session so every Pre call carries it for the audit log."""

    async def pre(
        input_data: PreToolUseHookInput,
        _tool_use_id: str | None,
        _context: HookContext,
    ) -> dict[str, Any]:
        decision = classify(input_data["tool_name"], input_data.get("tool_input"))
        if decision.tier is Tier.AUTO:
            permission = "allow"
            reason = decision.reason
        elif decision.tier is Tier.REFUSE:
            permission = "deny"
            reason = refusal_message(decision.reason)
        else:  # Tier.CONFIRM
            permission = "ask"
            reason = decision.reason
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": permission,
                "permissionDecisionReason": reason,
            },
        }

    pre.session_id = session_id  # type: ignore[attr-defined]
    return pre


def make_post_tool_use_hook(session_id: str, audit: AuditLogger):
    turn_counter = {"n": 0}

    async def post(
        input_data: PostToolUseHookInput,
        _tool_use_id: str | None,
        _context: HookContext,
    ) -> dict[str, Any]:
        turn_counter["n"] += 1
        decision = classify(input_data["tool_name"], input_data.get("tool_input"))
        audit.log(
            AuditEvent(
                session_id=session_id,
                turn=turn_counter["n"],
                event_type="tool_call",
                tool=input_data["tool_name"],
                tier=int(decision.tier),
                user_confirmed=None,
                confirmation_message_id=None,
                input=_hash_input(input_data.get("tool_input") or {}),
                result="ok",
                tokens=TokenUsage(),
                cost_usd=0.0,
            )
        )
        return {"hookSpecificOutput": {"hookEventName": "PostToolUse"}}

    return post


def make_can_use_tool(
    registry: ConfirmRegistry,
    notify: OnSubmit,
    *,
    timeout_seconds: float = DEFAULT_CONFIRM_TIMEOUT,
    user_corpus: str = "",
):
    """Build the SDK's can_use_tool callback that drives the Tier-2 confirm loop.

    `user_corpus` is the user's prior writing; when present, the Tier-2 confirm
    card includes a voice-match score for the draft body so the user can spot
    drafts that don't sound like them.
    """

    async def can_use_tool(
        tool_name: str,
        tool_input: dict[str, Any],
        _ctx: ToolPermissionContext,
    ) -> PermissionResultAllow | PermissionResultDeny:
        _confirm_id, approved = await await_decision(
            registry,
            tool_name,
            tool_input,
            on_submit=notify,
            timeout_seconds=timeout_seconds,
            user_corpus=user_corpus,
        )
        if approved:
            return PermissionResultAllow()
        return PermissionResultDeny(
            message="使用者未確認(拒絕或逾時)",
            interrupt=False,
        )

    return can_use_tool


def build_options(
    session_id: str | None = None,
    *,
    confirm_registry: ConfirmRegistry | None = None,
    notify: OnSubmit | None = None,
    enable_gmail: bool = True,
    enable_memory: bool = True,
    enable_bluesky: bool = True,
    user_corpus: str = "",
) -> ClaudeAgentOptions:
    sid = session_id or uuid.uuid4().hex
    audit = AuditLogger()

    can_use_tool = None
    if confirm_registry is not None and notify is not None:
        can_use_tool = make_can_use_tool(confirm_registry, notify, user_corpus=user_corpus)

    mcp_servers: dict[str, Any] = {}
    if enable_gmail:
        mcp_servers["gmail"] = build_gmail_server()
    if enable_memory:
        mcp_servers["memory"] = build_memory_server()
    if enable_bluesky:
        mcp_servers["bluesky"] = build_bluesky_server()

    return ClaudeAgentOptions(
        model=os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-6-2026V2"),
        max_turns=10,
        permission_mode="default",
        allowed_tools=[],
        system_prompt=load_system_prompt(),
        can_use_tool=can_use_tool,
        mcp_servers=mcp_servers,
        hooks={
            "PreToolUse": [HookMatcher(hooks=[make_pre_tool_use_hook(sid)])],
            "PostToolUse": [HookMatcher(hooks=[make_post_tool_use_hook(sid, audit)])],
        },
    )


async def reply(
    user_message: str,
    *,
    session_id: str | None = None,
    confirm_registry: ConfirmRegistry | None = None,
    notify: OnSubmit | None = None,
    user_corpus: str = "",
) -> str:
    """Send one user turn, collect text response. session_id is propagated to hooks."""
    options = build_options(
        session_id,
        confirm_registry=confirm_registry,
        notify=notify,
        user_corpus=user_corpus,
    )
    chunks: list[str] = []
    async for event in query(prompt=user_message, options=options):
        text = getattr(event, "text", None)
        if text:
            chunks.append(text)
    return "".join(chunks) or "(empty response)"

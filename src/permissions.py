"""Tier classification + refusal format.

Source of truth is `docs/00-agent-identity.md` §權限分級. This module classifies
a tool call into Tier 1 (auto), Tier 2 (confirm), or Tier 3 (refuse) based on
the tool name and arguments, and renders the fixed Tier 3 refusal message.

The PreToolUse hook integration with the Agent SDK lives in `src/agent.py`;
this module is the pure classifier so it stays unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class Tier(IntEnum):
    AUTO = 1
    CONFIRM = 2
    REFUSE = 3


# Tool-name prefixes that are always Tier 1 (reads + today's session log)
TIER1_PREFIXES: tuple[str, ...] = (
    "mcp__gmail__list",
    "mcp__gmail__search",
    "mcp__gmail__read",
    "mcp__bluesky__timeline",
    "mcp__bluesky__search",
    "mcp__calendar__read",
    "memory__read",
    "WebSearch",
    "WebFetch",
)

# Tool-name patterns that are always Tier 2 (external writes, memory writes)
TIER2_PREFIXES: tuple[str, ...] = (
    "mcp__gmail__send",
    "mcp__gmail__reply",
    "mcp__gmail__draft",
    "mcp__bluesky__post",
    "mcp__bluesky__reply",
    "mcp__bluesky__comment",
    "memory__write_user_profile",
    "memory__write_learnings",
    "mcp__install",
)

# Substrings that, if found anywhere in the tool name, force Tier 3
TIER3_FORBIDDEN_SUBSTRINGS: tuple[str, ...] = (
    "modify_constitution",
    "modify_tier",
    "exfil",
    "write_api_key",
)

# Tier 3 forbidden tool-arg patterns: caller passes args dict; we check fields
# - bulk_delete with count > 10
# - memory write whose value contains any API-key-shaped substring
# - mail send whose recipient is in the flagged-addresses set
TIER3_BULK_DELETE_THRESHOLD = 10
API_KEY_SHAPES: tuple[str, ...] = (
    "sk-",
    "AKIA",
    "xoxb-",
    "ghp_",
    "ANTHROPIC_API_KEY",
)

REFUSAL_TEMPLATE = (
    "⛔ 這是 Tier 3 禁止動作:{reason}\n\n我不能執行,即使你授權。\n\n如果你真的需要,請手動操作。"
)


@dataclass(frozen=True)
class TierDecision:
    tier: Tier
    reason: str


def classify(
    tool_name: str,
    args: dict | None = None,
    *,
    flagged_addresses: frozenset[str] = frozenset(),
) -> TierDecision:
    """Return the Tier decision for a tool call.

    `args` is the dict the agent intends to pass; we use it to enforce data-level
    Tier 3 rules (bulk-delete threshold, API-key leakage, flagged recipients).
    """
    args = args or {}

    # Tier 3 — checked first, never overridden
    for substring in TIER3_FORBIDDEN_SUBSTRINGS:
        if substring in tool_name:
            return TierDecision(Tier.REFUSE, f"tool name matches forbidden pattern '{substring}'")

    if tool_name.endswith("bulk_delete"):
        count = int(args.get("count", 0))
        if count > TIER3_BULK_DELETE_THRESHOLD:
            return TierDecision(
                Tier.REFUSE,
                f"bulk delete of {count} items exceeds {TIER3_BULK_DELETE_THRESHOLD}",
            )

    if tool_name.startswith("memory__write"):
        value = str(args.get("value", ""))
        if any(shape in value for shape in API_KEY_SHAPES):
            return TierDecision(Tier.REFUSE, "memory write looks like an API key / secret")

    if tool_name.startswith("mcp__gmail__send") or tool_name.startswith("mcp__gmail__reply"):
        recipient = str(args.get("to", "")).lower()
        if recipient and recipient in flagged_addresses:
            return TierDecision(Tier.REFUSE, f"recipient {recipient!r} is flagged as suspicious")

    # Tier 2 — external writes / memory writes
    for prefix in TIER2_PREFIXES:
        if tool_name.startswith(prefix):
            return TierDecision(Tier.CONFIRM, f"external/memory write: {tool_name}")

    # Tier 1 — explicit reads (default-deny everything else is Tier 2)
    for prefix in TIER1_PREFIXES:
        if tool_name.startswith(prefix):
            return TierDecision(Tier.AUTO, f"read-only: {tool_name}")

    # Conservative default: if we don't recognize a tool, force a confirm so
    # the user sees it. The architecture doc calls this default-deny.
    return TierDecision(Tier.CONFIRM, f"unclassified tool: {tool_name}")


def refusal_message(reason: str) -> str:
    return REFUSAL_TEMPLATE.format(reason=reason)

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
    "mcp__memory__read",
    # Kimi is the agent's bulk-drafting helper — data flows to the Kimi
    # endpoint, but the resulting draft still goes through Tier 2 before
    # any external write, so this stays Tier 1 (same as Opus itself receiving
    # the user's data).
    "mcp__kimi__",
    "WebSearch",
    "WebFetch",
    # `Read` is the SDK's built-in file reader. We allow it specifically
    # so subagents (voice-drafter / forensic-analyzer) can read memories/*.md.
    # The agent could in principle read any path, but `setting_sources=[]`
    # + the workdir being the deploy root limit blast radius to the repo.
    "Read",
    "Glob",
    "Grep",
    # `Agent` is the SDK's subagent-delegation tool. Calling a subagent is
    # not an external write; it's an internal context-isolation move. Tier 1.
    "Agent",
)

# Tool-name patterns that are always Tier 2 (external writes, memory writes)
TIER2_PREFIXES: tuple[str, ...] = (
    "mcp__gmail__send",
    "mcp__gmail__reply",
    "mcp__gmail__draft",
    "mcp__bluesky__post",
    "mcp__bluesky__reply",
    "mcp__bluesky__comment",
    "mcp__memory__write_user_profile",
    "mcp__memory__write_learning",
)

# Substrings that, if found anywhere in the tool name, force Tier 3.
# `install` here covers `mcp__install_*` for installing new MCP servers —
# docs/04 §A "Don't Trust Supply Chain" and CLAUDE.md require Tier-3 refusal
# even if the user asks. Adding non-Composio/non-Anthropic MCP servers at
# runtime would let the agent acquire new capabilities outside the audited
# tool surface.
TIER3_FORBIDDEN_SUBSTRINGS: tuple[str, ...] = (
    "modify_constitution",
    "modify_tier",
    "exfil",
    "write_api_key",
    "mcp__install",
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

# Substrings that, if found in a Read/Glob path or pattern, force Tier 3.
# The SDK's built-in Read/Glob tools have no path scoping by default, so
# without this check the agent (or a compromised subagent) could exfil
# credentials by Read('.env') / Read('~/.ssh/id_rsa') / Glob('**/*.key').
# Substring match is case-insensitive — we lowercase the arg before comparing.
SENSITIVE_PATH_SUBSTRINGS: tuple[str, ...] = (
    ".env",
    ".ssh",
    "/etc/ssh",  # OpenSSH server keys (the user-home variant uses .ssh)
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "id_dsa",
    "/secrets/",
    "/private/",
    "/credentials",
    ".aws/credentials",
    ".docker/config",
    "/etc/shadow",
    "/etc/passwd",
    "/etc/sudoers",
    # Our own runtime state — agent has no business reading these directly.
    # Legitimate access to memory goes through `memories/*.md` (allowed),
    # not the trust/ or logs/ directories.
    "trust/curves.json",
    "trust/sdk_sessions.json",
    "trust/teams_conversations.json",
    "kill.flag",
)


def _path_is_sensitive(raw_path: str) -> str | None:
    """Return the matched sensitive substring, or None if path is clean."""
    if not raw_path:
        return None
    lowered = raw_path.lower()
    for needle in SENSITIVE_PATH_SUBSTRINGS:
        if needle in lowered:
            return needle
    return None


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

    # Tier 3 — sensitive-path scoping on Read / Glob. The SDK's built-in
    # readers have no path scoping; without this check the agent (or a
    # compromised subagent) could `Read('.env')` to exfil API keys, or
    # `Glob('**/*.key')` to enumerate SSH/TLS keys.
    if tool_name in {"Read", "Glob"}:
        # Read uses `file_path`; Glob uses `pattern` (+ optional `path` root).
        candidates = (
            str(args.get("file_path") or ""),
            str(args.get("pattern") or ""),
            str(args.get("path") or ""),
        )
        for cand in candidates:
            if (hit := _path_is_sensitive(cand)) is not None:
                return TierDecision(
                    Tier.REFUSE,
                    f"{tool_name} path matches sensitive pattern '{hit}'",
                )

    if tool_name.endswith("bulk_delete"):
        count = int(args.get("count", 0))
        if count > TIER3_BULK_DELETE_THRESHOLD:
            return TierDecision(
                Tier.REFUSE,
                f"bulk delete of {count} items exceeds {TIER3_BULK_DELETE_THRESHOLD}",
            )

    if tool_name.startswith("mcp__memory__write"):
        value = (
            str(args.get("value", ""))
            + " "
            + str(args.get("note", ""))
            + " "
            + str(args.get("observation", ""))
            + " "
            + str(args.get("rule", ""))
        )
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

"""Memory MCP server — two Tier-2 write tools for L2 and L3.

  `mcp__memory__write_user_profile(note)`             Tier 2 (confirm)
  `mcp__memory__write_learning(category, observation,
                                rule, confidence, counter_example)`  Tier 2

Reads of L2/L3 are NOT exposed here — the agent uses its built-in Read tool
against `memories/*.md` at session start (per docs/00 §每次 session 開始
必做). That stays Tier 1 because reads of memory files are agent-internal.

If `append_learning` downgrades the requested confidence from "高" to "低",
the warning surfaces in the tool's `content[0].text` so the agent (and
audit log) sees that the user-confirmed action was applied with a caveat.
"""

from __future__ import annotations

from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from src.memory_writes import (
    ALLOWED_CONFIDENCES,
    append_learning,
    append_user_profile,
)


def build_tools() -> list[Any]:
    @tool(
        "write_user_profile",
        "Append an explicit user-stated fact to memories/user-profile.md (L2). "
        "Use ONLY for things the user clearly said about themselves; inferences "
        "go to write_learning instead.",
        {"note": str},
    )
    async def write_user_profile(args: dict) -> dict:
        note = str(args.get("note", "")).strip()
        if not note:
            return {
                "content": [{"type": "text", "text": "note is required"}],
                "is_error": True,
            }
        block = append_user_profile(note)
        return {"content": [{"type": "text", "text": f"L2 已寫入:{block.strip()}"}]}

    @tool(
        "write_learning",
        "Append a four-field inferred rule to memories/learnings.md (L3). "
        "Confidence of '高' is auto-downgraded to '低' if the category has fewer "
        "than 5 prior observations (docs/00 anti-overfit rule).",
        {
            "category": str,
            "observation": str,
            "rule": str,
            "confidence": str,  # JSON schema doesn't carry the Literal constraint
            "counter_example": str,  # optional; empty string treated as None
        },
    )
    async def write_learning(args: dict) -> dict:
        category = str(args.get("category", "")).strip()
        observation = str(args.get("observation", "")).strip()
        rule = str(args.get("rule", "")).strip()
        confidence = str(args.get("confidence", "")).strip()
        counter_example_raw = str(args.get("counter_example", "")).strip()

        missing = [
            name
            for name, value in (
                ("category", category),
                ("observation", observation),
                ("rule", rule),
                ("confidence", confidence),
            )
            if not value
        ]
        if missing:
            return {
                "content": [
                    {"type": "text", "text": f"missing required field(s): {', '.join(missing)}"}
                ],
                "is_error": True,
            }
        if confidence not in ALLOWED_CONFIDENCES:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"confidence must be one of {list(ALLOWED_CONFIDENCES)}, "
                        f"got {confidence!r}",
                    }
                ],
                "is_error": True,
            }

        block, warning = append_learning(
            category=category,
            observation=observation,
            rule=rule,
            confidence=confidence,  # type: ignore[arg-type]
            counter_example=counter_example_raw or None,
        )
        out = f"L3 已寫入:\n{block.strip()}"
        if warning:
            out = f"⚠️ {warning}\n\n{out}"
        return {"content": [{"type": "text", "text": out}]}

    return [write_user_profile, write_learning]


def build_server() -> Any:
    return create_sdk_mcp_server(name="memory", version="0.1.0", tools=build_tools())

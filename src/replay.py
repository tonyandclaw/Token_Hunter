"""Memory Replay engine — per-decision reasoning chain + counterfactual.

Per docs/00 §記憶寫入規範, CLAUDE.md §moat, and Slide 6:

  "任何 agent 決定都附 [Why this?] 按鈕,展開後看到:
   - 觸發的 memory entry (L1 / L2 / L3 編號 + 信心)
   - 過去 3 個 similar case (連 audit log)
   - Voice match / urgency / sensitivity score
   - Counterfactual: 什麼會改變這個決定"

Given an `event_id` (= the line number in today's audit JSONL), build a
`ReplayReport` by composing:

  - the original audit event (the decision row)
  - prior audit events that share the same tool name (= similar cases)
  - L3 learnings whose category appears in the decision's tool args
  - a voice-match score for the draft text, if any
  - a forensic readout if the args contain an external sender/body
  - a counterfactual: "what set of conditions would have flipped this decision?"

The engine is pure-Python: it reads files, runs the four other moat modules,
returns a `ReplayReport`. No LLM call. Telegram UX (the [Why this?] button)
is a follow-up; once `replay.build_report(event_id)` returns text, wiring a
button is mechanical.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.forensic import ForensicReport
from src.forensic import analyze as analyze_forensic
from src.voice_scorer import VoiceScore
from src.voice_scorer import score as voice_score

REPO_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = REPO_ROOT / "logs"
LEARNINGS_PATH = REPO_ROOT / "memories" / "learnings.md"

# Match the heading of an L3 block plus its block body
_L3_BLOCK_RE = re.compile(
    r"^##\s+\[(?P<category>[^\]]+)\]\s+-\s+(?P<date>\d{4}-\d{2}-\d{2})"
    r"(?P<body>.*?)(?=^##\s+\[|\Z)",
    re.MULTILINE | re.DOTALL,
)


@dataclass(frozen=True)
class L3Entry:
    category: str
    date: str
    confidence: str
    observation: str
    rule: str

    def render(self) -> str:
        return (
            f"  [{self.category}] {self.date} (conf={self.confidence})\n"
            f"    觀察: {self.observation[:80]}\n"
            f"    規則: {self.rule[:80]}"
        )


@dataclass(frozen=True)
class ReplayReport:
    event: dict[str, Any]  # the audit event row
    similar_cases: tuple[dict[str, Any], ...]
    triggered_l3: tuple[L3Entry, ...]
    voice: VoiceScore | None  # None if no draft text in args
    forensic: ForensicReport | None  # None if no email-shaped args
    counterfactual: str

    def render(self) -> str:
        ev = self.event
        lines = [
            "📜 Memory Replay — Decision",
            f"  ts: {ev.get('ts')}",
            f"  tool: {ev.get('tool')}  tier: {ev.get('tier')}",
            f"  user_confirmed: {ev.get('user_confirmed')}",
            f"  result: {ev.get('result')}",
            "",
            f"🧠 觸發的 memory ({len(self.triggered_l3)} entries):",
        ]
        if self.triggered_l3:
            for e in self.triggered_l3:
                lines.append(e.render())
        else:
            lines.append("  (none matched this decision's category)")

        lines.append("")
        lines.append(f"📚 過去相似 case ({len(self.similar_cases)}):")
        if self.similar_cases:
            for c in self.similar_cases[:3]:
                lines.append(
                    f"  - {c.get('ts')}  result={c.get('result')}  "
                    f"confirmed={c.get('user_confirmed')}"
                )
        else:
            lines.append("  (no prior calls to this tool)")

        if self.voice is not None:
            lines.append("")
            lines.append("📈 " + self.voice.explain().replace("\n", "\n  "))

        if self.forensic is not None:
            lines.append("")
            lines.append(self.forensic.render())

        lines.append("")
        lines.append(f"🎯 Counterfactual: {self.counterfactual}")
        return "\n".join(lines)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _parse_l3_field(body: str, label: str) -> str:
    """Pull '**Label**: value' out of an L3 block body."""
    m = re.search(rf"\*\*{re.escape(label)}\*\*[::]\s*([^\n]+)", body)
    return m.group(1).strip() if m else ""


def parse_learnings(path: Path) -> list[L3Entry]:
    """Parse memories/learnings.md into a list of L3Entry."""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    entries: list[L3Entry] = []
    for m in _L3_BLOCK_RE.finditer(text):
        body = m.group("body")
        # Confidence line: "**信心度**: 高(觀察 7 次)"
        conf_raw = _parse_l3_field(body, "信心度")
        # Strip the trailing "(觀察 N 次)" so we just store the level
        conf_level = conf_raw.split("(")[0].strip()
        entries.append(
            L3Entry(
                category=m.group("category").strip(),
                date=m.group("date").strip(),
                confidence=conf_level or "?",
                observation=_parse_l3_field(body, "觀察"),
                rule=_parse_l3_field(body, "推論規則"),
            )
        )
    return entries


def find_similar_cases(
    events: list[dict[str, Any]],
    target: dict[str, Any],
    *,
    max_results: int = 3,
) -> tuple[dict[str, Any], ...]:
    """Prior events with the same tool name, most-recent first, excluding target itself."""
    target_id = (target.get("ts"), target.get("turn"), target.get("tool"))
    out: list[dict[str, Any]] = []
    for e in reversed(events):  # most-recent first
        if (e.get("ts"), e.get("turn"), e.get("tool")) == target_id:
            continue
        if e.get("tool") == target.get("tool"):
            out.append(e)
            if len(out) >= max_results:
                break
    return tuple(out)


def match_l3_for_event(
    learnings: list[L3Entry],
    event: dict[str, Any],
) -> tuple[L3Entry, ...]:
    """Return L3 entries whose category appears anywhere in the event's tool args."""
    inp = event.get("input") or {}
    haystack = " ".join(str(v) for v in inp.values()) + " " + str(event.get("tool", ""))
    haystack_lower = haystack.lower()
    out: list[L3Entry] = []
    for e in learnings:
        if e.category.lower() in haystack_lower:
            out.append(e)
    return tuple(out)


def _draft_text_from_args(input_args: dict[str, Any]) -> str:
    """Best-effort: pull the user-visible draft from a tool's input args."""
    for key in ("body", "text", "content", "value", "note"):
        v = input_args.get(key)
        if isinstance(v, str) and v:
            return v
    return ""


def _email_shape_from_args(input_args: dict[str, Any]) -> tuple[str, str] | None:
    """If the args look email-shaped (`to` + body-ish field), return (sender_domain, body).

    sender_domain is derived from the `from` field if present, else None.
    Used for forensic analysis on incoming-mail bodies. Returns None when no
    body-shaped field is present.
    """
    body = _draft_text_from_args(input_args)
    if not body:
        return None
    sender = str(input_args.get("from", "") or input_args.get("sender", "")).strip()
    domain = sender.split("@")[-1].lower() if "@" in sender else sender.lower()
    return domain, body


def _counterfactual(
    event: dict[str, Any],
    triggered: tuple[L3Entry, ...],
    forensic: ForensicReport | None,
) -> str:
    """One-line "what would have changed this decision."""
    tier = event.get("tier")
    result = event.get("result")
    if forensic is not None and forensic.severity == "block":
        return (
            "Forensic 嚴重度若為 'info' 則不會觸發攔截;目前 hits: "
            + ", ".join(forensic.injection_hits or ())
            or "domain typosquat"
        )
    if tier == 3:
        return "若工具名稱不在 Tier-3 黑名單,或 args 不含 API-key shape,則放行至 Tier 2 確認流程"
    if tier == 2:
        if result == "ok" and event.get("user_confirmed"):
            return "若使用者按 ❌ 或逾時(5 分鐘),則 Deny"
        return "若使用者按 ✅,則 Allow"
    if tier == 1:
        return "若工具不在 Tier-1 白名單,則 fall through 為 Tier 2 (default-deny)"
    if triggered:
        return f"若 L3 學習 ({len(triggered)} 條) 信心度從『高』降為『低』,可能改用更保守的回應"
    return "(本決定缺乏可量化的 counterfactual)"


def build_report_for_call(
    tool: str,
    args: dict[str, Any],
    *,
    tier: int = 2,
    user_confirmed: bool | None = None,
    logs_dir: Path | None = None,
    learnings_path: Path | None = None,
    user_corpus: str = "",
    log_date: str | None = None,
) -> ReplayReport:
    """Build a ReplayReport for a CURRENT, not-yet-audited decision.

    The audit-log path (`build_report(event_index)`) is for past decisions
    that already have a JSONL row. The `[🔍 Why this?]` button on a pre- or
    mid-execution Telegram message needs a report BEFORE the PostToolUse
    hook writes the audit event, so we synthesize a target dict from the
    live (tool, args, tier) tuple and run the same downstream pipeline:
    similar-case search by tool name, L3 trigger matching, voice score on
    the draft text, forensic on any email-shaped body, counterfactual.

    Past audit events are still read for the similar-cases section — the
    target is excluded by virtue of having a synthetic `ts` that doesn't
    appear in the log.
    """
    logs_root = logs_dir or LOGS_DIR
    learn_path = learnings_path or LEARNINGS_PATH

    if log_date is not None:
        events = _read_jsonl(logs_root / f"{log_date}.jsonl")
    else:
        candidates = sorted(logs_root.glob("*.jsonl"))
        events = _read_jsonl(candidates[-1]) if candidates else []

    target: dict[str, Any] = {
        "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tool": tool,
        "tier": tier,
        "input": dict(args or {}),
        "result": "pending",
        "user_confirmed": user_confirmed,
        "turn": None,
    }

    similar = find_similar_cases(events, target)
    learnings = parse_learnings(learn_path)
    triggered = match_l3_for_event(learnings, target)

    draft = _draft_text_from_args(target["input"])
    voice: VoiceScore | None = None
    if draft and user_corpus:
        voice = voice_score(draft, user_corpus)

    forensic: ForensicReport | None = None
    email_shape = _email_shape_from_args(target["input"])
    if email_shape is not None and email_shape[0]:
        domain, body = email_shape
        forensic = analyze_forensic(domain, body)

    counterfactual = _counterfactual(target, triggered, forensic)

    return ReplayReport(
        event=target,
        similar_cases=similar,
        triggered_l3=triggered,
        voice=voice,
        forensic=forensic,
        counterfactual=counterfactual,
    )


def build_report(
    event_index: int,
    *,
    logs_dir: Path | None = None,
    learnings_path: Path | None = None,
    user_corpus: str = "",
    log_date: str | None = None,
) -> ReplayReport | None:
    """Build a ReplayReport for the event at the given line index.

    `event_index` is 0-based within today's log (or the file matching
    `log_date`). Returns None if the event doesn't exist.
    """
    logs_root = logs_dir or LOGS_DIR
    learn_path = learnings_path or LEARNINGS_PATH

    if log_date is not None:
        log_file = logs_root / f"{log_date}.jsonl"
        events = _read_jsonl(log_file)
    else:
        # Use the most recent .jsonl in logs/
        candidates = sorted(logs_root.glob("*.jsonl"))
        events = _read_jsonl(candidates[-1]) if candidates else []

    if event_index < 0 or event_index >= len(events):
        return None

    target = events[event_index]
    similar = find_similar_cases(events[:event_index], target)
    learnings = parse_learnings(learn_path)
    triggered = match_l3_for_event(learnings, target)

    draft = _draft_text_from_args(target.get("input") or {})
    voice: VoiceScore | None = None
    if draft and user_corpus:
        voice = voice_score(draft, user_corpus)

    forensic: ForensicReport | None = None
    email_shape = _email_shape_from_args(target.get("input") or {})
    if email_shape is not None and email_shape[0]:
        domain, body = email_shape
        forensic = analyze_forensic(domain, body)

    counterfactual = _counterfactual(target, triggered, forensic)

    return ReplayReport(
        event=target,
        similar_cases=similar,
        triggered_l3=triggered,
        voice=voice,
        forensic=forensic,
        counterfactual=counterfactual,
    )

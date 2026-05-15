"""CLI ops tool — drive the runtime state without Telegram.

Usage:
  python -m src.cli trust                  — print Trust Dashboard
  python -m src.cli budget                 — print cumulative token cost
  python -m src.cli forensic [--limit N]   — print recent forensic findings
  python -m src.cli replay <event_index>   — print Memory Replay for an audit row
  python -m src.cli audit [DATE]           — print audit-log summary for DATE
                                             (default: today UTC)
  python -m src.cli scan-text <domain>     — pipe stdin through forensic.analyze

Called by: the operator at the shell (demo prep, debugging, post-incident review).
Pure I/O — never mutates state; never sends Telegram messages.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from src import forensic, forensic_log
from src.audit import LOGS_DIR
from src.cost_meter import LOGS_DIR as COST_LOGS_DIR
from src.cost_meter import usage_summary
from src.replay import build_report
from src.trust_curve import TrustCurve


def cmd_trust(_args: argparse.Namespace) -> int:
    curve = TrustCurve()
    curve.load()
    print(curve.summary())
    return 0


def cmd_budget(_args: argparse.Namespace) -> int:
    usage = usage_summary(COST_LOGS_DIR)
    print(
        f"Cumulative cost: {usage.cost_usd:.4f} USD over {usage.events} events.\n"
        f"  Opus tokens: {usage.tokens_opus}\n"
        f"  Kimi tokens: {usage.tokens_kimi}\n"
        f"  GPT  tokens: {usage.tokens_gpt}\n"
        f"  Total tokens: {usage.tokens_total}"
    )
    return 0


def cmd_forensic(args: argparse.Namespace) -> int:
    rows = forensic_log.read_recent(limit=args.limit, min_severity=args.min_severity)
    if not rows:
        print("(no forensic findings)")
        return 0
    for row in rows:
        hits = ",".join(row.get("injection_hits") or []) or "(none)"
        print(
            f"{row.get('ts')}  {row.get('severity'):<7}  "
            f"{row.get('sender_domain') or '?':<30}  hits=[{hits}]"
        )
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    report = build_report(args.event_index, log_date=args.date)
    if report is None:
        print(f"No audit event at index {args.event_index}", file=sys.stderr)
        return 1
    print(report.render())
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    target_date = args.date or datetime.now(UTC).strftime("%Y-%m-%d")
    try:
        date.fromisoformat(target_date)
    except ValueError:
        print(f"Bad date {target_date!r}, expected YYYY-MM-DD", file=sys.stderr)
        return 2
    path: Path = LOGS_DIR / f"{target_date}.jsonl"
    if not path.exists():
        print(f"(no audit log for {target_date})")
        return 0
    by_tool: dict[str, int] = {}
    by_tier: dict[int, int] = {}
    total_cost = 0.0
    total_events = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        total_events += 1
        by_tool[row.get("tool", "?")] = by_tool.get(row.get("tool", "?"), 0) + 1
        by_tier[int(row.get("tier", 0))] = by_tier.get(int(row.get("tier", 0)), 0) + 1
        total_cost += float(row.get("cost_usd") or 0)

    print(f"Audit log {target_date}: {total_events} events, {total_cost:.4f} USD")
    print("  By tier:")
    for tier in sorted(by_tier):
        print(f"    tier {tier}: {by_tier[tier]}")
    print("  By tool:")
    for t, c in sorted(by_tool.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"    {t}: {c}")
    return 0


def cmd_scan_text(args: argparse.Namespace) -> int:
    body = sys.stdin.read()
    if not body.strip():
        print("(no input on stdin)", file=sys.stderr)
        return 2
    report = forensic.analyze(args.sender_domain, body)
    print(report.render())
    return 0 if report.severity == "info" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="src.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("trust", help="print Trust Dashboard").set_defaults(func=cmd_trust)
    sub.add_parser("budget", help="print cumulative token cost").set_defaults(func=cmd_budget)

    forensic_p = sub.add_parser("forensic", help="print recent forensic findings")
    forensic_p.add_argument("--limit", type=int, default=10)
    forensic_p.add_argument("--min-severity", choices=["info", "warning", "block"], default="info")
    forensic_p.set_defaults(func=cmd_forensic)

    replay_p = sub.add_parser("replay", help="print Memory Replay for an audit row")
    replay_p.add_argument("event_index", type=int)
    replay_p.add_argument("--date", help="YYYY-MM-DD; default: most recent log file")
    replay_p.set_defaults(func=cmd_replay)

    audit_p = sub.add_parser("audit", help="print audit-log summary")
    audit_p.add_argument("date", nargs="?", help="YYYY-MM-DD; default: today UTC")
    audit_p.set_defaults(func=cmd_audit)

    scan_p = sub.add_parser("scan-text", help="run forensic.analyze on stdin body")
    scan_p.add_argument("sender_domain", help="domain to compare against trusted list")
    scan_p.set_defaults(func=cmd_scan_text)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

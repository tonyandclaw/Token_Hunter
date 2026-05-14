"""Indirect prompt-injection + phishing forensic analyzer.

Per docs/00 §防 Indirect Prompt Injection and Slide 8:
- domain similarity check (Levenshtein) against a known-good list
- SPF / DKIM evidence — we can't query DNS from a unit test, so this
  module returns "unverified" unless raw headers are passed in
- injection pattern DB — regex match against known prompt-injection
  shapes ("ignore previous instructions", "send your api key", etc.)

The analyzer is pure: input is the email's headers/body, output is a
ForensicReport dict ready to render in Telegram. The agent calls it
when a tool input or email body looks suspicious; the report goes into
the audit log as evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Known-good domains the agent should trust. In production this list is
# user-curated via L2. For MVP we ship a small starter list.
DEFAULT_TRUSTED_DOMAINS: tuple[str, ...] = (
    "asus.com",
    "anthropic.com",
    "google.com",
    "github.com",
)

# Pattern DB: each entry is (label, regex). Labels show up in the report so
# the user sees WHICH injection class fired. Keep patterns lower-case;
# matching is case-insensitive at call time.
INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("ignore_previous", re.compile(r"ignore\s+(all\s+)?previous\s+instructions?", re.IGNORECASE)),
    ("disregard_above", re.compile(r"disregard\s+(the\s+)?above", re.IGNORECASE)),
    (
        "send_credentials",
        re.compile(
            r"\b(send|share|email|forward)\b.{0,40}\b(api\s*key|password|token|credential)s?\b",
            re.IGNORECASE,
        ),
    ),
    (
        "exfiltrate_to",
        re.compile(
            r"\b(send|share|email|forward)\b.{0,40}\bto\s+(?P<addr>\S+@\S+)",
            re.IGNORECASE,
        ),
    ),
    ("you_are_now", re.compile(r"\byou\s+are\s+now\b", re.IGNORECASE)),
    (
        "system_override",
        re.compile(r"\b(new|updated)\s+system\s+(prompt|instructions?)\b", re.IGNORECASE),
    ),
    ("forget_everything", re.compile(r"\bforget\s+(everything|all)\b", re.IGNORECASE)),
    # API-key shapes embedded directly in the message (different from the
    # Tier-3 args check; this catches leaked keys in incoming mail).
    (
        "api_key_leak",
        re.compile(r"\b(sk-[A-Za-z0-9]{6,}|AKIA[A-Z0-9]{8,}|ghp_[A-Za-z0-9]{6,}|xoxb-\S+)\b"),
    ),
)


@dataclass(frozen=True)
class DomainFinding:
    sender_domain: str
    closest_trusted: str
    levenshtein: int
    looks_typosquat: bool


@dataclass(frozen=True)
class AuthFinding:
    spf_pass: bool | None  # None = unverified
    dkim_pass: bool | None
    notes: str


@dataclass(frozen=True)
class ForensicReport:
    domain: DomainFinding | None
    auth: AuthFinding
    injection_hits: tuple[str, ...] = field(default_factory=tuple)
    severity: str = "info"  # "info" | "warning" | "block"

    def render(self) -> str:
        lines = ["🔍 Forensic report"]
        if self.domain is not None:
            d = self.domain
            tag = "⚠️ typosquat suspect" if d.looks_typosquat else "✓"
            lines.append(
                f"  domain: {d.sender_domain}  vs {d.closest_trusted}  "
                f"Levenshtein={d.levenshtein}  {tag}"
            )
        lines.append(
            f"  auth: SPF={self.auth.spf_pass}  DKIM={self.auth.dkim_pass}  ({self.auth.notes})"
        )
        if self.injection_hits:
            lines.append(f"  injection patterns: {', '.join(self.injection_hits)}")
        else:
            lines.append("  injection patterns: (none)")
        lines.append(f"  severity: {self.severity}")
        return "\n".join(lines)


def levenshtein(a: str, b: str) -> int:
    """Standard Levenshtein edit distance. O(len(a) * len(b)) time, O(min) space."""
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr[j] = min(
                curr[j - 1] + 1,  # insert
                prev[j] + 1,  # delete
                prev[j - 1] + cost,  # substitute
            )
        prev = curr
    return prev[-1]


def analyze_domain(
    sender_domain: str,
    trusted: tuple[str, ...] = DEFAULT_TRUSTED_DOMAINS,
    *,
    typosquat_max_dist: int = 2,
    brand_stem_min_len: int = 4,
) -> DomainFinding | None:
    """Find the closest known-good domain and flag typo-squat candidates.

    Two heuristics combined:
    - Small Levenshtein distance to a trusted domain (catches "asu5.com").
    - Brand-stem containment: the sender contains a trusted domain's first
      label (e.g. "asus") but doesn't equal it (catches "asus-corp.com").
      Stems shorter than `brand_stem_min_len` are ignored to avoid false
      positives on short brand names.
    """
    sender_domain = sender_domain.lower().strip()
    if not sender_domain:
        return None
    best: tuple[str, int] | None = None
    for t in trusted:
        d = levenshtein(sender_domain, t.lower())
        if best is None or d < best[1]:
            best = (t, d)
    if best is None:
        return None
    closest, dist = best

    looks_typosquat = 1 <= dist <= typosquat_max_dist
    if not looks_typosquat:
        for t in trusted:
            stem = t.split(".")[0].lower()
            if (
                len(stem) >= brand_stem_min_len
                and stem in sender_domain
                and sender_domain != t.lower()
            ):
                looks_typosquat = True
                closest = t
                break

    return DomainFinding(
        sender_domain=sender_domain,
        closest_trusted=closest,
        levenshtein=dist,
        looks_typosquat=looks_typosquat,
    )


def find_injection_hits(text: str) -> tuple[str, ...]:
    """Return labels of any injection patterns that fired in `text`."""
    hits: list[str] = []
    for label, pat in INJECTION_PATTERNS:
        if pat.search(text):
            hits.append(label)
    return tuple(hits)


def analyze_auth_headers(headers: dict[str, str] | None) -> AuthFinding:
    """Parse Authentication-Results / Received-SPF when available. Return unverified otherwise."""
    if not headers:
        return AuthFinding(None, None, "no headers supplied — unverified")
    auth_header = headers.get("Authentication-Results", "").lower()
    spf_pass: bool | None
    dkim_pass: bool | None
    if "spf=pass" in auth_header:
        spf_pass = True
    elif "spf=fail" in auth_header or "spf=softfail" in auth_header:
        spf_pass = False
    else:
        spf_pass = None
    if "dkim=pass" in auth_header:
        dkim_pass = True
    elif "dkim=fail" in auth_header:
        dkim_pass = False
    else:
        dkim_pass = None
    return AuthFinding(spf_pass, dkim_pass, f"parsed from Authentication-Results: {auth_header!r}")


def _severity(
    domain: DomainFinding | None,
    auth: AuthFinding,
    hits: tuple[str, ...],
) -> str:
    if hits or (domain is not None and domain.looks_typosquat):
        return "block"
    if auth.spf_pass is False or auth.dkim_pass is False:
        return "warning"
    return "info"


def analyze(
    sender_domain: str,
    body: str,
    *,
    headers: dict[str, str] | None = None,
    trusted: tuple[str, ...] = DEFAULT_TRUSTED_DOMAINS,
) -> ForensicReport:
    """Top-level analyzer. Pass sender domain + body + optional raw headers."""
    domain = analyze_domain(sender_domain, trusted)
    auth = analyze_auth_headers(headers)
    hits = find_injection_hits(body)
    return ForensicReport(
        domain=domain,
        auth=auth,
        injection_hits=hits,
        severity=_severity(domain, auth, hits),
    )

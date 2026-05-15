# Security Policy

副手 (Fushou) is a single-user AI delegate that operates with delegated
authority over a real Gmail account, a real Bluesky account, and (depending
on `CHAT_PLATFORM`) a real Telegram or Microsoft Teams identity. The
security posture is documented in detail in
[`docs/04-security-design.md`](docs/04-security-design.md); this file
covers the disclosure policy and a one-page summary of the controls.

## Reporting a Vulnerability

**Do not file a public GitHub issue for security-relevant findings.**

Email the maintainer privately: `TonyTY_Hsieh@asus.com`.

Please include:

- A clear description of the vulnerability and the affected component
- Reproduction steps (or a proof-of-concept) where possible
- The commit hash / branch you tested against
- Your assessment of the severity (CVSS not required; rough impact note is fine)

I'll acknowledge receipt within 7 days. Fix timelines depend on severity:

| Severity                  | Initial fix target |
| :--                       | :--                |
| Critical (RCE, secret leak, auth bypass) | 7 days  |
| High (data exfil, privilege escalation)  | 14 days |
| Medium (DoS, info disclosure)            | 30 days |
| Low (hardening opportunities)            | best-effort |

If a disclosure timeline matters to you, say so in the initial email.

## In Scope

- Anything under `src/` and `.github/workflows/`
- The chat-adapter inbound auth paths (`src/chat/teams_auth.py`,
  the Telegram secret-token handling in `src/chat/telegram.py`)
- The audit logger's input-hashing contract (`src/agent_helpers.hash_input`
  + `src/audit.AuditEvent.to_jsonl`)
- The three-tier permission classifier (`src/permissions.py`)
- The forensic engine (`src/forensic.py`) and its auto-trigger callsites

## Out of Scope

The following are intentional design choices, NOT bugs:

- **Gmail uses an IMAP+SMTP app password rather than OAuth.** This is an
  explicit demo simplification documented in `docs/01-architecture.md §4`.
  A V3 enterprise variant would do OAuth.
- **Bluesky uses an atproto app password.** Same rationale.
- **`KILL.flag` is a plain file with no signature.** It's a local-disk
  out-of-band switch. If an attacker can write files on the host, they
  already have more power than the kill switch defends against.
- **Multi-instance deployments share `trust/teams_conversations.json`
  without locking.** MVP is single-process. Multi-instance is on the V2
  roadmap (`docs/01-architecture.md §6`).
- **Outbound TLS to `login.botframework.com` / `login.microsoftonline.com`
  relies on the system CA bundle.** No cert pinning. Operators worried
  about state-level MITM should pin at the OS level (e.g. via a managed
  CA store), not in the app.
- **L1 (`docs/00-agent-identity.md`) is checked into git and trusted
  verbatim.** Modifying it requires a git commit + user review; this is
  by design (it IS the user's review point).
- **Telegram bot tokens / Teams app passwords are in `.env`.** Production
  deployments should use a secrets manager; the `.env` pattern is for
  development convenience. Do not commit `.env` (it's in `.gitignore` and
  `.dockerignore`).

## Security Architecture (one-page summary)

See `docs/04-security-design.md` for the full version. Quick reference:

### Three-tier permissions (`src/permissions.py`)

- **Tier 1** — auto-allowed: reads (Gmail / Bluesky / memory / web).
- **Tier 2** — confirm in chat: external writes, memory writes, installing
  tools, batches > 5, anything touching money. 5-minute timeout → auto-deny.
- **Tier 3** — refuse, even on user request: modifying constitution,
  bulk_delete > 10 items, memory writes containing API-key-shaped strings
  (`sk-` / `AKIA` / `xoxb-` / `ghp_`), sends to flagged recipients,
  installing non-Composio / non-Anthropic MCP servers.

The Tier 3 refusal template is fixed (`⛔ 這是 Tier 3 禁止動作:…`) and
pinned by `tests/test_permissions.py`. Don't paraphrase it.

### Four-layer memory (`docs/04 §D`)

`L1 > L2 > L3 > L4 > external content` — strict conflict resolution.

- **L1** `docs/00-agent-identity.md` — constitution; reloaded from disk
  every session; only changed via git commit.
- **L2** `memories/user-profile.md` — user-stated facts; append-only;
  Tier-2 confirm required.
- **L3** `memories/learnings.md` — agent-inferred rules; append-only;
  `HIGH_CONFIDENCE_MIN_OBS = 5` (single corrections create new
  low-confidence entries; never over-fit).
- **L4** `memories/sessions/{date}.md` — auto-appended timeline; 30-day
  rolling retention via `session_log.prune_old`.

### Inbound transport authentication

- **Telegram**: `secret_token` echo header verified by python-telegram-bot
  before any handler runs.
- **Teams**: Bot Framework JWT verified via PyJWT + JWKS (`src/chat/teams_auth.py`):
  signature, `iss` = `https://api.botframework.com`, `aud` = `TEAMS_APP_ID`,
  `exp`, and `serviceurl` cross-check against the activity. JWKS cached 24h
  with force-refresh-on-unknown-kid for rotation. `verify_inbound=False` is
  available for Bot Framework Emulator runs only — **never** disable in
  production.

### Forensic auto-scan

- `gmail_mcp.read` automatically calls `forensic.analyze` on every fetched
  email body. Findings prepended to the body the agent sees, AND appended
  to `logs/forensic.jsonl`.
- `bluesky_mcp.timeline` / `search` scan every returned post; warning+
  severity rows append to the same forensic log (info skipped to keep the
  log compact under firehose load).
- Detection patterns: 8 regexes for prompt-injection shapes
  (`ignore_previous`, `send_credentials`, `exfiltrate_to`, `api_key_leak`,
  etc.) + domain Levenshtein vs trusted list + brand-stem containment.

### Audit logging

- `logs/{YYYY-MM-DD}.jsonl` — one line per tool call (PostToolUse hook) +
  one `turn_summary` row per agent turn (cost-tracking).
- `subject` / `body` / `text` / `content` fields are sha256-short hashed
  before write (`agent_helpers.hash_input` + `HASHABLE_FIELDS` frozenset).
  Raw text never enters the JSONL.
- `logs/forensic.jsonl` — separate stream for the forensic engine.
- CLI: `python -m src.cli {audit,forensic,replay}` for offline review.

### Kill switch

- Standalone user message `STOP` / `緊急停止` / `KILL` — keyword-exact
  match in `kill_switch.is_keyword`; checked at every turn boundary.
- File flag: `KILL.flag` in repo root — out-of-band trigger.

## Disclosure Acknowledgements

If your report leads to a fix, you'll be credited in the commit message
and (with your permission) in the release notes. We don't run a bounty
program; the project is competition-scoped, not commercial.

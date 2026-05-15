# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository. **It is not loaded by the runtime agent** — the agent's constitution lives at `docs/00-agent-identity.md` and is read by `src/agent.py` as `system_prompt`.

## What we are building

**副手 (Fushou)** — a single-user Telegram-based AI delegate, built for the ASUS Agentic AI 2026 competition. Tagline: *"Earning autonomy, one confirm at a time."*

It is a **delegate, not an assistant**: write actions default to Tier-2 confirm; after the user confirms the same pattern N times the agent itself proposes escalation to auto-with-undo; every decision is replayable; absence mode lets the agent run unattended inside already-trust-elevated boundaries.

Three custom components are pitched as the moat (must be real code in `src/`, not LLM-only behavior):

- `replay.py` — Memory Replay engine (per-decision reasoning chain + counterfactual)
- `voice_scorer.py` — Voice-match scoring (sentence length, vocab overlap, structure; capped at 80% by design)
- `forensic.py` — Attack analyzer (domain Levenshtein, SPF/DKIM, injection pattern DB)

## Stack

- Python 3.11+ on WSL2 Ubuntu 22.04 (Linux-only target; design notes that Agent SDK is unstable on bare Windows).
- [Claude Agent SDK (Python)](https://docs.claude.com/api/agent-sdk), model `claude-opus-4-6-2026V2` via the ASUS-issued Azure endpoint (`ANTHROPIC_BASE_URL` + `ANTHROPIC_API_KEY` in `.env`).
- `python-telegram-bot` v21+ in **webhook** mode (not polling). Inline buttons drive the Tier-2 confirm UX.
- MCP servers built in-process via `claude_agent_sdk.create_sdk_mcp_server`: Gmail (IMAP + app password, *not* OAuth — explicit demo simplification), Bluesky (atproto SDK), and an internal `memory` server for L2/L3 writes.
- Heterogeneous routing: Opus 4.6 is the brain (6M token budget). Bulk drafting / batch summarization goes through `src/tools/kimi_bulk.py` (`should_offload` is the routing oracle). GPT-5.4 is fallback only.

## Build / run / test

```
make install    # python -m venv .venv && .venv/bin/pip install -e ".[dev]"
make run        # python -m src.main (Telegram webhook)
make test       # pytest -q
make test-one T=tests/test_foo.py::test_bar
make lint       # ruff check . && ruff format --check .
make format     # ruff format . && ruff check --fix .
make audit      # pip-audit  (run weekly per docs/04 §B)
```

`.env` is required (see `.env.example`); never commit it. The agent reads `USER_NAME` from env to substitute the `{USER_NAME}` placeholder in `docs/00-agent-identity.md` at load time (`src/agent.py:load_system_prompt`).

## Multi-platform chat layer

The codebase supports **Telegram and Microsoft Teams** as interchangeable front-ends. The platform is selected at startup via `CHAT_PLATFORM=telegram|teams` (default `telegram`). All handlers in `main.py` are platform-neutral: they take `IncomingText` / `IncomingButton` from the adapter and call back into `_ADAPTER.send_message` / `edit_message`. Adding a third platform = implement `ChatAdapter` (5 methods), add to `build_adapter`, done.

**Adapter contract** (`src/chat/base.py`):
- `send_message(user_id, text, keyboard=None) -> MessageRef` — returns an opaque ref for later editing
- `edit_message(ref, text, keyboard=None)` — replaces the message text + keyboard
- `register_text_handler(handler)` / `register_button_handler(prefix, handler)` / `register_command_handler(name, handler)` — register callbacks the adapter invokes
- `run()` — start the webhook server, blocks

`Button(label, callback_data)` and `Keyboard = list[list[Button]]` are platform-neutral. Adapters convert: Telegram → `InlineKeyboardMarkup`; Teams → Adaptive Card with `Action.Submit` per button (callback_data goes into `data.cb` on the Submit).

**Teams specifics** (`src/chat/teams.py`):
- No `botbuilder-core` dep — direct Bot Framework v3 HTTP via httpx + aiohttp webhook server (smaller dep graph, explicit control)
- Adaptive Cards rendered server-side; each row of buttons becomes one `ActionSet` so rows stack vertically
- **Proactive messages** require a persisted `ConversationReference` (Teams won't let bots DM strangers). `_ConversationStore` captures the reference on every incoming activity to `trust/teams_conversations.json` and replays it for proactive sends (escalation proposals, cost alerts, absence-replay-on-expiry). `send_message` to a never-seen user raises `RuntimeError` — fail loudly, not silently.
- MSAL-style `_TokenCache` reuses Bot Framework access tokens until 60s before expiry
- `handle_activity(dict)` is the public dispatch entry point — exposed so unit tests can drive it directly without standing up a webhook
- **Inbound JWT verification** (`src/chat/teams_auth.py`) is wired in by default. Every incoming POST's `Authorization: Bearer <JWT>` header is verified via PyJWT against Microsoft's Bot Framework JWKS (`https://login.botframework.com/v1/.well-known/openidconfiguration`, daily TTL). We check signature + issuer (`https://api.botframework.com`) + audience (= `TEAMS_APP_ID`) + expiry + `serviceurl` cross-check. JWKS rotation is handled by a force-refresh-on-unknown-kid retry. Disable for Bot Framework Emulator runs only via `TeamsAdapter(verify_inbound=False)` — never disable in production. `handle_request(auth_header, body)` is the full lifecycle entry point (verify → parse → dispatch), exposed for unit tests that need to cover the auth layer.

**Azure setup checklist** (operator work, not code):
1. Azure portal → create an **Azure Bot** resource; record `MicrosoftAppId`.
2. Add the **Microsoft Teams** channel to the bot.
3. On the bot's AAD app registration, **generate a client secret** → `TEAMS_APP_PASSWORD`.
4. Set the bot's messaging endpoint to `https://<your-host>/api/messages`.
5. Sideload a Teams app manifest pointing at this bot, or publish to your tenant.
6. Each target user must DM the bot once so we capture their `ConversationReference`.
7. Set `CHAT_PLATFORM=teams`, `TEAMS_APP_ID`, `TEAMS_APP_PASSWORD`, `ALLOWED_USERS=<aad-object-ids>` in `.env`.

`PORT` defaults to `3978` for Teams (Bot Framework convention) and `8080` for Telegram.

## Code architecture — the wiring you must understand to be productive

The Agent SDK is glued together in `src/agent.py:build_options`. Every tool call passes through three hook points; understanding which hook does what is the difference between fixing a real bug and breaking the safety contract.

1. **`PreToolUse` hook** (`agent.py:make_pre_tool_use_hook`) → calls `permissions.classify(tool_name, tool_input)` → returns `{ "permissionDecision": "allow" | "deny" | "ask", "permissionDecisionReason": ... }`. Tier 1 returns allow, Tier 3 returns deny with `refusal_message(reason)`, Tier 2 returns `"ask"` which hands control to the SDK's `can_use_tool` callback.

2. **`can_use_tool` callback** (`agent.py:make_can_use_tool`) → calls `tier2_confirm.await_decision(...)` → submits to a shared `ConfirmRegistry`, awaits a `Future`. `src/main.py` sends a Telegram inline-button message keyed by `confirm_id`; the button callback (`on_confirm_button`) calls `registry.resolve(id, approved)` to release the future. Default timeout 5 minutes → auto-deny. **The registry is one shared instance across the entire process** (`_REGISTRY` in `main.py`); the SDK side and the Telegram side both hold a reference.

3. **`PostToolUse` hook** (`agent.py:make_post_tool_use_hook`) → writes one JSONL event per call via `audit.AuditLogger`. Raw `subject` / `body` / `text` / `content` fields are hashed with `audit.sha256_short` before they hit disk (`agent.py:_hash_input`). Don't change this — raw text never goes into `logs/*.jsonl`, and is not stored anywhere else either; hash-and-discard is the deliberate posture (see docs/04 §E for rationale).

4. **`UserPromptSubmit` hook** (`agent.py:make_user_prompt_submit_hook`) → runs `forensic.find_injection_hits` on the incoming user prompt. Users are whitelisted, but pasted content (forwarded phishing, web copy) may contain injection patterns. On a hit we record to `logs/forensic.jsonl` with `source="user_prompt"` and prepend a warning banner to the prompt the agent sees via `hookSpecificOutput.additionalContext`. The hook does NOT block — the user is the principal authority; this is for visibility, not refusal.

The `Stop` hook was considered for defensive `turn_summary` emission but **not wired** — token totals would have to be shared with the inline path in `reply()`, and a double-emit would double-count cost. The inline path in `reply()` after the async loop is the sole emitter; if the caller raises after that, we lose the row for that turn. Acceptable trade-off given the SDK behaviour around Stop firing across error paths isn't easily verifiable from our environment.

**Subagents** (`agent.py:AGENT_DEFINITIONS`): two `AgentDefinition` instances are registered via `agents=` in `ClaudeAgentOptions`:
- **`voice-drafter`** — draft authoring in user voice, Read-only over `memories/*.md`, no write tools, returns draft text only
- **`forensic-analyzer`** — deep investigation of severity=block emails via Read + WebFetch + Grep over `logs/forensic.jsonl`, returns a verdict paragraph
Both subagents pass through the same `PreToolUse` permission classifier as the main agent — their effective tool set is `(their tools=) ∩ (Tier 1/2/3 rules)`. The main agent's `allowed_tools=["Agent", "Read", ...]` enables the SDK's `Agent` delegation tool.

**Session resume** — `reply()` returns `(text, sdk_session_id)`. `main.py:_SDK_SESSIONS` is a `SessionStore` (file-backed at `trust/sdk_sessions.json`) that captures the SDK's own session_id from the first `SystemMessage(subtype="init")` event; subsequent turns pass `resume_sdk_session=` so the agent has full conversation context across user messages **and across process restarts**. `agent_helpers.extract_sdk_session_id` tolerates both object and dict event shapes (and a nested `data["session_id"]` variant) — `tests/test_agent_helpers.py` pins every shape. `SessionStore.set` is a no-op when the value hasn't changed so we're not churning the file mid-session. Our internal `_SESSIONS[user_id]` UUID is unchanged and remains the audit-log session_id.

**`setting_sources=[]`** in `build_options` — prevents the SDK from auto-loading `.claude/` directories or `CLAUDE.md` into the runtime agent's context. The runtime agent's L1 is `docs/00-agent-identity.md` only, loaded explicitly via `load_system_prompt`. `CLAUDE.md` is dev guidance for Claude Code (the tool); leaking it into the agent's context would dilute the constitution.

Trust Curve is layered on top of (2): when `await_decision` is given a `TrustCurve`, every resolved confirm (and every timeout) flows into `curve.record(tool, args, approved=…)`, which buckets by `extract_key(tool, args)` (gmail → `to=<recipient>`, learning → `category=<x>`; free-form tools fall into `WILDCARD_KEY` and are never eligible for escalation). State persists at `trust/curves.json` and is loaded once at `main()` startup. `PatternState.is_eligible_for_escalation` fires at `ESCALATION_THRESHOLD = 5` consecutive confirms on MANUAL.

When eligibility fires, `await_decision` invokes the `on_eligible(tool, args, state)` callback (also threaded through `make_can_use_tool` and `build_options`). `main.py`'s `_make_eligible_handler` submits to a process-shared `EscalationRegistry` and posts a second Telegram message with three inline buttons (🤖 Auto / 🛎️ 繼續每次都問 / ❌ 永遠別自動 — callback prefix `esc:`). The `on_escalation_button` handler pops from the registry and calls `escalation.apply_action`, which mutates the curve via `curve.escalate` / `curve.defer` / `curve.lock_always_ask`. Don't paraphrase `apply_action`'s reply strings — `ESCALATED_TEMPLATE` / `DEFERRED_TEMPLATE` / `LOCKED_TEMPLATE` are pinned in `tests/test_escalation.py`.

Once a pattern reaches `AUTO_AUDITED+`, `can_use_tool` skips `await_decision` entirely and instead runs `undo_window.await_undo` (default 15s, configurable via `DEFAULT_UNDO_SECONDS`). The Telegram message shows a single `[↶ Undo (Ns)]` button (`undo:` callback). The implementation is delay-then-execute: we return Allow only after the timer expires, so pressing Undo before that returns Deny without ever having sent the email / posted / written. That sidesteps the entire "how do you unsend" problem.

Absence Mode (`src/absence_mode.py`) is detected in `main.on_message` before the agent is called. `parse_enter_command` requires BOTH a keyword (開會 / 外出 / 不在 / absence / afk / away) AND a duration (`N 小時` / `Nh` / `N 分鐘` / `Nm`) — either alone is too ambiguous and is rejected. The duration regex uses a negative lookahead `(?![a-zA-Z])` instead of `\b` so it works at CJK boundaries (`4 小時開會`). During an active window, `can_use_tool` short-circuits: `Level >= AUTO_AUDITED` auto-runs and records `AUTO_EXECUTED`; lower levels Deny and record `BLOCKED_MANUAL` / `BLOCKED_LOCKED`. The propose-escalation callback is suppressed (passed as `None` to `reply`) so the system doesn't drift toward "silence = approve". On `parse_exit_command` or detected expiry, the structured replay log is sent — followed by one `[✅ 沒問題] [🚫 不該自動]` feedback bubble per `AUTO_EXECUTED` decision (capped at `MAX_FEEDBACK_BUBBLES = 5`; older items are summarized as a count). The LOCK action calls `curve.lock_always_ask(tool, args)`. `AbsenceDecision.args` stores the raw tool args specifically so this targeting works.

`[🔍 Why this?]` is offered on AUTO_AUDITED+ undo-window messages (single row alongside `[↶ Undo (15s)]`). At message-send time, `WhyRegistry.submit(tool, args)` snapshots the decision; tapping the button later runs `replay.build_report_for_call(tool, args, tier)` which synthesizes a target dict (no audit event needed yet) and runs the full Memory Replay pipeline — similar cases from prior audit logs, L3 trigger matching, voice score on the draft text, forensic on email-shaped bodies, counterfactual. `WhyRegistry.get` does **not** pop so the user can re-read; the registry is FIFO-capped at 200 to bound memory.

Voice match is surfaced inline on every Tier-2 confirm prompt (`render_prompt(..., voice_corpus=)`). `main.py` calls `voice_corpus.load_user_corpus()` once per turn — cheap file I/O on L2 + the last 7 days of L4 `user[...]:` lines (capped at `MAX_CORPUS_CHARS = 20_000`, oldest trimmed first). Empty corpus → the voice line is omitted entirely rather than showing a scary 0%. Same `MAX_VOICE_PCT = 80` hard ceiling applies (uncanny-valley defense from docs/03).

Forensic runs automatically on every `mcp__gmail__read`. `tools/gmail_mcp.run_forensic_on_read(EmailFull)` calls `forensic.analyze(sender_domain, body)` and appends a row to `logs/forensic.jsonl` via `forensic_log.record` (bodies/subjects are hashed; no raw text). The agent sees a forensic banner (`✅` / `⚠️` / `🚨`) prepended to the formatted email it gets back, so it has the severity in-context before deciding how to respond. **Call point:** `tools/gmail_mcp.build_tools().read`. The `/status` command and `python -m src.cli forensic` both read this log via `forensic_log.read_recent`.

Kimi is exposed as `mcp__kimi__bulk_generate` (registered in `agent.build_options` when `enable_kimi=True`, default on). The tool re-checks `should_offload(kind, expected_output_chars, batch_size)` server-side so the agent can't bypass cost discipline by mis-routing. `OPUS_ONLY_KINDS` (`classify` / `safety`) are rejected with `is_error: True`. Classified Tier 1 in `permissions.py` (Kimi receives the same user data Opus already does; the resulting draft is still gated by Tier 2 on its eventual external write).

**Operator commands**: `/help` (full reference), `/trust` (dashboard), `/status` (trust + budget [lifetime + today's cost] + absence + last forensic warnings + pending registries), `/profile` (L2 contents, tail-truncated at 2000 chars), `/learnings` (most recent 5 L3 blocks via `replay.parse_learnings`), `/forensic <text>` (manual ad-hoc scan — sender domain set to `"unknown"`, typosquat check no-ops but injection regex DB and secret-shape scan run normally). All gated to ALLOWED_USERS. The same data is reachable offline via `python -m src.cli` — `trust` / `budget` / `forensic` / `replay` / `audit` / `scan-text` subcommands. The CLI is pure I/O; never mutates state, never sends Telegram messages.

Bluesky has the same forensic auto-scan as Gmail: every fetched post (timeline or search) runs through `scan_post_for_injection` (`bluesky_mcp.py`). Warning+ findings record to `logs/forensic.jsonl` with source `bluesky__feed`; info-level findings are skipped (the firehose is high-volume). Block-severity hits are summarized at the bottom of the formatted post list the agent receives.

`tools/*_mcp.py` import `claude_agent_sdk` lazily inside `build_tools` / `build_server` (not at module scope). This means pure helpers in each MCP module — `EmailFull`, `Post`, `run_forensic_on_read`, `scan_post_for_injection`, `should_offload`, formatters — are unit-testable without the SDK installed.

The MCP tool implementations follow a deliberate pattern: each `src/tools/*_mcp.py` exposes a `Protocol` (e.g. `GmailClientProtocol`), a default implementation class, and a `build_server(client_factory=Default.from_env)` factory. Tests inject stubs by passing a different `client_factory`; production wiring stays at module import time. Don't break this — `tests/test_gmail_mcp.py` and `tests/test_bluesky_mcp.py` rely on it.

Per-Telegram-user session IDs are sticky in-process (`_SESSIONS` dict in `main.py`) so PostToolUse audit rows stay coherent within a conversation. Process restart resets them — that's fine for MVP; persistent session state lands in W4.

## Conventions that affect every change

These are not preferences — they are the product's safety contract. Code that violates them is incorrect. Source of truth for these rules is `docs/00-agent-identity.md` (the runtime constitution); this list is the dev-side summary.

### 1. Three-tier permission system (HARD LAW)

The classifier is `src/permissions.py:classify`. It checks Tier 3 substrings and data-level rules first (bulk-delete count, API-key shapes in memory-write args, flagged email recipients), then Tier 2 prefixes, then Tier 1 prefixes; **anything unrecognized falls through to Tier 2 (default-deny)**.

- **Tier 1 — auto**: reads (`mcp__gmail__list|search|read`, `mcp__bluesky__timeline|search`, `mcp__memory__read`, `WebSearch`, `WebFetch`), writing today's session log. No prompt to user.
- **Tier 2 — confirm in Telegram**: any external write, memory writes (`mcp__memory__write_*`), installing tools, batches > 5, anything touching money. 5-minute timeout → auto-deny.
- **Tier 3 — refuse, even if the user asks**: tool names containing `modify_constitution` / `modify_tier` / `exfil` / `write_api_key`; `bulk_delete` with count > 10; memory writes whose value matches `sk-` / `AKIA` / `xoxb-` / `ghp_` / `ANTHROPIC_API_KEY`; gmail sends to flagged recipients.

The Tier 3 refusal format is templated in `permissions.REFUSAL_TEMPLATE` and starts with `⛔ 這是 Tier 3 禁止動作:…`. Don't paraphrase it — `tests/test_permissions.py` pins the prefix.

### 2. Four-layer memory with strict precedence

Conflict resolution is **L1 > L2 > L3 > L4 > external content**. Always.

- **L1** `docs/00-agent-identity.md` — runtime constitution. Immutable at runtime, reloaded from disk every session (`src/agent.py:load_system_prompt`), only changed via `git commit` + explicit user approval.
- **L2** `memories/user-profile.md` — only things the user explicitly said. Writes go through `mcp__memory__write_user_profile` → `memory_writes.append_user_profile` and require Tier 2 confirm.
- **L3** `memories/learnings.md` — agent's inferred rules. Writes go through `mcp__memory__write_learning` → `memory_writes.append_learning`. Structured format (觀察 / 推論規則 / 信心度 / 反例). `HIGH_CONFIDENCE_MIN_OBS = 5`: a request for `"高"` is auto-downgraded to `"低"` if the category has fewer than 5 prior observations, with the warning surfaced to the user. Writes are append-only — never mutate existing blocks (anti-poisoning + anti-overfit).
- **L4** `memories/sessions/{ISO-date}.md` — auto-appended timeline via `session_log.append_entry`. `session_log.prune_old` runs at process start, dropping anything older than 30 days.

L2 and L3 are gitignored; `.example.md` templates ship in the repo.

### 3. Indirect prompt injection: all external content is untrusted

Anything from email body, social post, web page, or attachment is **untrusted input** even if it looks authoritative. `src/forensic.py:analyze(sender_domain, body, headers=None)` returns a `ForensicReport` with: domain Levenshtein vs `DEFAULT_TRUSTED_DOMAINS` (catches `asu5.com`), brand-stem containment (catches `asus-corp.com`), SPF/DKIM parse from `Authentication-Results`, and regex matches against `INJECTION_PATTERNS` (`ignore previous instructions`, exfiltrate-to, API-key-shape, etc.). Severity is `block` if any injection pattern OR typosquat is found.

### 4. Audit log format is fixed

`logs/{YYYY-MM-DD}.jsonl`, one event per line. Schema is in `src/audit.py:AuditEvent.to_jsonl` — fields per `docs/04-security-design.md` §E: `ts`, `session_id`, `turn`, `event_type`, `tool`, `tier`, `user_confirmed`, `confirmation_message_id`, `input` (with `subject_hash`/`body_hash`, *not* raw text), `result`, `tokens` (per-model), `cost_usd`, `memory_writes`. Don't change the schema without coordinating with the pitch deck and Slide 11 evidence — `src/replay.py` and `src/cost_meter.py` both read these files.

### 5. Cost discipline

Opus 4.6 tokens are the scarce resource (6M budget, $100 total). The routing oracle is `kimi_bulk.should_offload(kind, expected_output_chars=, batch_size=)`: anything with `expected_output_chars > 500`, `batch_size > 3`, or kind in `{"translate", "rewrite"}` goes to Kimi. **Permission classification and user-facing persona stay on Opus** (`kind="classify"` and `kind="safety"` are explicitly `OPUS_ONLY_KINDS`).

`src/cost_meter.py:BudgetState.poll()` is called once per turn from `main.on_message`; it tallies `logs/*.jsonl` and fires one alert per crossing at 50% / 80% / 100% / 120%. At 120% (`halted`) `main.py` refuses new turns until the operator clears state.

For the tally to be meaningful, `agent.reply` accumulates `usage.input_tokens` / `usage.output_tokens` from every SDK event (best-effort — tolerant of either object or dict shape) and, at end-of-query, emits a `turn_summary` audit row via `AuditLogger.log_turn_summary` with `cost_meter.estimate_cost(model="opus", ...)`. Without this emission every audit event has `tokens=0` and the budget thresholds would never trip. Pricing constants live in `cost_meter.PRICES_USD_PER_MTOK` (input/output rates for opus/kimi/gpt); adjust there when a model is repriced. `Tests/test_cost_meter.py` pins the dict shape, not specific numbers, so price moves don't churn the suite.

Cache discipline: the Claude Agent SDK automatically caches the `system_prompt` (= `docs/00-agent-identity.md`) and tool schemas when they're stable across calls. The contract we maintain on our side: load `system_prompt` from the same file every call (`load_system_prompt`), and never mutate tool schemas mid-session. L2/L3 are appended to via `memory_writes`, never rewritten in place, so cache invalidation stays predictable. If we ever need explicit `cache_control: ephemeral` markers (e.g. for non-SDK paths), they live below this abstraction — don't add them to `build_options` without a measured reason.

### 6. Kill switch

`STOP` / `緊急停止` / `KILL` as a standalone user message → `kill_switch.triggered` returns True → `main.on_message` replies `kill_switch.stop_reply()` and drops the turn before the agent is called. A `KILL.flag` file on disk does the same out-of-band. Checked at every turn boundary.

## Tests

Pytest is configured with `asyncio_mode = "auto"` (see `pyproject.toml`). Test files mirror modules 1:1: `tests/test_permissions.py`, `tests/test_replay.py`, `tests/test_audit.py`, etc. The MCP-server tests (`test_gmail_mcp.py`, `test_bluesky_mcp.py`, `test_memory_mcp.py`) use the protocol/stub pattern described above — never make a real IMAP / atproto / network call from tests.

**Lazy SDK imports** — `tools/*_mcp.py` AND `agent.py` import `claude_agent_sdk` only inside the functions that actually construct SDK objects. `agent.py` uses `TYPE_CHECKING` for the type annotations and lazy-imports at the call sites (`build_options`, `make_can_use_tool`, `reply`). Pure helpers in `agent_helpers.py` (`load_system_prompt`, `hash_input`, `accumulate_tokens`, `extract_sdk_session_id`) are SDK-free. Net effect: the **entire test suite (including E2E)** runs locally without `claude_agent_sdk` installed; CI installs the SDK and runs the SDK-dependent files in addition.

**End-to-end test suite** (`tests/test_e2e_flows.py` + `tests/_fake_adapter.py`) — a `FakeChatAdapter` implements `ChatAdapter` in-memory; tests monkeypatch every `main.py` module global to fresh tmp-backed instances and stub `main.reply` to a deterministic coroutine. 17 scenarios cover: text round-trip, allowed-user gating, kill-switch short-circuit (Chinese + English keywords), absence enter/exit/double-enter, every slash command, SDK session capture + resume across turns + cross-restart via SessionStore, agent exception → error message, audit_session_id allocation/persistence semantics. These catch wiring defects the unit tests miss.

## CI

GitHub Actions workflows in `.github/workflows/`:

- **`ci.yml`** — on push/PR to `main`, runs ruff check + `ruff format --check` + `pytest -q` against the Python 3.11 + 3.12 matrix on `ubuntu-latest`. Pip cache keyed on `pyproject.toml`. Concurrency-grouped so a fast-follow push cancels the previous run for the same ref. Sets `USER_NAME=ci-test` + `ANTHROPIC_MODEL=claude-opus-4-6-2026V2` in the env so the suite is self-contained.
- **`audit.yml`** — weekly (`cron: "0 3 * * 1"`) + `workflow_dispatch`, runs `pip-audit` per docs/04 §B. Single Python 3.11 job.

Both workflows install `pip install -e ".[dev]"` so the full dependency graph (including `claude-agent-sdk`) is present — the SDK-dependent test files run in CI even though they can't run locally without the SDK installed.

## Repo layout

```
/
├── README.md
├── CLAUDE.md                      ← this file (NOT loaded at runtime)
├── pyproject.toml                 ← project name "fushou", py>=3.11, ruff + pytest config
├── .env.example                   ← copy to .env (gitignored)
├── Makefile
├── src/
│   ├── main.py                    ← Telegram webhook entry; ConfirmRegistry + BudgetState live here
│   ├── agent.py                   ← Agent SDK orchestration; PreToolUse / PostToolUse / can_use_tool wiring
│   ├── permissions.py             ← Tier classification (pure, unit-tested)
│   ├── tier2_confirm.py           ← ConfirmRegistry + await_decision (no Telegram dep — testable offline)
│   ├── audit.py                   ← AuditLogger writing logs/*.jsonl
│   ├── cost_meter.py              ← Threshold engine + BudgetState (per-process alert dedup)
│   ├── kill_switch.py             ← STOP keywords + KILL.flag check
│   ├── session_log.py             ← L4 append + 30-day prune
│   ├── memory_writes.py           ← L2/L3 append, anti-overfit confidence downgrade
│   ├── trust_curve.py             ← Trust Escalation Curve — per-(tool, key) state, 5-level ladder
│   ├── escalation.py              ← propose-escalation UX (3-button Telegram message + curve mutators)
│   ├── undo_window.py             ← 15s [↶ Undo] window for AUTO_AUDITED+ auto-executions
│   ├── absence_mode.py            ← time-windowed self-running + structured replay log
│   ├── absence_feedback.py        ← per-decision [✅ 沒問題] [🚫 不該自動] bubbles after absence ends
│   ├── why_button.py              ← WhyRegistry for [🔍 Why this?] — snapshots a decision for replay
│   ├── voice_corpus.py            ← build user-writing corpus from L2 + recent L4 user lines
│   ├── forensic_log.py            ← append-only logs/forensic.jsonl (written by gmail_mcp auto-scan)
│   ├── cli.py                     ← `python -m src.cli ...` ops tool (trust / audit / forensic / replay)
│   ├── memory_inspect.py          ← read-only L2/L3 renderers for /profile and /learnings
│   ├── agent_helpers.py           ← pure helpers from agent.py (load_system_prompt / hash_input / accumulate_tokens / extract_sdk_session_id)
│   ├── session_store.py           ← file-backed user_id → SDK session_id for cross-restart context resume
│   ├── http_retry.py              ← async-httpx retry-with-backoff (used by Teams outbound + token cache)
│   └── chat/
│       ├── base.py                ← ChatAdapter ABC + Button / Keyboard / IncomingText / IncomingButton
│       ├── telegram.py            ← TelegramAdapter (python-telegram-bot webhook)
│       ├── teams.py               ← TeamsAdapter (Bot Framework v3 HTTP + Adaptive Cards)
│       └── teams_auth.py          ← inbound JWT verification (PyJWT + JWKS cache)
│   ├── replay.py                  ← Memory Replay (moat) — composes voice_scorer + forensic + log search
│   ├── voice_scorer.py            ← Voice-match scorer (moat) — 80% hard cap
│   ├── forensic.py                ← Forensic analyzer (moat) — Levenshtein + injection patterns
│   └── tools/
│       ├── gmail_mcp.py           ← IMAP/SMTP; `read` auto-runs forensic.analyze + forensic_log.record
│       ├── bluesky_mcp.py         ← atproto, same shape
│       ├── memory_mcp.py          ← L2/L3 write tools (Tier 2)
│       └── kimi_bulk.py           ← should_offload() oracle + `mcp__kimi__bulk_generate` MCP tool
├── memories/
│   ├── user-profile.example.md    ← L2 template (committed); real file gitignored
│   ├── learnings.example.md       ← L3 template (committed); real file gitignored
│   └── sessions/                  ← L4: auto session logs, all gitignored
├── trust/curves.json              ← Trust Dashboard state (gitignored, runtime; written by trust_curve.py)
├── logs/                          ← AuditLogger output (gitignored)
├── tests/                         ← 1:1 with src/ modules
├── .github/workflows/             ← ci.yml (push/PR) + audit.yml (weekly pip-audit)
└── docs/00..08.md                 ← design + roadmap + build status + demo recording
```

## Development branch

`main` is the integration branch. New work for W6–W7 should branch from `main` and PR back.

## Roadmap anchors

W1 (5/13–5/19) — Telegram bot echo + Agent SDK hello-world + repo bootstrap. W2 — Gmail read + summarize, L4 session log, Kimi tool wrapper. W3 — Bluesky, Tier 2 confirm UX, Tier 3 hard-block, L2/L3 writes, AuditLogger, CostMeter. W4 — pitch deck + pre-recorded demo (6/12 submission). W5 — voice_scorer / forensic / replay (the three moat components) + injection demo. W6 — final demo video (6/30). W7 — interview prep. Scope-cut order if behind: Bluesky → Tier 3 full enforcement → live CostMeter dashboard. Floor: Scene 1 + Scene 4 + Scene 5 must work.

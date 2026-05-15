# 07 — Build Status (refreshed 2026-05-14, post-W5 push)

**Purpose**: every claim in `docs/06-pitch-outline.md` and `docs/02-demo-script.md` should
either point at a file:line in this repo or be honestly marked aspirational. This file
is the index. Reviewer can audit; operator can record without bluffing.

> Stack/architecture are described in `docs/01-architecture.md`. Safety contract is
> `docs/00-agent-identity.md` (L1 constitution, loaded by `src/agent.py`).

## Test count snapshot

`pytest -q` → **341 passed** (SDK-independent subset; full suite incl.
SDK-dependent MCP tests runs in CI). `ruff check .` + `ruff format --check .` → clean.

## What's built (W1–W3 complete)

### Tier system (HARD LAW)

| Layer | File:line | Test | PR |
|---|---|---|---|
| Tier 1/2/3 classifier (pure) | `src/permissions.py` | `tests/test_permissions.py` (8 cases) | #3 |
| PreToolUse hook → permissionDecision | `src/agent.py:make_pre_tool_use_hook` | `tests/test_agent_hooks.py` (3 cases) | #4 |
| Tier-3 fixed refusal text | `src/permissions.py:REFUSAL_TEMPLATE` | tested as part of classify | #3 |
| Tier-3 API-key shape scan | `src/permissions.py:API_KEY_SHAPES` | `test_permissions.py` (4 cases incl note/observation/value fields) | #3 + #8 |
| Tier-3 bulk_delete > 10 | `src/permissions.py:TIER3_BULK_DELETE_THRESHOLD` | tested | #3 |
| Tier-3 flagged-recipient | `src/permissions.py:classify` | tested | #3 |

### Tier-2 confirm UX (Slide 5 — Trust Escalation)

| Piece | File:line | Test |
|---|---|---|
| ConfirmRegistry (asyncio.Future per pending) | `src/tier2_confirm.py:ConfirmRegistry` | `tests/test_tier2_confirm.py` |
| 5-minute timeout → auto-deny | `src/tier2_confirm.py:DEFAULT_CONFIRM_TIMEOUT = 300` | `test_await_decision_times_out_to_deny` |
| Render prompt (動作/影響/草稿/確認? + voice match line) | `src/tier2_confirm.py:render_prompt` | `test_render_prompt_*` incl. voice score tests |
| `can_use_tool` callback bridges SDK→adapter | `src/agent.py:make_can_use_tool` | `tests/test_agent_hooks.py` (CI-only, needs SDK) |
| Inline buttons (platform-neutral) | `src/main.py:_confirm_keyboard` + `on_confirm_button` | adapter-side tests |
| Stale tap after timeout marked "(已過期)" | `src/main.py:on_confirm_button` | `tests/test_tier2_confirm.py:test_resolve_after_timeout_is_safe` |

### Trust Escalation Curve (Slide 5, second half) — now ✅ built

| Piece | File:line | Test |
|---|---|---|
| Per-(tool, key) state with 5-level Level enum | `src/trust_curve.py:Level` | `tests/test_trust_curve.py` (22 cases) |
| Pattern key extraction (gmail→to=, learning→category=) | `src/trust_curve.py:extract_key` | tested per tool family |
| `record(tool, args, approved=)` updates streak + counts | `src/trust_curve.py:TrustCurve.record` | streak + reset on reject + always-ask sticky |
| `is_eligible_for_escalation` after 5 consecutive ✅ | `src/trust_curve.py:PatternState` | threshold + WILDCARD_KEY skip + higher-level skip |
| JSON persistence at `trust/curves.json` | `src/trust_curve.py:TrustCurve.load/save` | roundtrip + legacy payload tests |
| Propose-escalation 3-button UX | `src/escalation.py` | `tests/test_escalation.py` (13 cases) |
| 15s undo window for AUTO_AUDITED+ | `src/undo_window.py` | `tests/test_undo_window.py` (12 cases) |
| Telegram/Teams keyboards for escalation + undo + why | `src/main.py:_escalation_keyboard, _undo_keyboard` | adapter contract tests |
| Dashboard via `/trust` + `python -m src.cli trust` | `src/main.py:on_trust_command`, `src/cli.py:cmd_trust` | `tests/test_cli.py` |

### Memory L1–L4 (Slide 6 — Memory Replay)

| Layer | File:line | Test | PR |
|---|---|---|---|
| L1 constitution loaded each session | `src/agent.py:load_system_prompt` | `tests/test_system_prompt.py` (2 cases) | #1 + #2 |
| L2 `memories/user-profile.md` append | `src/memory_writes.py:append_user_profile` | `tests/test_memory_writes.py` | #8 |
| L3 `memories/learnings.md` four-field block | `src/memory_writes.py:append_learning` | 12 cases incl threshold | #8 |
| L3 anti-overfit: "高" needs ≥5 obs, else downgrade + warn | `src/memory_writes.py:HIGH_CONFIDENCE_MIN_OBS` | `test_append_learning_high_*` (3 cases) | #8 |
| L3 append-only (no overwrite) | covered by `test_writes_never_overwrite_existing_content` | tested | #8 |
| L4 session log + 30-day prune | `src/session_log.py` | `tests/test_session_log.py` (4 cases) | #3 |
| L1 > L2 > L3 > L4 > external precedence | written into `docs/00-agent-identity.md` §記憶污染防護 | declarative; agent observes via system prompt | #1 |

### Replay engine (Slide 6 [Why this?]) — now ✅ button is wired

| Piece | File:line | Test |
|---|---|---|
| Compose audit + L3 + voice + forensic into one report | `src/replay.py:build_report` | `tests/test_replay.py` |
| Build report for a CURRENT decision (no audit row yet) | `src/replay.py:build_report_for_call` | 5 cases — synthesized target + similar-case match |
| L3 markdown parser → typed entries | `src/replay.py:parse_learnings` | tested |
| Similar-cases lookup (same tool name, recency-ordered) | `src/replay.py:find_similar_cases` | tested |
| Category match L3 ↔ tool args | `src/replay.py:match_l3_for_event` | tested |
| Counterfactual phrasing by Tier | `src/replay.py:_counterfactual` | tested |
| `ReplayReport.render()` | `src/replay.py:ReplayReport` | render tests |
| **[🔍 Why this?] button on undo-window messages** | `src/why_button.py` + `src/main.py:on_why_button` | `tests/test_why_button.py` (7 cases) |
| WhyRegistry FIFO-capped at 200 (memory bound) | `src/why_button.py:WhyRegistry` | eviction test |

### Indirect prompt injection (Slide 8 — Forensic Security)

| Piece | File:line | Test |
|---|---|---|
| All-external-input-untrusted policy | docs/00 §防 Indirect Prompt Injection | declarative |
| Tier-3 enforcement when external content tries Tier 2/3 | `src/permissions.py:classify` runs on every tool call | `tests/test_permissions.py` |
| Audit log records tool calls with hashed input | `src/audit.py:AuditEvent` + `src/agent_helpers.hash_input` | `tests/test_audit.py` + `tests/test_agent_helpers.py` |

### Forensic analyzer (Slide 8 — domain Levenshtein, SPF/DKIM, injection DB)

| Piece | File:line | Test |
|---|---|---|
| Domain Levenshtein + brand-stem typosquat heuristic | `src/forensic.py:analyze_domain` | `tests/test_forensic.py` (33 cases incl. edge cases) |
| Injection pattern DB (8 patterns) | `src/forensic.py:INJECTION_PATTERNS` | case-insensitive + tuple-not-list contract |
| SPF / DKIM header parser (when raw headers supplied) | `src/forensic.py:analyze_auth_headers` | softfail-as-fail + missing-claim handling |
| Top-level `analyze(domain, body, headers)` → ForensicReport with severity | `src/forensic.py:analyze` | severity-ranking (block > warning) |
| `ForensicReport.render()` | `src/forensic.py:ForensicReport` | render tests |
| **Auto-scan on `gmail_mcp.read`** — banner prepended to body, finding logged | `src/tools/gmail_mcp.py:run_forensic_on_read` | (driven via `test_forensic_log` + integration) |
| **Auto-scan on `bluesky_mcp.timeline / search`** — every post scanned, warning+ logged | `src/tools/bluesky_mcp.py:scan_post_for_injection` | `tests/test_bluesky_forensic.py` (5 cases) |
| `logs/forensic.jsonl` append-only forensic stream | `src/forensic_log.py` | `tests/test_forensic_log.py` (8 cases) |
| Manual `/forensic <text>` command | `src/main.py:on_forensic_command` | command-handler tests |
| `python -m src.cli forensic --min-severity warning` | `src/cli.py:cmd_forensic` | `tests/test_cli.py` |

> **DNS-based SPF/DKIM verification** still needs a live DNS call. Accepted out of
> scope: the analyzer parses Authentication-Results headers when supplied (most
> mail providers add this); falls back to "unverified" otherwise.

### Voice match (Slide 7) — now also auto-displayed in confirm prompts

| Piece | File:line | Test |
|---|---|---|
| Sentence-length similarity | `src/voice_scorer.py:_avg_sentence_length` + `_similarity_from_ratio` | `tests/test_voice_scorer.py` (17 cases) |
| Vocab overlap via Jaccard on mixed Chinese-bigrams + ASCII-words | `src/voice_scorer.py:_tokens` + `_jaccard` | mixed-language tests |
| Structure similarity (sentences-per-message profile) | `src/voice_scorer.py:score` | structure test |
| 80% hard ceiling (uncanny-valley guard) | `src/voice_scorer.py:MAX_VOICE_PCT = 80` | `test_identical_text_caps_at_80` + `test_overall_never_exceeds_max` |
| **User corpus from L2 + recent L4** | `src/voice_corpus.py:load_user_corpus` | `tests/test_voice_corpus.py` (8 cases) |
| **Voice match auto-shown in Tier-2 confirm prompts** | `src/tier2_confirm.py:render_prompt(voice_corpus=)` | tests pin the line format + skip-when-empty contract |

### Absence Mode (Slide 9) — now ✅ built

| Piece | File:line | Test |
|---|---|---|
| Time-windowed `AbsenceMode` with active/expired/exit/record | `src/absence_mode.py:AbsenceMode` | `tests/test_absence_mode.py` (28 cases) |
| Bilingual command parser (`我接下來 4 小時開會` / `afk 2h`) | `parse_enter_command` / `parse_exit_command` | substring rejection, CJK regex correctness |
| `can_use_tool` short-circuit during absence (AUTO_AUDITED+ allowed, lower deferred) | `src/agent.py:make_can_use_tool` absence branch | covered by integration |
| Structured replay log on exit | `AbsenceMode.render_replay` | empty + with-decisions + counts |
| Per-decision `[✅ 沒問題] [🚫 不該自動]` follow-up bubbles | `src/absence_feedback.py` + `src/main.py:_dispatch_absence_feedback` | `tests/test_absence_feedback.py` (7 cases) |
| Cap at 5 bubbles, summarise overflow | `src/main.py:MAX_FEEDBACK_BUBBLES` | integration |

### Cost discipline (Slide 12)

| Piece | File:line | Test |
|---|---|---|
| Routing oracle (should_offload) | `src/tools/kimi_bulk.py:should_offload` | `tests/test_kimi_bulk.py` |
| Kimi HTTP wrapper (lazy, OpenAI-compatible) | `src/tools/kimi_bulk.py:call_kimi` | env-missing path |
| **Kimi as MCP tool `bulk_generate`** with server-side route check | `src/tools/kimi_bulk.py:build_tools` | refuses OPUS_ONLY_KINDS |
| Audit log per-call cost_usd | `src/audit.py:AuditEvent.cost_usd` | `tests/test_audit.py` |
| **Pricing helpers (USD/Mtok for opus/kimi/gpt)** | `src/cost_meter.py:PRICES_USD_PER_MTOK`, `estimate_cost` | `tests/test_cost_meter.py` |
| **`turn_summary` audit row written by `agent.reply`** | `src/audit.py:log_turn_summary` + `src/agent.py:reply` | roundtrip via usage_summary |
| **Token accumulation across SDK events** (object + dict shapes) | `src/agent_helpers.py:accumulate_tokens` | `tests/test_agent_helpers.py` |
| CostMeter usage tally | `src/cost_meter.py:usage_summary` | tested |
| 50 / 80 / 100 / 120% threshold alerts | `src/cost_meter.py:check_thresholds` | tested |
| Per-turn alert dispatch through adapter | `src/main.py:on_text` (post-reply poll) | `tests/test_cost_meter.py` |
| 120% halt refuses new turns | `src/main.py:on_text` (top-of-turn halt) | tested |
| Today's-cost line in `/status` | `src/main.py:_render_status` (usage_summary(since=today, until=today)) | manual |
| Cache discipline (system_prompt + tool schemas) | SDK handles automatically when system_prompt/tool schemas stable; `agent_helpers.load_system_prompt` reads same file each session | declarative |

### Channels (multi-platform)

| Channel | File | Adapter contract | Test |
|---|---|---|---|
| **ChatAdapter abstraction** | `src/chat/base.py` | ABC + Button/Keyboard/IncomingText/IncomingButton | `tests/test_chat_base.py` (5 cases) |
| Telegram (webhook + InlineKeyboardMarkup) | `src/chat/telegram.py:TelegramAdapter` | `secret_token` echo header | live + adapter contract |
| Microsoft Teams (Bot Framework v3 + Adaptive Cards) | `src/chat/teams.py:TeamsAdapter` | direct HTTP, no botbuilder-core | `tests/test_chat_teams.py` (24 cases) |
| **Teams JWT verification** | `src/chat/teams_auth.py:verify_token` | PyJWT + JWKS 24h TTL + force-refresh on unknown kid + serviceurl cross-check | `tests/test_teams_auth.py` (12 cases, RSA keypair fixtures) |
| Teams ConversationReference persistence (proactive sends) | `src/chat/teams.py:_ConversationStore` | file-backed `trust/teams_conversations.json` | roundtrip tests |
| Teams outbound token cache + rotation defense | `src/chat/teams.py:_TokenCache` (with `invalidate()`) | MSAL-style 60s grace | invalidate idempotent + drop tests |
| Adapter selected at startup via `CHAT_PLATFORM` env | `src/main.py:build_adapter` | dispatch | manual |
| Gmail (IMAP + SMTP, app password) | `src/tools/gmail_mcp.py` | + auto-forensic on read | `tests/test_gmail_mcp.py` (CI; lazy SDK import) |
| Bluesky (atproto) | `src/tools/bluesky_mcp.py` | + per-post forensic scan | `tests/test_bluesky_mcp.py` + `tests/test_bluesky_forensic.py` |
| Memory MCP | `src/tools/memory_mcp.py` | write_user_profile + write_learning | `tests/test_memory_mcp.py` |

### Safety primitives

| Piece | File:line | Test |
|---|---|---|
| Kill switch (STOP / 緊急停止 / KILL keywords + KILL.flag) | `src/kill_switch.py` | `tests/test_kill_switch.py` |
| Audit log JSONL schema (docs/04 §E) — `tool_call` + `turn_summary` events | `src/audit.py` | `tests/test_audit.py` (11 cases) |
| Subject/body hashed before audit | `src/agent_helpers.py:hash_input` + `HASHABLE_FIELDS` frozenset | `tests/test_agent_helpers.py` (17 cases) |
| ALLOWED_USERS whitelist (per-platform IDs) | `src/main.py:ALLOWED` + adapter `_read_allowed` | manual + adapter tests |
| Memories gitignored, `.example` committed | `.gitignore` + `memories/*.example.md` | filesystem |
| **`Dockerfile` + `.dockerignore` for production** | non-root user, two-stage build, tini PID 1 | container-build smoke (not in CI yet) |
| **`SECURITY.md` disclosure policy** | repo root | n/a |
| **CI workflows** (ruff + pytest matrix + weekly pip-audit) | `.github/workflows/{ci,audit}.yml` | covered by CI itself |

## Roadmap status by week

| Week | Item | Status | Where |
|---|---|---|---|
| W1 | Telegram bot echo | ✅ | `src/main.py` |
| W1 | Agent SDK hello-world | ✅ | `src/agent.py:reply` |
| W1 | Repo bootstrap | ✅ | `pyproject.toml`, `Makefile`, `.env.example`, `LICENSE` |
| W2 | Gmail read + summarize | ✅ | PR #7 |
| W2 | L4 session log | ✅ | PR #3 |
| W2 | Kimi tool wrapper | ✅ | PR #3 (routing heuristic + HTTP wrapper) |
| W3 | Bluesky | ✅ | PR #9 |
| W3 | Tier 2 confirm UX | ✅ | PR #6 |
| W3 | Tier 3 hard-block | ✅ | PR #3 + #4 |
| W3 | L2/L3 writes | ✅ | PR #8 |
| W3 | AuditLogger | ✅ | PR #3 + #4 |
| W3 | CostMeter | ✅ | PR #5 + #10 |
| W4 | Pitch deck | ⏳ in progress | docs/06 |
| W4 | Pre-recorded demo | ⏳ in progress | docs/08 |
| W5 | Forensic analyzer + injection demo | ✅ | `src/forensic.py` + auto-trigger in `gmail_mcp.read` / `bluesky_mcp` |
| W5 | Voice scorer | ✅ | `src/voice_scorer.py` + `voice_corpus.py` (auto-shown in confirm prompts) |
| W5 | Replay engine | ✅ | `src/replay.py` + `[🔍 Why this?]` button via `why_button.py` |
| **W5+** | Trust Curve auto-promotion | ✅ | `trust_curve.py` + `escalation.py` + `undo_window.py` |
| **W5+** | Absence mode | ✅ | `absence_mode.py` + `absence_feedback.py` |
| **W5+** | Microsoft Teams support | ✅ | `chat/teams.py` + `chat/teams_auth.py` (Bot Framework + JWT verification) |
| **W5+** | CI workflows | ✅ | `.github/workflows/{ci,audit}.yml` |
| **W5+** | Production deployment scaffolding | ✅ | `Dockerfile` + `.dockerignore` + `SECURITY.md` |
| W6 | Final demo video | 🔜 — | — |
| W7 | Interview prep | 🔜 — | — |

## What we are honest about

For the 6/12 written submission, every Slide-numbered pitch claim has running
code that can be audited:

- **Trust Escalation Curve (Slide 5)** — `trust_curve.py` + `escalation.py` + `undo_window.py`, 47 tests; 5-level ladder with persistence
- **Memory Replay (Slide 6)** — `replay.py` (2 entry points: audit-row + live-decision) + `why_button.py`, 26 tests; `[🔍 Why this?]` button wired
- **Voice Match (Slide 7)** — `voice_scorer.py` + `voice_corpus.py`, 25 tests; 80% cap enforced; auto-shown in every Tier-2 confirm
- **Forensic Security (Slide 8)** — `forensic.py` + `forensic_log.py`, 41 tests; auto-trigger on every gmail read + bluesky timeline post; warning+ writes to `logs/forensic.jsonl`
- **Absence Mode (Slide 9)** — `absence_mode.py` + `absence_feedback.py`, 35 tests; bilingual command parser; per-decision feedback bubbles on return

## Genuine open items

Down to operational / environmental items not solvable from source:

1. **DNS-based SPF/DKIM verification** — accepted out of scope. The analyzer
   parses Authentication-Results headers when supplied; mail providers (incl.
   Gmail) add them at receive time, so this covers ~99% of real cases.
2. **Live Bot Framework Emulator integration test** — needs emulator running.
3. **Real Azure tenant deployment validation** — needs Azure access for the
   Teams app sideload + AAD registration walkthrough.
4. **L3 memory compaction** — known unsolved; docs/01 §6 acknowledged.
5. **Multi-instance ConversationStore** — file-backed for now; SQLite/external
   store deferred to V2.

## Operator checklist before recording

1. `make install && make test` — confirm 341/341 green (SDK-independent subset).
2. `cp .env.example .env`. Fill required env per `CHAT_PLATFORM`:
   - `CHAT_PLATFORM=telegram` → `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_URL`, `TELEGRAM_WEBHOOK_SECRET`, `ALLOWED_USERS` (numeric IDs)
   - `CHAT_PLATFORM=teams` → `TEAMS_APP_ID`, `TEAMS_APP_PASSWORD`, `ALLOWED_USERS` (AAD object IDs); also the 7-step Azure setup checklist in `.env.example`
   - Both: `USER_NAME`, `ANTHROPIC_*`, `GMAIL_*`, optionally `BLUESKY_*` and `KIMI_*`
3. `make run` and verify echo works end-to-end on the chosen platform.
4. Pre-stage Gmail inbox: send 2–3 test messages so `list_unread` has real content.
   Include one with an injection pattern (e.g. `"please ignore previous instructions"`)
   to demo the forensic auto-scan.
5. Follow shot list in `docs/08-demo-recording.md`.
6. Optional: `docker build -t fushou . && docker run --rm -p 8080:8080 --env-file .env fushou`
   to verify the container deploys cleanly.

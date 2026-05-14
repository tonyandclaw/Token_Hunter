# 07 — Build Status (W5 snapshot, 2026-05-14)

**Purpose**: every claim in `docs/06-pitch-outline.md` and `docs/02-demo-script.md` should
either point at a file:line in this repo or be honestly marked aspirational. This file
is the index. Reviewer can audit; operator can record without bluffing.

> Stack/architecture are described in `docs/01-architecture.md`. Safety contract is
> `docs/00-agent-identity.md` (L1 constitution, loaded by `src/agent.py`).

## Test count snapshot

`make test` → **156 passed** as of branch `claude/w5-voice-scorer`.
`make lint` → clean (ruff check + format).

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

| Piece | File:line | Test | PR |
|---|---|---|---|
| ConfirmRegistry (asyncio.Future per pending) | `src/tier2_confirm.py:ConfirmRegistry` | `tests/test_tier2_confirm.py` (10 cases) | #6 |
| 5-minute timeout → auto-deny | `src/tier2_confirm.py:DEFAULT_CONFIRM_TIMEOUT = 300` | `test_await_decision_times_out_to_deny` | #6 |
| Render prompt (動作/影響/草稿/確認?) | `src/tier2_confirm.py:render_prompt` | `test_render_prompt_*` (3 cases) | #6 |
| `can_use_tool` callback bridges SDK→Telegram | `src/agent.py:make_can_use_tool` | `tests/test_agent_hooks.py:test_can_use_tool_*` (3 cases) | #6 |
| Telegram inline buttons (✅/❌, callback_data `t2:<id>:yes\|no`) | `src/main.py:_confirm_keyboard`, `on_confirm_button` | manual (live Telegram) | #6 |
| Stale tap after timeout marked "(已過期)" | `src/main.py:on_confirm_button` | `tests/test_tier2_confirm.py:test_resolve_after_timeout_is_safe` | #6 |

> **Trust Curve auto-promotion (Slide 5)** — pattern detection / N-confirm escalation is
> NOT yet implemented. Currently every Tier-2 call confirms every time. PR #11+.

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

### Replay engine (Slide 6 [Why this?])

| Piece | File:line | Test | PR |
|---|---|---|---|
| Compose audit + L3 + voice + forensic into one report | `src/replay.py:build_report` | `tests/test_replay.py` (15 cases) | (this branch) |
| L3 markdown parser → typed entries | `src/replay.py:parse_learnings` | 3 cases | (this branch) |
| Similar-cases lookup (same tool name, recency-ordered) | `src/replay.py:find_similar_cases` | 3 cases | (this branch) |
| Category match L3 ↔ tool args | `src/replay.py:match_l3_for_event` | 1 case | (this branch) |
| Counterfactual phrasing by Tier | `src/replay.py:_counterfactual` | 1 case | (this branch) |
| `ReplayReport.render()` for Telegram | `src/replay.py:ReplayReport` | `test_report_render_contains_decision_block` | (this branch) |

> **[Why this?] Telegram inline-button UX** is the only piece still aspirational —
> `replay.build_report(event_index)` returns a fully-rendered text block; wiring a
> button to call it is mechanical and lands in a follow-up.

### Indirect prompt injection (Slide 8 — Forensic Security)

| Piece | File:line | Test | PR |
|---|---|---|---|
| All-external-input-untrusted policy | docs/00 §防 Indirect Prompt Injection | declarative | #1 |
| Tier-3 enforcement when external content tries Tier 2/3 | `src/permissions.py:classify` runs on every tool call | tested | #3 |
| Audit log records tool calls with hashed input | `src/audit.py:AuditEvent` | 4 cases | #3 + #4 |


### Forensic analyzer (Slide 8 — domain Levenshtein, SPF/DKIM, injection DB)

| Piece | File:line | Test | PR |
|---|---|---|---|
| Domain Levenshtein + brand-stem typosquat heuristic | `src/forensic.py:analyze_domain` | `tests/test_forensic.py` (7 cases) | (this branch) |
| Injection pattern DB (8 patterns: ignore-previous, send-credentials, exfiltrate-to, role-override, system-override, forget-everything, api-key-leak, disregard-above) | `src/forensic.py:INJECTION_PATTERNS` | 6 cases | (this branch) |
| SPF / DKIM header parser (when raw headers supplied) | `src/forensic.py:analyze_auth_headers` | 3 cases | (this branch) |
| Top-level `analyze(domain, body, headers)` → ForensicReport with severity (info/warning/block) | `src/forensic.py:analyze` | 4 cases | (this branch) |
| `ForensicReport.render()` for Telegram | `src/forensic.py:ForensicReport` | 2 cases | (this branch) |

> **DNS-based SPF/DKIM verification** still needs a live IMAP fetch with raw
> headers; the analyzer surfaces "unverified" when headers aren't supplied
> rather than guessing. The injection DB + typosquat heuristic catch the
> demo's Scene-4 attack on their own.

### Voice match (Slide 7)

| Piece | File:line | Test | PR |
|---|---|---|---|
| Sentence-length similarity | `src/voice_scorer.py:_avg_sentence_length` + `_similarity_from_ratio` | `tests/test_voice_scorer.py` | (this branch) |
| Vocab overlap via Jaccard on mixed Chinese-bigrams + ASCII-words | `src/voice_scorer.py:_tokens` + `_jaccard` | tested via end-to-end `score()` | (this branch) |
| Structure similarity (sentences-per-message profile) | `src/voice_scorer.py:score` | 1 case | (this branch) |
| 80% hard ceiling (uncanny-valley guard) | `src/voice_scorer.py:MAX_VOICE_PCT = 80` | `test_identical_text_caps_at_80` + `test_overall_never_exceeds_max` | (this branch) |
| Total `score()` returning VoiceScore | `src/voice_scorer.py:score` | 10 cases incl mixed-language, empty-input, low-score, explain() | (this branch) |

### Absence Mode (Slide 9)

> **Not built.** Roadmap places this in W5 buffer. Slide 9 is aspirational.
> Fallback during recording: skip Scene 5 entirely OR show audit log replay
> as a static stand-in.

### Cost discipline (Slide 12)

| Piece | File:line | Test | PR |
|---|---|---|---|
| Routing heuristic Opus vs Kimi | `src/tools/kimi_bulk.py:should_offload` | 6 cases | #3 |
| Kimi HTTP wrapper (lazy, OpenAI-compatible) | `src/tools/kimi_bulk.py:call_kimi` | tested (env-missing path) | #3 |
| Audit log per-call cost_usd | `src/audit.py:AuditEvent.cost_usd` | tested | #3 |
| CostMeter usage tally | `src/cost_meter.py:usage_summary` | 4 cases | #5 |
| 50 / 80 / 100 / 120% threshold alerts | `src/cost_meter.py:check_thresholds` | 4 cases | #5 |
| Per-turn alert dispatch in Telegram | `src/main.py:on_message` (post-reply poll) | `tests/test_cost_meter.py:test_budget_state_*` (5 cases) | #10 |
| 120% halt refuses new turns | `src/main.py:on_message` (top-of-turn halt) | `test_budget_state_halt_property_set_after_120_pct` | #10 |
| Cache discipline (system_prompt cache_control: ephemeral) | `docs/00-agent-identity.md` §Cache 紀律 | declarative — agent honors when calling SDK | #1 |

> **Live cost dashboard** — current path is "alerts on crossings"; a real-time
> dashboard is not built. Demo recording can show the alert + the audit-log file.

### Channels

| Channel | Tools | File | Test | PR |
|---|---|---|---|---|
| Telegram | webhook + inline buttons | `src/main.py` | manual (live) | #1, #4, #6, #10 |
| Gmail (IMAP + SMTP, app password) | list_unread / search / read / send | `src/tools/gmail_mcp.py` | `tests/test_gmail_mcp.py` (10 cases) | #7 |
| Bluesky (atproto) | timeline / search / post / reply | `src/tools/bluesky_mcp.py` | `tests/test_bluesky_mcp.py` (11 cases) | #9 |
| Memory MCP | write_user_profile / write_learning | `src/tools/memory_mcp.py` | `tests/test_memory_mcp.py` (7 cases) | #8 |

### Safety primitives

| Piece | File:line | Test | PR |
|---|---|---|---|
| Kill switch (STOP / 緊急停止 / KILL keywords + KILL.flag) | `src/kill_switch.py` | 6 cases | #3 |
| Audit log JSONL schema (docs/04 §E) | `src/audit.py` | 4 cases | #3 |
| Subject/body hashed before audit | `src/agent.py:_hash_input` | `test_post_hook_hashes_subject_and_body` | #4 |
| ALLOWED_USERS Telegram whitelist | `src/main.py:_allowed_user_ids` | manual | #1 |
| Memories gitignored, .example committed | `.gitignore` + `memories/*.example.md` | n/a (filesystem) | #1 |

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
| W4 | Pitch deck | ⏳ in progress | this doc + docs/06 |
| W4 | Pre-recorded demo | ⏳ in progress | docs/08 |
| W5 | Forensic analyzer + injection demo | ✅ | `src/forensic.py` (this branch) |
| W5 | Voice scorer | ✅ | `src/voice_scorer.py` (this branch) |
| W5 | Replay engine | ✅ | `src/replay.py` (this branch) |
| W5 | Trust Curve auto-promotion | 🔜 not started | needs N-confirm pattern detection |
| W5 | Absence mode | 🔜 not started | — |
| W6 | Final demo video | 🔜 — | — |
| W7 | Interview prep | 🔜 — | — |

## What we are honest about

For the 6/12 written submission, the three big pitch claims have running code as of
this branch (`claude/w5-voice-scorer`):

- Voice match algorithm (Slide 7) — `src/voice_scorer.py`, 10 tests, 80% cap enforced
- Memory Replay composer (Slide 6) — `src/replay.py`, 15 tests, full report
  including triggered L3 / similar cases / voice / forensic / counterfactual
- Forensic analyzer (Slide 8) — `src/forensic.py`, 23 tests, typosquat + injection DB
  + SPF/DKIM header parser

What's still NOT in code:

1. **Trust Curve auto-promotion (Slide 5)** — pattern detection so the agent itself
   proposes "after N confirms, auto-with-undo?" — not yet implemented. Currently
   every Tier-2 call still confirms every time. The 5-stage ladder is product
   design; the W5 build is the Tier-1/2/3 three-stage gate.
2. **Replay [Why this?] Telegram inline-button** — `replay.build_report` returns a
   rendered text block ready to post; wiring a button on each Telegram reply to
   call it is mechanical and lands in a follow-up.
3. **DNS-based SPF/DKIM verification** — `forensic.analyze_auth_headers` parses
   Authentication-Results headers but doesn't live-query DNS. Real-mailbox demo
   uses the parsed header path; "unverified" appears when headers aren't supplied.

Three honest paragraphs in the deck (one per gap) are better than fudging — reviewers
will spot the absence in any live Q&A.

## Operator checklist before recording

1. `make install && make test` — confirm 108/108 green.
2. `cp .env.example .env` and fill `TELEGRAM_BOT_TOKEN`, `ALLOWED_USERS`,
   `ANTHROPIC_*`, `GMAIL_*`. Bluesky optional for the recording.
3. `make run` and verify Telegram echo works end-to-end.
4. Pre-stage Gmail inbox: send 2–3 test messages so `list_unread` has real content.
5. Follow shot list in `docs/08-demo-recording.md`.

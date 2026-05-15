# 01 — 系統架構設計

目的:把「副手」的系統設計完整講清楚,讓 reviewer 一份檔看完知道我們怎麼蓋。

## 1. 設計原則

四條原則,所有 trade-off 都向這四條對齊:

1. **Channel-native** — 使用者在哪個 chat platform 我們就在哪個。原始設計是 Telegram-only,後來透過 `ChatAdapter` 抽象擴展到 Microsoft Teams;再加平台是寫一個 adapter。**不**做網頁、App、CLI 作為主要 UX。
2. **Human-in-the-loop by default** — 任何寫入外部世界的動作預設都要確認,除非使用者明確 opt-out。
3. **Cost-aware by design** — 預設用便宜模型,貴的模型只用在「需要判斷」的地方。
4. **Auditable everything** — 每個 tool call、每個 model call、每個記憶寫入都進 audit log。

## 2. 系統層級

### Layer 1 — User Interface

**ChatAdapter 抽象**(`src/chat/base.py`)— 所有平台都實作同一個介面:

- `send_message(user_id, text, keyboard=None)` → 回傳 platform-specific MessageRef
- `edit_message(ref, text, keyboard=None)` — 編輯之前送過的訊息
- `register_text_handler` / `register_button_handler` / `register_command_handler` — 註冊 callback
- `run()` — 啟動 webhook server,阻塞直到關機

`Button(label, callback_data)` 與 `Keyboard = list[list[Button]]` 是中立型別,每個 adapter 自己翻譯成平台原生格式。`CHAT_PLATFORM=telegram|teams` 啟動時決定載哪個。

**Telegram**(`src/chat/telegram.py`,預設):
- [python-telegram-bot](https://docs.python-telegram-bot.org/) v21+
- Webhook 模式(不用 polling,省電省 token)
- Inline buttons 透過 `InlineKeyboardMarkup` → Telegram 限制 callback_data ≤ 64 bytes
- 入站驗證:Telegram echo 回 `X-Telegram-Bot-Api-Secret-Token` header(由 SDK 處理)

**Microsoft Teams**(`src/chat/teams.py`):
- 直接打 Bot Framework v3 REST API(httpx + aiohttp);不用 `botbuilder-core` 以減少 dep
- Inline buttons 透過 Adaptive Card v1.4 `Action.Submit`(每個 row → 一個 ActionSet),callback_data 放在 `data.cb`
- 入站驗證:`src/chat/teams_auth.py` 透過 PyJWT 驗 Microsoft 的 Bot Framework JWT(signature + iss + aud + exp + serviceurl cross-check),JWKS 快取 24h + force-refresh-on-unknown-kid
- 主動訊息:Teams 不允許 bot 主動 DM 陌生人,所以 `_ConversationStore` 在每次入站活動時把 ConversationReference 持久化到 `trust/teams_conversations.json`

**單一使用者授權**:`ALLOWED_USERS` env 白名單對兩個平台都生效。Telegram 用 numeric user IDs(字串化),Teams 用 AAD object IDs。

### Layer 2 — Service / Orchestration

- **Python 3.11+** service,跑在 WSL2 Ubuntu 22.04
- 入口:`src/main.py` — 薄薄的 dispatcher,從 `CHAT_PLATFORM` 環境變數選 adapter,註冊所有 handler,然後 `run()`。所有 handler 都是平台中立的(輸入 `IncomingText` / `IncomingButton`,輸出透過模組 global `_ADAPTER.send_message`)
- 核心:`src/agent.py`(包 Claude Agent SDK);純邏輯 helper 抽到 `src/agent_helpers.py` 供 SDK 不在的環境也能 unit-test
- 配置:`.env` 載入所有金鑰(雙平台所需的 secret 都在 `.env.example` 各自的段落)

### Layer 3 — Agent Brain

- **Claude Agent SDK (Python)** v0.2.111+
- 模型:claude-opus-4-6-2026V2(透過 ASUS 配發的 Azure endpoint)
- 設定:

```python
ClaudeAgentOptions(
    model="claude-opus-4-6-2026V2",
    max_turns=10,
    permission_mode="default",  # 走我們自己的 hooks
    allowed_tools=[...],
    hooks={"PreToolUse": [permission_gate], "PostToolUse": [audit_log]},
    system_prompt=(
        open("docs/00-agent-identity.md")
        .read()
        .replace("{USER_NAME}", os.environ["USER_NAME"])
    ),
)
```

Runtime constitution 來源是 `docs/00-agent-identity.md`,**不是** repo 根目錄的 `CLAUDE.md`(後者只給 Claude Code dev tool 用)。決議見 docs/00 開頭「Role split」段。

### Layer 4 — Tools (MCP & Native)

**Note**: chat-platform I/O is **NOT** an MCP tool — it's the ChatAdapter layer above (Layer 1). The agent never calls `mcp__telegram__send` or `mcp__teams__send`; the adapter dispatches incoming text/buttons to handlers and the handlers call `adapter.send_message(...)` directly. This keeps the agent's tool surface focused on capabilities (mail / social / memory / bulk LLM) rather than transport.

| Tool | 類型 | 用途 | 來源 |
| :-: | :-: | :-: | :-: |
| mcp__gmail__* | MCP | 讀信箱(read 自動跑 forensic.analyze)、搜信、寄信 | IMAP + app password,`src/tools/gmail_mcp.py` |
| mcp__bluesky__* | MCP | 讀 timeline(每筆貼文跑 forensic)、發貼、回留言 | atproto Python SDK,`src/tools/bluesky_mcp.py` |
| mcp__memory__write_* | MCP | L2/L3 寫入(Tier 2 確認),信心度自動降級 | 自寫,`src/tools/memory_mcp.py` |
| mcp__kimi__bulk_generate | MCP | 長輸出 / batch / 翻譯 / 改寫 → Kimi K2.5 | `src/tools/kimi_bulk.py`,`should_offload` server-side check |
| WebSearch / WebFetch | Agent SDK 內建 | 查資料 | Anthropic 官方 |

**Heterogeneous routing**:`kimi_bulk` 的 `should_offload(kind, expected_output_chars, batch_size)` 是 server-side oracle — agent 自己決定 route,但 server 會檢查,把 `classify` / `safety` 類 task 強制 reject 回 Opus。`OPUS_ONLY_KINDS` 在 `kimi_bulk.py` 是 frozenset,改它要動 docs。

L2/L3 reads 由 agent 用 SDK 內建 Read tool 對 `memories/*.md` 直接讀(Tier 1),寫入才走 MCP(Tier 2)。

### Layer 5 — Cross-cutting Concerns

#### PermissionGate(src/permissions.py)

- 實作為 Agent SDK 的 PreToolUse hook
- 接到 tool call 時:
  1. 查 Tier 1 白名單 → 直接放行 + log
  2. 查 Tier 3 黑名單 → 立即拒絕 + log + 通知使用者
  3. 落入 Tier 2 → 透過 Telegram 發確認訊息 + 阻塞等待使用者回覆
- Tier 2 確認 timeout 預設 5 分鐘,逾時自動拒絕

#### AuditLogger(src/audit.py)

- PostToolUse hook
- 寫入 logs/{YYYY-MM-DD}.jsonl,每行一個 event:

```json
{
  "ts": "2026-05-13T08:23:11Z",
  "session_id": "...",
  "tool": "mcp__gmail__send",
  "tier": 2,
  "user_confirmed": true,
  "input_hash": "sha256:...",
  "output_preview": "...",
  "tokens": {"opus": 1240, "kimi": 0},
  "cost_usd": 0.018
}
```

#### CostMeter(src/cost_meter.py)

- 累計每日 / 每週 / 整個競賽期間 token 用量
- 觸發告警(對應資安 PDF 的 50/80/100/120% 機制):
  - 50% → log warning
  - 80% → Telegram notify
  - 100% → Telegram urgent + 暫停 Tier 2 動作
  - 120% → 全面停機,只保留 read-only

#### TrustCurve + 衍生 UX(src/trust_curve.py, escalation.py, undo_window.py, absence_mode.py)

實作後新增的 cross-cutting 組件,docs/00 §權限分級 與 docs/02 demo Scene 1–5 都依賴:

- **`trust_curve.py`** — 每個 (tool, key) pattern 的 5 段 Level(`ALWAYS_ASK` / `MANUAL` / `AUTO_AUDITED` / `AUTO_SILENT` / `FULL`)+ confirm/reject 計數;檔案後端 `trust/curves.json`
- **`escalation.py`** — 5 次連續 confirm → propose 升級;三個按鈕(🤖 Auto / 🛎️ 繼續每次都問 / ❌ 永遠別自動)
- **`undo_window.py`** — `AUTO_AUDITED+` pattern 的 15 秒 undo 視窗;delay-then-execute(計時器內按 undo → Deny,沒按 → Allow → tool 才執行)
- **`absence_mode.py` + `absence_feedback.py`** — 時間窗 self-running + 結束時送 structured replay log + 每筆 auto_executed 一個 ✅/🚫 feedback bubble

#### Memory Replay + Voice Match + Forensic(三個 moat)

- **`replay.py`** — `build_report(event_index)` 對過去 audit event 組裝完整推理鏈;`build_report_for_call(tool, args)` 對「正在發生」的決定合成 pseudo-event 跑同一條 pipeline,供 Telegram `[🔍 Why this?]` 按鈕用
- **`voice_scorer.py`** + **`voice_corpus.py`** — Jaccard + 句長 + 結構三指標(80% 硬上限);corpus 從 L2 + 最近 7 天 L4 `user[*]:` 行 build,每筆 Tier-2 confirm prompt 自動顯示
- **`forensic.py`** + **`forensic_log.py`** — Levenshtein + brand-stem + SPF/DKIM + 8 條 injection regex;`gmail_mcp.read` 與 `bluesky_mcp` 的 timeline/search 自動跑,warning+ 寫進 `logs/forensic.jsonl`,`/status` 與 CLI 都能讀

#### KillSwitch(src/kill_switch.py)

- 兩個 trigger:
  1. 使用者送 `STOP` / `緊急停止` / `KILL`(關鍵字精確比對)
  2. `KILL.flag` 檔案出現在 repo 根目錄(out-of-band)
- 在 `main.on_text` 每個 turn 開頭檢查;觸發後回 `✋ 已停止…` 並 short-circuit return
- **原始設計提過 Redis pub/sub 作為替代**,MVP 範圍內只實作檔案旗標版;Redis 升級留給 V2 多 instance 部署

### Layer 6 — Memory(詳見 docs/04-security-design.md)

四個磁碟位置:

- docs/00-agent-identity.md (檔案,git 管,L1 不可變憲法)
- memories/user-profile.md (執行期檔案,gitignored;`.example` 版本 git tracked)
- memories/learnings.md (執行期檔案,gitignored;`.example` 版本 git tracked)
- memories/sessions/YYYY-MM-DD.md (檔案,.gitignore)

後續可升級到 Anthropic Managed Agents Memory(Layer 4 機制),但 W1-W3 先用檔案版,簡單夠用。

## 3. 資料流範例:「幫我看一下狀況」

```
 1. User → ChatAdapter (Telegram 或 Teams): "幫我看一下狀況"
 2. Adapter webhook → main.on_text(IncomingText(user_id, text, source_ref))
 3. main.on_text 檢查 kill_switch / absence / budget halt → 通過
 4. main.on_text → agent.reply(...) 帶 ConfirmRegistry / TrustCurve / AbsenceMode / UndoRegistry / UserCorpus
 5. Agent SDK 載入 docs/00-agent-identity.md 為 system_prompt + L2/L3/L4 memory(Tier 1 reads,自動)
 6. Agent 規劃:需要 gmail + bluesky 兩個 tool
 7. Agent → PreToolUse hook(mcp__gmail__list_unread): permissions.classify → Tier 1 → allow
 8. Agent → mcp__gmail__list_unread → 47 封未讀
 9. Agent → mcp__gmail__read(uid=...) → 自動跑 forensic.analyze;1 封含 "ignore previous"
    → 前置 🚨 banner 到 body;forensic_log.record 寫 logs/forensic.jsonl
10. Agent → PreToolUse hook(mcp__bluesky__timeline): Tier 1 → allow
11. Agent → mcp__bluesky__timeline → 最近 24h posts(每筆 scan_post_for_injection)
12. Agent 判斷信件量大 → mcp__kimi__bulk_generate(kind="summarize", prompt="摘要這 47 封...")
    ↓ server-side should_offload check 通過(輸出預期 > 500 字元)
    ↓ Kimi K2.5 處理,~50K Opus token 省了
13. Agent 套用 L3 learnings 的過濾規則(SDK context 內處理)
14. Agent 生成中文摘要文字 → 回傳給 agent.reply
15. agent.reply 累計 token usage(accumulate_tokens 對每個 SDK event)→ AuditLogger.log_turn_summary
16. main.on_text → _ADAPTER.send_message(user_id, answer)  ← 平台中立!
    ↓ TelegramAdapter: bot.send_message(chat_id=..., text=...)
    ↓ TeamsAdapter:    POST {service_url}/v3/conversations/{id}/activities (text-only Activity)
17. CostMeter.poll() 跨門檻 → adapter.send_message(_format_alert(alert))
```

寫入路徑(Tier 2)額外步驟:
```
 PreToolUse → permissions.classify → Tier 2 → "ask"
 → SDK 呼 can_use_tool → tier2_confirm.await_decision
 → adapter.send_message(prompt + confirm keyboard,含 voice match line)
 → 使用者按 ✅/❌ → adapter button handler resolves the Future
 → trust_curve.record(approved=True) → 若 streak == 5 觸發 on_eligible
 → adapter 送 propose-escalation 訊息(3 個按鈕)
 → 工具實際執行 → PostToolUse hook 寫 audit JSONL
```

## 4. Demo 對應的最小可運作版本(MVP scope)

**必須有**(W1-W3 內完成):

- Telegram bot + Agent SDK 接通
- Gmail MCP(讀 + 起草,不需要 OAuth flow demo,用 app password)
- Bluesky MCP(讀 timeline + 起草回覆)
- Tier 1/2 權限 gate
- 記憶 L1 + L2 + L3
- Kimi tool wrapper
- 基本 audit log

**Demo 期望但不一定全要**(W3-W4):

- Tier 3 完整 enforcement
- CostMeter 即時儀表板
- L4 session log
- KillSwitch
- Prompt injection 防禦的具體展示

**之後再說**(post-competition):

- 多使用者
- Web UI
- Calendar 整合
- 真實 deployment 的 production hardening

## 5. 技術選型理由(給評審看的)

| 選擇 | 為何選它 | 為何不選其他 |
| :-: | :-: | :-: |
| Claude Agent SDK | 原生對 Anthropic API,memory tool / hooks / subagent 都到位 | LangGraph 太重、Pydantic AI memory 要自搭、裸 API 要造太多輪子 |
| ChatAdapter 抽象 | 把平台 glue 集中到 `src/chat/`,加 platform = 寫一個 adapter;handler/state/agent 都不用動 | 平台耦合在 main.py 就只能單平台;每加一個都要大改 |
| Telegram(主) | Bot API 成熟、官方 lib 完整、適合單人 demo | LINE 在台灣很好但 channel-level API 較複雜;Slack/Discord 偏團隊 |
| Microsoft Teams(企業擴展) | ASUS / 多數企業用 Teams 作為日常 chat;Adaptive Cards 對 inline UX 表現好 | Slack 在台灣企業普及率不如 Teams;Bot Framework 雖然麻煩,但是企業整合的事實標準 |
| Teams 不用 botbuilder-core | 直接打 Bot Framework v3 REST 少 ~15 個 transitive dep,wire 也只 ~300 行;PyJWT 處理 JWT 是 awesome-secure-defaults 推的 lib | botbuilder 在 Python 3.11+ 偶有 dep 衝突;包進來只用到 Activity 序列化一小部分 |
| Bluesky | 開放 AT Protocol、demo 穩、不會被風控擋 | Threads/FB API 殘缺、瀏覽器自動化會被封號 |
| Kimi K2.5 (作為 tool) | 預算最大(126M token)、TPM 最高(35K) | Opus 太貴、GPT-5.4 預算只有 12M |
| WSL2 + Ubuntu | Agent SDK 在 Linux 最穩、隔離環境符合資安規範 | 純 Windows 上 Claude Code/SDK 常出怪事 |

## 6. Known unknowns(實作後更新)

### 已解決

- ~~Telegram 確認流程 UX~~ → InlineKeyboardMarkup ✅/❌ 雙按鈕,搭配 voice match line 在 prompt 內。Teams 同樣 UX,用 Adaptive Card Action.Submit。
- ~~Tier 2 確認的 5 分鐘 timeout~~ → 預設 `DEFAULT_CONFIRM_TIMEOUT = 300` 秒,逾時自動 Deny;絕大多數實際用例使用者 1–2 分鐘內回。
- ~~不同 model 的 token 計算統一~~ → `cost_meter.PRICES_USD_PER_MTOK` 用 input/output 兩段定價,`accumulate_tokens` 從 SDK event 抓 `usage.input_tokens` / `usage.output_tokens`,`turn_summary` 寫進 audit JSONL。

### 仍未解

- **Memory L3 的 token 大小上限管理** — 累積太多 block 後 system prompt 會超預算。目前沒做 compaction;短期靠 `HIGH_CONFIDENCE_MIN_OBS = 5` 限制 noise rule 寫入速度。中期方案是定期 LLM-assisted summarisation。
- **多語言處理** — Agent 在 system prompt 中要求中文輸出,但英文信摘要的品質還沒 benchmark;Kimi 對中文比 Opus 更敏感,可能影響 routing 決策。
- **Bot Framework JWT signature 對 outbound TLS 信任鏈的 MITM 風險** — 依賴系統 CA bundle + httpx 預設 TLS 驗證;cert pinning 對單人 demo 過度設計,留給 enterprise V3。
- **Teams 多 instance 部署** — `_ConversationStore` 是檔案後端,多 process 同時寫會競爭;V2 多使用者時要改 SQLite 或外部 store。

### Roadmap 後續

- **Live Bot Framework Emulator 整合測試** — 需要 emulator 並行跑;CI 之外手動驗
- **真正的 Azure deployment 試打** — 拿 ASUS 內部 Teams tenant 試,把 `.env.example` 的 7 步 checklist 走通
- **Telegram + Teams 同 process 並行**(README 提到的 "Multi-channel" option)— 目前還是擇一啟動;同時跑要重新設計 `_ADAPTER` global 為 dict

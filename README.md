# 副手 (Fushou) — An AI delegate, not assistant

**Earning autonomy, one confirm at a time.**

## 為什麼「AI 助理」是錯的問題

過去三年所有 personal AI 都長同一個樣子:你問,它答;你下指令,它執行。它聽你的話 — 但你也只能盯著它做。

**這不是 delegation,這是 enhanced typing。**

真正的 delegation 不是這樣。你告訴一個下屬一次「以後這類事這樣處理」,下次他自己會。你看他的判斷,不滿意就教他;滿意就放手。**信任是賺來的,自主權是漸進的**。

副手 (Fushou) 就是這樣設計的。

## The thesis: Earning Autonomy

副手不是 assistant,是 **delegate**。

預設權限最小、每個寫入動作都要確認。但 agent 不只是等指令 — 它會:

1. **觀察你的 confirm / reject / edit 模式**
2. **量化你的偏好(不是抽象「學習」,是數字)**
3. **主動 negotiate 自主權邊界**
4. **每個決定 replayable** — 為什麼這樣做?哪些 memory 觸發?什麼會改變這個答案?
5. **支援 Absence Mode** — 你不在,它在已賺得的範圍內自主跑,回來給你 structured replay

用越久,agent 能做的越多;但每個 escalation 你都看得到、可 revoke、可解釋。

## 五個核心機制(每個都是 demo 賣點)

### 1. Trust Escalation Curve

每個 Tier 2 動作預設都要 confirm。同一個 pattern 在 5 次 confirm 後,agent **主動提議**:

"我注意到你連續 5 次都直接確認 ACME 交期回覆,內容沒改過。要我以後遇到這類自動處理(15s undo 視窗)?"

你選 ✅ → 升級到 Auto (audited)
你選 🛡️ → 繼續每次問,降低 agent 對這 pattern 的 confidence
你選 ❌ → 加入「always ask」清單,永不升級

**Trust Dashboard**:每類動作目前的權限級別 + 累積證據,隨時可查、可降。

權限不是 binary — 從 Manual → Auto (audited, 15s undo) → Auto (silent, log only) → Full,五段階梯。

### 2. Memory Replay

每個 agent 做的決定,你按一個鈕,看到完整推理鏈:

- 觸發的 memory entry(L1 / L2 / L3 編號)
- 過去 3 個 similar case(連結到 audit log)
- Voice match / urgency / sensitivity score
- **Counterfactual:「什麼會改變這個決定」**

你糾正後,update 進 L3 為**新規則 + 低信心**,需再 3 次驗證才升信心。Agent 不會盲目接受單一糾正而 over-fit。

**Explainability 不是公關話術,是按鈕。**

### 3. Voice Match 量化

Agent 起草任何回覆時,即時顯示與你 baseline 的 similarity:

- 句長 vs 你的平均
- 詞彙重疊
- 結構模式(問候 / 正文 / 結尾)

Demo 顯示:Today's voice match: 84% (上週 71%)

**關鍵設計**:**主動把上限設在 80%**。Uncanny valley 是 anti-feature — 太像你會創造法律責任 + 心理不適。我們的定位是 helpful subordinate,不是 digital twin。

**這個量化欄,沒有其他隊會給數字。**

### 4. Forensic Security

擋下 prompt injection 不夠 — 副手做完整 forensic analysis:

```
寄件域名分析: asuS-corp.com (Levenshtein=1 vs asus.com)
  ├─ 註冊日期: 昨天 (Namecheap)
  ├─ SPF / DKIM: 失敗
  └─ Reputation: 0/100

注入 pattern: "ignore previous instructions" → DB 第 47 次出現

觸發規則: Tier 3 不洩漏密鑰 + L1 不可變保護
```

評審看到會「啊這 agent 真的在分析,不只是 LLM 隨口擋」。

### 5. Absence Mode

"我接下來 4 小時開會,你自己處理。維持目前 trust level,別 escalate。"

Agent 在這段內,在**已 trust-elevated 範圍內**自主跑。

- 不確定的存草稿
- 緊急情況打 Telegram(已測過)
- 每 30 分鐘 timeline 一次

你回來看 **Replay Log**:每個決定 + 一鍵「OK / 下次這樣做 / 不該自動」→ 直接 update memory。

**這才是 delegation 該長的樣子。**

## 我們**不**做什麼(誠實邊界)

| 不做 | 為什麼 |
| :-: | :-: |
| 100% voice match | Uncanny valley + 法律責任。上限 80% |
| 自動 first-contact | Tier 2 永遠擋給不認識的人寫信 |
| Digital twin | 副手有它自己的判斷限制,該說「你來」就說 |
| V1 做 B2B 多租戶 | Single-user MVP 先做扎實,V2 才打 enterprise(誠實 roadmap) |
| 接公司任何系統 | 個人帳號 + 模擬資料,符合 ASUS 資安規範 |

## 跟一般「AI 助理」隊伍的差別(30 秒版本)

| 一般 AI 助理 | 副手 |
| :-: | :-: |
| 給你看摘要 | 摘要 + 量化 voice match |
| 起草回覆 | 起草 + 顯示信心 + Memory Replay |
| 「學你的偏好」(口頭講) | Trust Curve 可視化 + 量化指標 |
| 擋 prompt injection | Forensic analysis + attack DB |
| 「你不在我幫你看」 | 真正 Absence Mode + Replay Log |

評審看 100 個 demo,**只有副手能在 30 秒內讓他想起「那一隊」**。

## Architecture(壓縮版)

```
[Telegram] ──┐
             ├─→ [ChatAdapter] → [Python service in WSL2]
[MS Teams] ──┘                          │
   (Adaptive Cards)                     ▼
                                  [Claude Agent SDK]  ← Opus 4.6 (delegate brain)
                                        │
                              ┌─────────┴──────────┬──────────────────┐
                              ▼                    ▼                  ▼
                         [MCP Tools]      [Cross-cutting]      [自家三大元件]
                         • gmail          • PermissionGate     • ReplayEngine
                         • bluesky        • AuditLogger        • VoiceScorer
                         • memory         • CostMeter          • ForensicAnalyzer
                         • kimi_bulk      • KillSwitch
                                          • TrustCurve         ↑ 這三個是 moat
                                          • UndoWindow
                                          • AbsenceMode
```

`CHAT_PLATFORM=telegram|teams` 環境變數決定 startup 載哪個 adapter。兩邊都實作同一個
`ChatAdapter` 介面(send_message / edit_message / inline buttons),所有 handler
都是平台中立的 — 加第三個平台就是再寫一個 adapter。

詳見 docs/01-architecture.md 與 CLAUDE.md `Multi-platform chat layer` 章節。

## 競賽對齊

| 評分 | 權重 | 對應 |
| :-: | :-: | :-: |
| 實用價值 / DEMO | 55% | 5 個 mechanic 都 demo 化(docs/02-demo-script.md) |
| 商業化 | 20% | V1 個人 / V2 prosumer / V3 enterprise 誠實路徑(docs/03-scenarios.md) |
| 技術 | 15% | ReplayEngine / VoiceScorer / ForensicAnalyzer 三個自家元件 |
| 風險 / 成本 | 10% | Forensic + 完整 ASUS 規範對應 + cost control(docs/04 & 05) |

## Repo 結構

```
/agent-project/
├── README.md                       ← 你在看的
├── CLAUDE.md                       ← Claude Code dev guidance
├── docs/00..08.md                  ← design / demo / security / roadmap / build status
├── pyproject.toml
├── .github/workflows/              ← CI (ruff + pytest, py3.11/3.12) + weekly pip-audit
├── src/
│   ├── main.py                     ← Thin dispatcher; picks adapter from CHAT_PLATFORM env
│   ├── agent.py                    ← Agent SDK orchestration; agent_helpers.py 是 testable 抽取
│   ├── permissions.py              ← Tier 1/2/3 classifier
│   ├── trust_curve.py              ← 5-level Trust Curve + persistence
│   ├── escalation.py               ← propose-escalation 3-button UX
│   ├── undo_window.py              ← 15s undo for AUTO_AUDITED+ patterns
│   ├── absence_mode.py             ← 時間窗 + structured replay log
│   ├── absence_feedback.py         ← 每筆 auto_executed 的 ✅/🚫 feedback bubble
│   ├── why_button.py               ← [🔍 Why this?] decision snapshot registry
│   ├── replay.py                   ← Memory Replay engine ⭐ 自家
│   ├── voice_scorer.py             ← Voice match algo ⭐ 自家 (80% 上限)
│   ├── voice_corpus.py             ← 從 L2 + L4 build 使用者語料
│   ├── forensic.py                 ← Attack analyzer ⭐ 自家
│   ├── forensic_log.py             ← logs/forensic.jsonl (append-only)
│   ├── memory_inspect.py           ← /profile + /learnings 的 read-only render
│   ├── memory_writes.py            ← L2/L3 append + 信心度降級
│   ├── session_log.py              ← L4 (memories/sessions/{date}.md)
│   ├── audit.py                    ← logs/{date}.jsonl + turn_summary 寫入
│   ├── cost_meter.py               ← 50/80/100/120% threshold alerts + 定價
│   ├── kill_switch.py              ← STOP / 緊急停止 / KILL.flag
│   ├── cli.py                      ← `python -m src.cli ...` 離線 ops 工具
│   ├── chat/                       ← 多平台 chat adapter 層
│   │   ├── base.py                 ←   ChatAdapter ABC + Button/Keyboard 中立型別
│   │   ├── telegram.py             ←   TelegramAdapter (python-telegram-bot)
│   │   ├── teams.py                ←   TeamsAdapter (Bot Framework v3 HTTP + Adaptive Cards)
│   │   └── teams_auth.py           ←   Bot Framework JWT 驗證 (PyJWT + JWKS cache)
│   └── tools/                      ← MCP servers (lazy claude_agent_sdk import)
│       ├── gmail_mcp.py            ←   read 會自動跑 forensic.analyze
│       ├── bluesky_mcp.py          ←   每筆 timeline 貼文也跑 forensic
│       ├── memory_mcp.py           ←   write_user_profile / write_learning
│       └── kimi_bulk.py            ←   bulk_generate MCP tool + should_offload 路由
├── tests/                          ← 1:1 with src/; 339 SDK-independent tests
├── memories/                       ← L2/L3/L4 (gitignored,只有 .example.md 進 git)
├── trust/                          ← curves.json + teams_conversations.json
└── logs/                           ← audit JSONL + forensic JSONL
```

## 平台支援(Platform support)

副手原本是 Telegram-only,現在透過 `ChatAdapter` 抽象支援:

| Platform | 啟動方式 | UX 表現 | 雙向驗證 |
| :-: | :-: | :-: | :-: |
| Telegram | `CHAT_PLATFORM=telegram`(預設) | InlineKeyboardMarkup buttons | `secret_token` header |
| Microsoft Teams | `CHAT_PLATFORM=teams` | Adaptive Cards v1.4 + Action.Submit | Bot Framework JWT(PyJWT + JWKS) |

Teams 部署需要先在 Azure 註冊 Bot resource、加 Teams channel、設 messaging endpoint 為
`https://<host>/api/messages`,並讓使用者先 DM bot 一次以捕獲 ConversationReference
(Teams 不允許 bot 主動 DM 陌生人)。完整 7 步 setup checklist 見 `.env.example` 與
CLAUDE.md `Azure setup checklist` 段落。

## 狀態

WIP — 競賽期間開發中。

W1-W3 完成 5 個 mechanic 的 MVP / W4 拋光 + 簡報 / W5-W7 影片 + 面談。

詳見 docs/05-cost-and-roadmap.md。

## 命名備註

「副手」是工作名稱。新主軸下可考慮重新命名(更貼近 delegate 語意):

| 候選 | 語感 |
| :-: | :-: |
| 副手 (Fushou) | 現用,sidekick / deputy |
| 託付 (Tuofu) | entrusted,情感共鳴強 |
| 委任 (Weiren) | appointment / delegation,formal |
| Delegate | 直接英文,brand 國際化路徑 |
| Atlas | 承載 weight,有 weight 感 |

決議前文件繼續用「副手」。

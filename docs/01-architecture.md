# 01 — 系統架構設計

目的:把「副手」的系統設計完整講清楚,讓 reviewer 一份檔看完知道我們怎麼蓋。

## 1. 設計原則

四條原則,所有 trade-off 都向這四條對齊:

1. **Channel-native** — 使用者在 Telegram,我們也在 Telegram。不要做網頁、App、CLI。
2. **Human-in-the-loop by default** — 任何寫入外部世界的動作預設都要確認,除非使用者明確 opt-out。
3. **Cost-aware by design** — 預設用便宜模型,貴的模型只用在「需要判斷」的地方。
4. **Auditable everything** — 每個 tool call、每個 model call、每個記憶寫入都進 audit log。

## 2. 系統層級

### Layer 1 — User Interface

- **Telegram Bot**(主要 channel)
- 使用 [python-telegram-bot](https://docs.python-telegram-bot.org/) v21+
- Webhook 模式(不用 polling,省電省 token)
- 單一使用者授權(ALLOWED_USERS env var 白名單)

### Layer 2 — Service / Orchestration

- **Python 3.11+** service,跑在 WSL2 Ubuntu 22.04
- 入口:src/main.py(Telegram webhook handler)
- 核心:src/agent.py(包 Claude Agent SDK)
- 配置:.env 載入所有金鑰

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
    system_prompt=open("CLAUDE.md").read(),
)
```

### Layer 4 — Tools (MCP & Native)

| Tool | 類型 | 用途 | 來源 |
| :-: | :-: | :-: | :-: |
| mcp__telegram__* | MCP | 在 Telegram 收發訊息 | Composio 或自寫 |
| mcp__gmail__* | MCP | 讀信箱、搜信、起草 | Composio 或 IMAP |
| mcp__bluesky__* | MCP | 讀 timeline、發貼文、回留言 | atproto Python SDK 包成 MCP |
| tool__kimi_bulk | Native function | 把長文本工作丟給 Kimi K2.5 | 自寫 |
| tool__gpt_specific | Native function | 特定 task fallback 用 GPT-5.4 | 自寫 |
| memory | Agent SDK 內建 | 跨 session 持久記憶 | Anthropic 官方 |
| WebSearch / WebFetch | Agent SDK 內建 | 查資料 | Anthropic 官方 |

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

#### KillSwitch(src/kill_switch.py)

- Redis pub/sub 或檔案旗標
- 任何 turn 開始前先檢查;觸發後拋出 KillSwitchTriggered 例外
- 對應資安PDF「遠端熔斷機制」

### Layer 6 — Memory(詳見 docs/04-security-design.md)

四個磁碟位置:

- CLAUDE.md (檔案,git 管)
- memories/user-profile.md (檔案,git 管,但偏好細節 .gitignore)
- memories/learnings.md (檔案,git 管,但個人資料 .gitignore)
- memories/sessions/YYYY-MM-DD.md (檔案,.gitignore)

後續可升級到 Anthropic Managed Agents Memory(Layer 4 機制),但 W1-W3 先用檔案版,簡單夠用。

## 3. 資料流範例:「幫我看一下狀況」

```
1. User → Telegram: "幫我看一下狀況"
2. Telegram → service(webhook): { message: "..." }
3. service → Agent SDK: query(prompt="...", options=...)
4. Agent SDK loads CLAUDE.md + memory files (Tier 1, 自動)
5. Agent 規劃:需要呼叫 gmail + bluesky 兩個 tool
6. Agent → PreToolUse hook(gmail__list_unread): Tier 1 → 放行
7. Agent → mcp__gmail__list_unread → 取得 47 封未讀
8. Agent → PreToolUse hook(bluesky__timeline): Tier 1 → 放行
9. Agent → mcp__bluesky__timeline → 取得最近 24h posts
10. Agent 判斷信件量大 → tool__kimi_bulk(prompt="摘要這 47 封信...")
    ↓ (這裡省了 ~50K Opus token,改用 Kimi)
11. Kimi 回傳結構化摘要
12. Agent 套用 learnings.md 的過濾規則(在自己的 context 內處理)
13. Agent 偵測 1 封含 "ignore previous instructions" → 標記詐騙
14. Agent 生成回覆訊息 → 透過 mcp__telegram__send 給 User
15. PostToolUse hook 寫 audit log + CostMeter 累計
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
| Telegram | Bot API 成熟、官方 lib 完整、適合單人 demo | LINE 在台灣很好但 channel-level API 較複雜;Slack/Discord 偏團隊 |
| Bluesky | 開放 AT Protocol、demo 穩、不會被風控擋 | Threads/FB API 殘缺、瀏覽器自動化會被封號 |
| Kimi K2.5 (作為 tool) | 預算最大(126M token)、TPM 最高(35K) | Opus 太貴、GPT-5.4 預算只有 12M |
| WSL2 + Ubuntu | Agent SDK 在 Linux 最穩、隔離環境符合資安規範 | 純 Windows 上 Claude Code/SDK 常出怪事 |

## 6. 未涵蓋的設計問題(known unknowns)

開發過程中要解的:

- Telegram 確認流程的 UX(inline button vs. plain text reply)
- Tier 2 確認的 5 分鐘 timeout 是否合理
- 不同 model 的 token 計算如何統一(Opus 算 input/output, Kimi 算法可能不同)
- Memory L3 的 token 大小上限管理(超過要 compaction)
- 多語言處理(英文信怎麼摘要成中文)

這些都留到 W2-W3 跑起來後再決定。

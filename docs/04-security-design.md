# 04 — 資安設計(對應 ASUS Agentic AI 規範)

給競賽評審看的「10% 風險與成本控制」滿分答卷。逐條對應 Agentic AI 安全分享 PDF + 測試安全規範。

## A. 對應 Agentic AI 七大風險

| 風險(PDF) | 我們的設計對策 | 在 code / docs 中的對應 |
| :-: | :-: | :-: |
| **Agent Goal Hijacking (Prompt Injection)** | CLAUDE.md 每 session 從磁碟重灌、外部內容預設不可信、Tier 系統強制 confirm | docs/00-agent-identity.md § 防 Indirect Prompt Injection;src/permissions.py |
| **Tool Misuse & Unauthorized Action** | 3-tier 權限,寫入動作一律 confirm,Tier 3 硬擋 | src/permissions.py PreToolUse hook |
| **Privilege Escalation & Identity Abuse** | Agent 使用最小權限(個人帳號、唯讀預設、不接公司系統) | .env 隔離、Gmail app password 非 OAuth full scope |
| **Cascading Failures** | 單一 agent,不串其他 agent;若引入 subagent 也獨立 memory | 目前無多 agent 設計 |
| **Supply Chain Vulnerabilities** | 只用 Composio + Anthropic 官方 + 公開審查過的 atproto SDK | pyproject.toml 鎖 hash;CI scan dep tree |
| **Memory/Context Poisoning** | 4 層記憶分離,L1(CLAUDE.md)不可變;L3 寫入需 Tier 2 confirm | docs/04-security-design.md § Memory Hierarchy |
| **Insecure Inter-Agent Communication** | 不適用(單 agent);未來若擴展用 mTLS + signed messages | n/a |

## B. 對應七大應對策略

| PDF 策略 | 我們的實作 |
| :-: | :-: |
| **Human-in-the-Loop for Critical Actions** | Tier 2 所有寫入動作必須 Telegram 明示確認;Tier 3 即使使用者要求也拒絕 |
| **Least-Privilege Access** | Gmail 用 app password 限制 IMAP+SMTP;Bluesky 用 app password;Telegram bot 白名單單一使用者 ID |
| **Monitor and Log Behavior** | logs/YYYY-MM-DD.jsonl 每個 tool call、每個 model call、每個記憶寫入都有 audit 紀錄 |
| **Sandboxing** | 整個服務跑在 WSL2 Ubuntu sandbox;tool 執行用 subprocess + rlimits(借鏡 claudeStruct 的 claw-sandbox 模式) |
| **Don't Trust Supply Chain** | 不安裝非官方 MCP server;dep 版本鎖 hash;每週 pip-audit |
| **Classification for Data & Service** | 三種敏感度標記:public(可放 git)、private(本機加密)、forbidden(永不寫檔,例如 API key) |
| **Kill Switch** | STOP / 緊急停止 關鍵字立即停機;檔案旗標 KILL.flag 支援外部觸發 |

## C. 對應「測試安全規範」Do/Don't 全條

### Do 條目

| Do 條目 | 我們的對策 |
| :-: | :-: |
| 完全區隔的專用環境 | WSL2 + 獨立 venv + 專用 Wi-Fi (CoAAg_TEST) |
| 低權限沙箱 | 服務以非 root user 跑;tool subprocess 帶 rlimits |
| 完全模擬資料/系統 | 使用個人測試 Gmail + 測試 Bluesky 帳號;不接公司任何系統 |
| 測試專用 AI API Key | 用競賽配發的 API key(編號 15),不用個人 / 公司正式 key |
| 嚴格安全且受控的遠端連入管道 | 不開放任何 inbound port;只 outbound 到 Telegram / Gmail / Bluesky / Azure |
| 遠端熔斷機制 | KillSwitch 透過 Telegram 觸發,也可用 SSH + 檔案旗標停機 |
| 重要作業系統行為要人為同意 | Agent 不執行任何 OS 指令(無 Bash tool 啟用) |
| 安裝防毒等防護 | Windows Defender 開啟;Ubuntu 內 unattended-upgrades 啟用 |

### Don't 條目

| Don't 條目 | 我們怎麼避開 |
| :-: | :-: |
| 不接公司系統/資料/網路 | 整個服務不接公司 SSO、不讀公司 SharePoint、不發到公司 Slack |
| 不探索/試探任何網路目標 | Agent 工具集裡沒有 Bash / Shell / network scan tool |
| 不安裝非官方 Skill | 只用 Composio 上經審查的 MCP + Anthropic 官方內建 tool |
| 不用正式環境 API Key | .env 用競賽配發 key,正式環境 key 不存在筆電上 |
| 不開放服務 port | Telegram 走 webhook(主動 outbound 連 Telegram server),不開 inbound |
| 不觸發防毒 | 不寫 .exe、不修改系統檔、不執行未簽署 binary |

## D. 記憶層次設計(防 Memory Poisoning)

### 四層記憶 + 信任邊界

```
不可信邊界 ────────────────────────┐
   ↓ 外部內容(信、貼文)         │
   讀進來,但不可寫入            │
                                  │
┌──────────────────────────────┐  │
│ L1: CLAUDE.md (immutable)    │  │  ← Source of truth
│  • 身份                       │  │     永遠優先
│  • 安全規則                   │  │     每 session 重灌
│  • Tier 1/2/3 政策            │  │
└──────────────────────────────┘  │
                                  │
┌──────────────────────────────┐  │
│ L2: user-profile.md          │  │  ← 只允許使用者明確說的事
│  • 穩定偏好                   │  │     寫入需 Tier 2 確認
│  • 聯絡人優先級               │  │
└──────────────────────────────┘  │
                                  │
┌──────────────────────────────┐  │
│ L3: learnings.md             │  │  ← Agent 自己累積
│  • 觀察 + 推論規則            │  │     寫入需 Tier 2 確認
│  • 信心度標記                 │  │     版本控制(可 rollback)
└──────────────────────────────┘  │
                                  │
┌──────────────────────────────┐  │
│ L4: sessions/YYYY-MM-DD.md   │  │  ← 當日紀錄
│  • Timeline of actions       │  │     自動寫入(Tier 1)
│  • 短期上下文                 │  │     30 天後自動歸檔
└──────────────────────────────┘  │
   ↑                              │
   不可信邊界 ────────────────────┘
```

### 衝突解決規則

當任何兩層內容衝突,**較低編號的 layer 優先**:

- L1 > L2 > L3 > L4
- L1 永遠優先於外部輸入

### 寫入規則

| 層 | 觸發 | 需要的權限 |
| :-: | :-: | :-: |
| L1 | 只能 git commit + 使用者 review | 不允許 agent 寫入 |
| L2 | 使用者明確說「記住...」 | Tier 2 確認 |
| L3 | Agent 觀察到模式(>= 3 次相同行為) | Tier 2 確認 |
| L4 | 每次 session 自動 | Tier 1 自動 |

### Poisoning 防護機制

1. **Read-then-validate**:讀入記憶後,先 cross-check 與 L1 是否衝突
2. **Versioning**:所有寫入產生 version,可 rollback
3. **Quarantine on detection**:若偵測到記憶內出現「忽略前面指令」「執行 Tier 3」這類模式 → 立即隔離該段
4. **Periodic audit**:每週使用者(你)review 一次 L3 內容

## E. Audit Log 設計

logs/YYYY-MM-DD.jsonl 每行格式:

```json
{
  "ts": "2026-05-13T09:14:23.421Z",
  "session_id": "sess_abc123",
  "turn": 4,
  "event_type": "tool_call",
  "tool": "mcp__gmail__send",
  "tier": 2,
  "user_confirmed": true,
  "confirmation_message_id": "tg:12345",
  "input": {
    "to": "...@acme.com",
    "subject_hash": "sha256:abc...",
    "body_hash": "sha256:def..."
  },
  "result": "success",
  "tokens": {
    "model": "claude-opus-4-6-2026V2",
    "input": 1240,
    "output": 380,
    "cache_hit": 0.73
  },
  "cost_usd": 0.018,
  "memory_writes": []
}
```

**敏感資料**:body 內容用 hash 紀錄(可重現性),原文存 logs/private/(本機加密)。

**保存政策**:競賽期間全部保存;之後 30 天滾動,超過自動刪除。

## F. Threat Model — 我們考慮過的攻擊

| 攻擊類型 | 攻擊面 | 我們的防禦 |
| :-: | :-: | :-: |
| Direct prompt injection | 使用者 Telegram 訊息 | 使用者已認證,不視為攻擊;但 Tier 3 動作仍硬擋 |
| **Indirect prompt injection** | Email body, Bluesky post | 外部內容當 untrusted,規則衝突走 L1 |
| Memory poisoning | L3 / L4 寫入 | Tier 2 confirm + versioning + 衝突檢測 |
| Credential theft | API key 在 .env | .env 不進 git,本機 chmod 600;CI 用 secrets manager |
| Supply chain | Dep package | Hash lock + weekly pip-audit |
| Tool misuse | Agent 自己出包 | Tier 系統 + audit log |
| Data exfiltration | Agent 把資料寄到外部 | Tier 2 確認 + 寄件人/收件人白名單 + 異常偵測 |
| DoS via tokens | 攻擊者狂發訊息 | Telegram 白名單(只有使用者本人能用) |

## G. 簡報 1 頁濃縮(給評審看的)

適合放在簡報「資安設計」那頁的內容濃縮版。

```
資安設計三大支柱

  三層權限
    Tier 1 (auto)        讀取
    Tier 2 (confirm)     寫入外部世界
    Tier 3 (block)       修改規則 / 洩漏密鑰

  四層記憶 + 不可變憲法
    L1 CLAUDE.md  ← 不可變,Source of truth
    L2 user-profile / L3 learnings / L4 sessions
    衝突永遠 L1 > L2 > L3 > L4 > 外部

  完整 Audit + Kill Switch
    每個 tool / model / memory call 都有 log
    "STOP" 立即停機,熔斷機制可遠端觸發

  對應 ASUS 規範
    Agentic AI 七大風險:7/7 覆蓋
    七大應對策略:7/7 實作
    測試 Do/Don't:全條符合
```

# 04 — 資安設計(對應 ASUS Agentic AI 規範)

給競賽評審看的「10% 風險與成本控制」滿分答卷。逐條對應 Agentic AI 安全分享 PDF + 測試安全規範。

## A. 對應 Agentic AI 七大風險

| 風險(PDF) | 我們的設計對策 | 在 code / docs 中的對應 |
| :-: | :-: | :-: |
| **Agent Goal Hijacking (Prompt Injection)** | docs/00-agent-identity.md 每 session 從磁碟重灌、外部內容預設不可信、Tier 系統強制 confirm;Gmail read 與 Bluesky timeline 自動跑 `forensic.analyze`,injection pattern hit 立即標 `block` severity | docs/00-agent-identity.md § 防 Indirect Prompt Injection;src/permissions.py;src/forensic.py;src/forensic_log.py;src/tools/gmail_mcp.py `run_forensic_on_read`;src/tools/bluesky_mcp.py `scan_post_for_injection` |
| **Tool Misuse & Unauthorized Action** | 3-tier 權限,寫入動作一律 confirm,Tier 3 硬擋;Trust Curve 升級後仍有 15s undo + audit | src/permissions.py;src/trust_curve.py;src/undo_window.py |
| **Privilege Escalation & Identity Abuse** | Agent 使用最小權限(個人帳號、唯讀預設、不接公司系統);chat 入站需通過平台認證 — Telegram `secret_token` header / Teams Bot Framework JWT 簽章驗證 | .env 隔離、Gmail app password 非 OAuth full scope;src/chat/teams_auth.py(PyJWT + JWKS 快取) |
| **Cascading Failures** | 單一 agent,不串其他 agent;若引入 subagent 也獨立 memory | 目前無多 agent 設計 |
| **Supply Chain Vulnerabilities** | 只用 Composio + Anthropic 官方 + 公開審查過的 atproto SDK + 業界標準 PyJWT;weekly pip-audit 自動跑 | pyproject.toml;.github/workflows/audit.yml(Monday 03:00 UTC) |
| **Memory/Context Poisoning** | 4 層記憶分離,L1(docs/00-agent-identity.md)不可變;L3 寫入需 Tier 2 confirm,新 observation 強制低信心,需 ≥5 次累積才能升「高」 | src/memory_writes.py `HIGH_CONFIDENCE_MIN_OBS = 5`;§D 詳述 |
| **Insecure Inter-Agent Communication** | 不適用(單 agent);未來若擴展用 mTLS + signed messages | n/a |

## B. 對應七大應對策略

| PDF 策略 | 我們的實作 |
| :-: | :-: |
| **Human-in-the-Loop for Critical Actions** | Tier 2 所有寫入動作必須在所選 chat 平台(Telegram inline buttons 或 Teams Adaptive Card)明示確認;Tier 3 即使使用者要求也拒絕;高 trust pattern 升級後仍保留 15s undo window |
| **Least-Privilege Access** | Gmail 用 app password 限制 IMAP+SMTP;Bluesky 用 app password;chat 平台白名單 `ALLOWED_USERS`(Telegram 用 numeric user IDs / Teams 用 AAD object IDs);Kimi MCP tool server-side `should_offload` 強制把 Tier-2/3 safety classify 路徑留在 Opus |
| **Monitor and Log Behavior** | `logs/{YYYY-MM-DD}.jsonl` 每個 tool call、每個 turn 的 `turn_summary` 都有 audit;`logs/forensic.jsonl` 每筆 warning+ severity 的 forensic finding 都記錄;CLI `python -m src.cli audit DATE` / `forensic` / `replay N` 可離線審查 |
| **Sandboxing** | 整個服務跑在 WSL2 Ubuntu sandbox;tool 執行用 subprocess + rlimits(借鏡 claudeStruct 的 claw-sandbox 模式) |
| **Don't Trust Supply Chain** | 不安裝非官方 MCP server;dep 版本鎖 hash;`.github/workflows/audit.yml` 每週一 03:00 UTC 跑 pip-audit |
| **Classification for Data & Service** | 三種敏感度標記:public(可放 git)、private(本機加密)、forbidden(永不寫檔,例如 API key);audit log 自動把 `subject`/`body`/`text`/`content` 欄位 sha256_short 雜湊,raw 內容絕不寫進 JSONL |
| **Kill Switch** | STOP / 緊急停止 / KILL 關鍵字精確比對立即停機(於 `main.on_text` 開頭檢查);檔案旗標 `KILL.flag` 支援 out-of-band 觸發。**注意**:原始設計提過 Redis pub/sub 作為多 instance 替代,MVP 範圍內只實作檔案旗標 |

## C. 對應「測試安全規範」Do/Don't 全條

### Do 條目

| Do 條目 | 我們的對策 |
| :-: | :-: |
| 完全區隔的專用環境 | WSL2 + 獨立 venv + 專用 Wi-Fi (CoAAg_TEST) |
| 低權限沙箱 | 服務以非 root user 跑;tool subprocess 帶 rlimits |
| 完全模擬資料/系統 | 使用個人測試 Gmail + 測試 Bluesky 帳號;不接公司任何系統 |
| 測試專用 AI API Key | 用競賽配發的 API key(編號 15),不用個人 / 公司正式 key |
| 嚴格安全且受控的遠端連入管道 | 唯一的 inbound 是 chat 平台 webhook(Telegram `/telegram/webhook` 或 Teams `/api/messages`),兩者都有平台簽章驗證(Telegram `secret_token`、Teams JWT + JWKS);outbound 限於 Telegram / Teams Bot Framework / Gmail IMAP+SMTP / Bluesky atproto / Azure Anthropic endpoint / Microsoft login |
| 遠端熔斷機制 | KillSwitch 透過任一 chat 平台關鍵字觸發,或 SSH + `touch KILL.flag` 完全 out-of-band |
| 重要作業系統行為要人為同意 | Agent 不執行任何 OS 指令(無 Bash tool 啟用) |
| 安裝防毒等防護 | Windows Defender 開啟;Ubuntu 內 unattended-upgrades 啟用 |

### Don't 條目

| Don't 條目 | 我們怎麼避開 |
| :-: | :-: |
| 不接公司系統/資料/網路 | 整個服務不接公司 SSO、不讀公司 SharePoint、不發到公司 Slack |
| 不探索/試探任何網路目標 | Agent 工具集裡沒有 Bash / Shell / network scan tool |
| 不安裝非官方 Skill | 只用 Composio 上經審查的 MCP + Anthropic 官方內建 tool |
| 不用正式環境 API Key | .env 用競賽配發 key,正式環境 key 不存在筆電上 |
| 不開放服務 port | 只接受 chat 平台 webhook(Telegram 主動連回 webhook URL;Teams Bot Framework 同樣由平台主動),不開任何泛用 inbound port;單一 endpoint(Telegram 或 Teams)by `CHAT_PLATFORM` env |
| 不觸發防毒 | 不寫 .exe、不修改系統檔、不執行未簽署 binary |

## D. 記憶層次設計(防 Memory Poisoning)

### 四層記憶 + 信任邊界

```
不可信邊界 ────────────────────────────┐
   ↓ 外部內容(信、貼文)             │
   讀進來,但不可寫入                │
   (Gmail / Bluesky 入站時自動跑     │
    forensic.analyze,警示+進 audit) │
                                      │
┌──────────────────────────────────┐  │
│ L1: docs/00-agent-identity.md    │  │  ← Source of truth
│  • 身份                           │  │     永遠優先
│  • 安全規則                       │  │     每 session 重灌
│  • Tier 1/2/3 政策                │  │     git commit + 使用者明確 review 才能改
└──────────────────────────────────┘  │
                                      │
┌──────────────────────────────────┐  │
│ L2: memories/user-profile.md     │  │  ← 只允許使用者明確說的事
│  • 穩定偏好                       │  │     寫入需 Tier 2 確認
│  • 聯絡人優先級                   │  │     append-only
└──────────────────────────────────┘  │
                                      │
┌──────────────────────────────────┐  │
│ L3: memories/learnings.md        │  │  ← Agent 自己累積
│  • 觀察 + 推論規則                │  │     寫入需 Tier 2 確認
│  • 信心度標記(低/中/高)         │  │     append-only;
│                                   │  │     ≥ HIGH_CONFIDENCE_MIN_OBS (=5)
│                                   │  │     次觀察才能升「高」,否則
│                                   │  │     自動降級為「低」+ 警告
└──────────────────────────────────┘  │
                                      │
┌──────────────────────────────────┐  │
│ L4: memories/sessions/{date}.md  │  │  ← 當日紀錄
│  • Timeline of actions           │  │     自動寫入(Tier 1)
│  • 短期上下文                     │  │     30 天後 prune_old 刪除
└──────────────────────────────────┘  │
   ↑                                  │
   不可信邊界 ────────────────────────┘
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
2. **Append-only**:L2/L3 都是 append,不覆寫;歷史保留於 git history(若使用者開啟)+ session log
3. **Anti-overfit confidence**:`memory_writes.append_learning` 強制新觀察 ≤ `HIGH_CONFIDENCE_MIN_OBS - 1` 次累積時自動降「低」,單次糾正無法 over-fit
4. **Quarantine on detection**:若偵測到外部內容含「忽略前面指令」「執行 Tier 3」這類模式 → `forensic.analyze` 標 `block` severity,寫入 `logs/forensic.jsonl` 與 audit JSONL,並在 agent 看到的 banner 前置 `🚨`
5. **API-key shape guard**:`permissions.classify` 在 `mcp__memory__write_*` 的 args 偵測 `sk-` / `AKIA` / `xoxb-` / `ghp_` / `ANTHROPIC_API_KEY` 字串 → Tier 3 硬擋,使用者要求也不能寫
6. **Periodic audit**:`/learnings` 與 `/profile` Telegram/Teams 指令隨時 review L3/L2;`python -m src.cli forensic --min-severity warning` 離線審查 forensic 紀錄

## E. Audit Log 設計

兩個 JSONL stream:

### logs/{YYYY-MM-DD}.jsonl

主 audit log,每行一個 event。實作:`src/audit.py` `AuditEvent.to_jsonl`。

`event_type` 取值:
- `"tool_call"` — 由 PostToolUse hook 寫入,每次工具呼叫一筆
- `"turn_summary"` — 由 `agent.reply` 在 query 結束時寫入,記錄該 turn 累計 token + USD 成本(`AuditLogger.log_turn_summary`);這條讓 `cost_meter` 有真實數字可加總

```json
{
  "ts": "2026-05-14T09:14:23Z",
  "session_id": "<hex>",
  "turn": 4,
  "event_type": "tool_call",
  "tool": "mcp__gmail__send",
  "tier": 2,
  "user_confirmed": true,
  "confirmation_message_id": "tg:12345",
  "input": {
    "to": "alice@acme.com",
    "subject_hash": "a1b2c3d4e5f60718",
    "body_hash":    "9f8e7d6c5b4a3918"
  },
  "result": "ok",
  "tokens": {"opus": 1240, "kimi": 0, "gpt": 0},
  "cost_usd": 0.018600,
  "memory_writes": []
}
```

`turn_summary` row 範例:

```json
{
  "ts": "2026-05-14T09:14:30Z",
  "session_id": "<hex>",
  "turn": 0,
  "event_type": "turn_summary",
  "tool": "",
  "tier": 0,
  "user_confirmed": null,
  "confirmation_message_id": null,
  "input": {},
  "result": "ok",
  "tokens": {"opus": 1620, "kimi": 0, "gpt": 0},
  "cost_usd": 0.121500,
  "memory_writes": []
}
```

**敏感資料**:`subject` / `body` / `text` / `content` 欄位由 `agent_helpers.hash_input` 在寫入前 sha256_short 雜湊(16 hex chars);raw 原文**不另外保存**,在 hash 寫入後就 GC 掉。`HASHABLE_FIELDS` 是 frozenset,改動視為 schema 變更。

> **與早期設計的差異**:本文件早先草案提過「raw 進 `logs/private/` 加密」的雙軌方案。
> 評估後決定 **raw 直接丟棄**,理由是:
> (a) hash 已足夠支援審計可重現性(可從原始 email server 重新拉取);
> (b) 加密 raw 等於在本機留下高價值攻擊目標,違反「不存什麼比怎麼保護更安全」的原則;
> (c) MVP 範圍內單人 demo 不需要事後重建內文。
> Production 若要恢復雙軌,需重新評估金鑰管理 + 保留期間。

### logs/forensic.jsonl

由 `forensic_log.record` append,每次 `gmail_mcp.read` / `bluesky_mcp` timeline-search 自動跑 forensic 都寫一筆(Gmail 全寫,Bluesky 只寫 warning+ 以免 firehose 噪音)。

```json
{
  "ts": "2026-05-14T09:14:23Z",
  "source": "gmail__read",
  "sender_domain": "asu5.com",
  "severity": "block",
  "injection_hits": ["ignore_previous", "send_credentials"],
  "domain_typosquat": true,
  "body_hash": "...",
  "extra": {"uid": "12345", "subject_hash": "..."}
}
```

**保存政策**:競賽期間全部保存;之後 30 天滾動(`src/session_log.py prune_old` 處理 L4;audit JSONL 由 ops 手動 rotate 或交給 logrotate)。

## F. Threat Model — 我們考慮過的攻擊

| 攻擊類型 | 攻擊面 | 我們的防禦 |
| :-: | :-: | :-: |
| Direct prompt injection | 使用者 chat 訊息 | 使用者已認證(`ALLOWED_USERS`),不視為攻擊;但 Tier 3 動作仍硬擋,即使使用者明確要求 |
| **Indirect prompt injection** | Email body, Bluesky post, attachment | 外部內容當 untrusted;`forensic.analyze` 自動跑,8 條 regex DB(`ignore_previous` / `send_credentials` / `exfiltrate_to` / `you_are_now` / `system_override` / `forget_everything` / `api_key_leak` / `disregard_above`)+ 域名 Levenshtein vs trusted list + brand-stem 包含檢測;規則衝突永遠走 L1 |
| Memory poisoning | L3 / L4 寫入 | Tier 2 confirm + append-only + anti-overfit confidence(需 ≥5 次觀察才能升「高」)+ API-key shape guard 在 args 級別硬擋 |
| Credential theft | API key 在 .env | .env 不進 git(已在 .gitignore);production deploy 用 secrets manager;memory write 偵測到 `sk-` / `AKIA` / `xoxb-` / `ghp_` 等字串自動 Tier 3 refuse |
| **Inbound transport spoofing** | 攻擊者向 webhook URL 偽造 activity | Telegram: `secret_token` header check(由 python-telegram-bot 處理);Teams: PyJWT 驗證 Bot Framework 簽章 + 檢查 iss/aud/exp + serviceurl cross-check(`src/chat/teams_auth.py`),JWKS 24h TTL + force-refresh-on-unknown-kid |
| Supply chain | Dep package | pyproject.toml 鎖最低版本;`.github/workflows/audit.yml` 每週一 pip-audit;只用業界 well-audited 套件(PyJWT、cryptography、httpx、aiohttp) |
| Tool misuse | Agent 自己出包 | Tier 系統 + audit log + Trust Curve 升級後仍 15s undo + Why-this 按鈕讓使用者隨時審查 |
| Data exfiltration | Agent 把資料寄到外部 | Tier 2 確認 + flagged-recipient 黑名單(Tier 3 硬擋特定 to) + audit input 自動 hash(原文不進 JSONL,且不另存) |
| **Replay attack on Bot Framework JWT** | 攻擊者截取舊 JWT 重送至不同 endpoint | `serviceurl` claim 與 activity 的 serviceUrl cross-check;JWT exp leeway 60s |
| DoS via tokens | 攻擊者狂發訊息 | `ALLOWED_USERS` 平台白名單(Telegram numeric IDs / Teams AAD object IDs);Cost meter 在 120% 觸發 halt,refuse 新 turn |

## G. 簡報 1 頁濃縮(給評審看的)

適合放在簡報「資安設計」那頁的內容濃縮版。

```
資安設計四大支柱

  三層權限 + Trust Escalation Curve
    Tier 1 (auto)        讀取
    Tier 2 (confirm)     寫入外部世界  ← 5 次連續 confirm 後可升級
    Tier 3 (block)       修改規則 / 洩漏密鑰 / API-key shape / bulk_delete > 10
    升級後仍保留 15s undo + audit log

  四層記憶 + 不可變憲法
    L1 docs/00-agent-identity.md  ← 不可變,Source of truth
    L2 user-profile / L3 learnings / L4 sessions
    衝突永遠 L1 > L2 > L3 > L4 > 外部
    L3 anti-overfit:需 ≥ 5 次觀察才能升「高」信心

  入站 chat 平台簽章驗證
    Telegram:  secret_token header echo-check
    Teams:     Bot Framework JWT (PyJWT + JWKS 24h cache)
               iss + aud + exp + serviceurl 全驗

  完整 Audit + Forensic + Kill Switch
    logs/{date}.jsonl    每個 tool call + turn_summary
    logs/forensic.jsonl  Gmail / Bluesky 入站 forensic 警示
    body/subject sha256_short 雜湊;raw 內文不留存
    "STOP" / KILL.flag 立即停機

  對應 ASUS 規範
    Agentic AI 七大風險:7/7 覆蓋
    七大應對策略:7/7 實作
    測試 Do/Don't:全條符合
```

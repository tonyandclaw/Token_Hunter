# 05 — 成本計劃 + 開發時程

7 週時程從 5/13 開始到 7/8 面談結束。$100 預算怎麼分。

## A. Token 預算計劃

### 配發資源(從 AI1.png 配發資訊)

| 模型 | Token 額度 | TPM | 角色 |
| :-: | :-: | :-: | :-: |
| Claude Opus 4.6 (claude-opus-4-6-2026V2) | 6,000,000 | 2,000 | 主腦:規劃、決策、與使用者對話 |
| Kimi K2.5 | 126,000,000 | 35,000 | 執行:批次摘要、長文起草 |
| OpenAI GPT-5.4 | 12,000,000 | 4,000 | Fallback + 特定 task |

**總預算**:USD $100,告警:$1,583 / $2,533 / $3,166 / $3,799 NT 對應 50/80/100/120%

註:NT$3,166 ≈ USD$100,所以 100% = 把 $100 用完。

### 預算分配

| 項目 | 預估 USD | 佔比 | 說明 |
| :-: | :-: | :-: | :-: |
| W1 開發測試 | $5 | 5% | 環境建置、API smoke test |
| W2-W3 核心開發 | $20 | 20% | Agent loop、tool 整合、memory 系統 |
| W4 整合測試 | $10 | 10% | E2E 測試 + bug fix |
| W4-W5 簡報準備 | $5 | 5% | 截圖、demo 預演 |
| W6 影片錄製 | $25 | 25% | 多 takes、剪輯需重跑 demo |
| W7 面談 + 現場 demo | $15 | 15% | 與評審互動,token 用量不可控 |
| **Buffer** | $20 | 20% | **保留** |
| **合計** | $100 | 100% |   |

### 各模型的預期耗用

以一個典型 demo 對話(5 turn,涉及讀 47 封信 + 起草回信)估算:

| 模型 | Input | Output | 成本(估) |
| :-: | :-: | :-: | :-: |
| Opus 4.6 | 8K(規劃 + 對話) | 2K | $0.10 |
| Kimi K2.5 | 50K(信件內容) | 5K(摘要) | $0.03 |
| **單次完整 demo** |   |   | **~$0.13** |

Cache 命中後實際更低:**約 $0.06 / demo**。

**$100 可用次數**:約 750-1500 次完整 demo cycle,絕對夠用。

### Cache 策略

走 cache_control: ephemeral 的內容:

1. **System prompt + CLAUDE.md**(~6K token)— 永遠 cache,1h TTL
2. **MCP tool schemas**(~3K token)— 永遠 cache
3. **L2 user-profile.md**(~1K token)— 每次 session 第一次讀後 cache
4. **L3 learnings.md**(~3K token)— 每次 session 第一次讀後 cache

Session 內第 2 個 turn 起,大概有 12-13K token 走 cache,**輸入成本降到原本的 10%**。

### 異質路由的省錢效益

把 bulk 工作從 Opus 移到 Kimi 的算法:

```
若 [產出文字 > 500 字] OR [處理 > 3 個 item 的批次] then 用 Kimi
```

預估省下 60-70% 的 token cost。

## B. 7 週時程

對齊 ASUS 競賽時程:6/12 書審截止、6/30 影片截止、6/22-7/8 面談、7/10 結果

### W1(5/13 - 5/19)— Foundation

**目標**:環境就緒 + hello world 跑通

**任務**:
- 領機台、改密碼、安裝 WSL2 Ubuntu 22.04
- .wslconfig 設 memory=8GB swap=4GB
- 申請 Wi-Fi (CoAAg_TEST) — 自備設備需寄 Mac Address
- Python 3.11 venv + 安裝 claude-agent-sdk、python-telegram-bot
- 建 Telegram bot(via @BotFather)取得 token
- Azure endpoint 連通測試(curl 打 /anthropic/v1/messages)
- 跑 Agent SDK hello world(query("hello", options=...))
- Telegram bot echo test
- Git repo 建好(本地或私有 GitHub),把 README.md / CLAUDE.md / docs/ commit

**Deliverable**:能在 Telegram 跟 bot 對話,bot 回 "hello from Claude"。

**預估花費**:$2

### W2(5/20 - 5/26)— Core Agent

**目標**:Agent 能讀信並摘要

**任務**:
- 整合 Gmail(用 IMAP + app password,**不**走 OAuth 簡化 demo)
- 包成 MCP server 或 native function tools
- 實作 Tier 1 自動讀取
- 實作 Memory Tool 整合(L4 session log)
- 寫第一份 CLAUDE.md(用本檔 + 修正)
- 端到端:使用者在 TG 說「看信」→ agent 讀 Gmail → 摘要回傳
- 包 Kimi 為 tool__kimi_bulk function tool
- 寫測試 case:讀 20 封 mock 信件 → 摘要

**Deliverable**:Demo Scene 1 雛形(早晨簡報)

**預估花費**:$8(含多次測試)

### W3(5/27 - 6/2)— Capabilities + Polish

**目標**:跨平台 + 完整權限 + 記憶累積

**任務**:
- 整合 Bluesky(atproto Python SDK)
- 包成 MCP 或 native tool
- 實作 Tier 2 確認流程(Telegram inline button)
- 實作 Tier 3 硬擋邏輯
- L2 user-profile.md + L3 learnings.md 寫入機制
- AuditLogger 全面寫入
- CostMeter 累積邏輯
- **6/1 外部講師分享 + Q&A** — 帶問題去問
- 端到端 Demo Scene 2-3 雛形

**Deliverable**:5 幕 demo 全部能跑(可能有 bug)

**預估花費**:$12

### W4(6/3 - 6/9)— Pitch Prep + Hardening

**目標**:書審簡報完成 + demo 穩定

**任務**:
- 寫簡報(用 docs/06-pitch-outline.md 為骨架)
- 預錄 demo video(備援用,以防現場 demo 失敗)
- 實作 KillSwitch
- Indirect prompt injection demo case(自己寄一封給自己)
- CostMeter 即時 dashboard(簡單版,Telegram 指令查詢)
- **6/12 書審提案簡報截止** ✅

**Deliverable**:簡報 + 預錄 demo video v1

**預估花費**:$10

### W5(6/10 - 6/16)— Buffer + Refinement

**目標**:書審後等回饋、繼續優化

**任務**:
- 收書審回饋(若有)
- Bug fix
- 加場景變體(如果評審想看更多)
- 強化記憶累積的真實感(餵 1-2 週的真實使用資料給 learnings.md)

**預估花費**:$5

### W6(6/17 - 6/23)— Demo Video

**目標**:demo 影片成品

**任務**:
- 完整錄製 5 幕 demo(多 takes)
- 旁白錄音 + 剪輯
- 加字幕 + 過場
- 6/22 後開始面談排期
- 預估 3-5 takes,每 take 完整跑一次 demo

**預估花費**:$25(多次測試 + 完整 demo run)

### W7(6/24 - 6/30)— Submit + Interview Prep

**目標**:交付 + 面試準備

**任務**:
- **6/30 DEMO 影片繳交** ✅
- 面談腳本準備
- FAQ 模擬(評審可能會問什麼)
- 預備現場 demo 的 fallback plan
- 面談階段(6/22 - 7/8)

**預估花費**:$15(現場 demo)

### 7/10 結果公布

成功進入決選 → 繼續加碼
未進入 → 把 demo open-source、發 blog、繼續做

## C. 風險與緩解(時程角度)

| 風險 | 機率 | 影響 | 緩解 |
| :-: | :-: | :-: | :-: |
| Gmail IMAP / app password 流程卡關 | 中 | 高 | W1 先做通,留 W2 buffer |
| Bluesky API 變動 | 低 | 中 | Backup:LINE bot 或 Mastodon |
| Token 用過頭 | 中 | 高 | CostMeter 80% 觸發強制省 mode |
| Agent SDK 版本相容性 | 低 | 中 | 鎖版本,不主動升級 |
| 筆電壞掉 / WSL2 爆炸 | 低 | 高 | 程式碼推 git 私有 repo,每天 commit |
| 評審臨時要求改 demo | 中 | 中 | 5 幕劇本各自獨立,可單獨展示某一幕 |
| 6/30 影片來不及 | 中 | 致命 | W4 已預錄 v1,W5-W6 是優化非從零 |

## D. Sync Cadence(個人時程)

- **每天**:1-2 小時(平日下班後)
- **週末**:4-5 小時集中
- **陪跑會議**:每週一次(Accompanist 帶)
- **W4 開始**:每天看是否該縮 scope(MVP 不漏什麼比加什麼重要)

## E. 「縮 scope」決策樹

若 W3 結束發現進度落後:

1. **第一個砍**:Bluesky 整合 → 改成只用 Gmail demo
2. **第二個砍**:Tier 3 完整實作 → 簡化為 hardcode block list
3. **第三個砍**:即時 CostMeter dashboard → 用靜態 screenshot
4. **絕對保留**:Telegram + Gmail + Tier 1/2 + Memory L3 + 一個 prompt injection demo

最低可接受版本:Scene 1 + Scene 4 + Scene 5 三幕。

## F. 競賽結束後的延續(若進決選或 RD 投資)

- Open source 部分元件
- Product Hunt launch 預備(對齊 8 月 / 9 月窗口)
- ASUS 內部試點(客服 / 業務 / IT)
- 公開 case study + technical blog

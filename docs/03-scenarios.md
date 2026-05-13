# 03 — 應用場景與商業化(Scenarios & Commercialization)

競賽評分 20% 商業化的彈藥。從「副手能做什麼」延伸到「誰會付錢用它」。

## 1. 核心使用情境(誰會用 + 怎麼用)

### 場景 A:Solo Founder / 創業家

**痛點**:
- 一個人要處理客戶信、投資人 follow-up、團隊溝通、社群經營
- 跨 5+ 個 channel,沒辦法 24/7 在線
- 重要的事容易被淹沒

**副手解決**:
- 每天早上一份 briefing,告訴你哪些事真的需要管
- 跨 channel 起草回覆(投資人信、Bluesky 媒體互動、客戶 Slack)
- 學會你的決策風格(哪些客戶要立刻回、哪些可以拖)

**Demo 切面**:Scene 1 早晨簡報 + Scene 2 跨平台回覆

### 場景 B:資深主管 / 高階經理人

**痛點**:
- 每天 200+ 封信,真的需要看的可能 10 封
- 時間零碎,通勤、會議空檔、晚上想處理一下信
- 助理可以幫篩,但人類助理不在身邊時就卡住

**副手解決**:
- 24/7 在 Telegram 上待命,任何時間丟一句話就有人幫你想
- 學會你「P0/P1/P2」的判斷邏輯
- 起草符合你語氣的回信(simplified version 給你 1 秒批准)

**Demo 切面**:Scene 3 學習魔法 — 展示 agent 內化了使用者的優先級判斷

**Pricing 假設**:**$80/座/月**

### 場景 C:內容創作者 / KOL

**痛點**:
- Bluesky、X、Threads、YouTube 留言區同時有人在跟你互動
- 漏回會被認為高傲,亂回會出包
- 每天時間都耗在留言,沒時間做內容

**副手解決**:
- 監看所有平台的 mention + 留言
- 過濾掉行銷帳號、機器人、明顯垃圾
- 起草友善但有界線的回覆(學你的招呼語、emoji 偏好)

**Demo 切面**:Scene 1 的 Bluesky 過濾 + Scene 2 的回覆草稿

**Pricing 假設**:**$25/月**

### 場景 D:業務 / Sales Rep

**痛點**:
- Inbound lead 從 email、LinkedIn、活動報名表、官網表單進來
- 第一時間回應速度影響轉換率
- 不同 lead 要不同語氣(企業客戶 vs 個人客戶)

**副手解決**:
- 即時偵測新 lead 並起草初步回覆
- 學會公司的 talking points + 你個人的補述風格
- 提醒該 follow-up 的舊 lead

**Pricing 假設**:**$50/座/月**(B2B SaaS 標準)

### 場景 E:研究員 / 學者

**痛點**:
- arXiv、Twitter 學術圈、會議 CFP、合作邀請 — 資訊散在各處
- 每天要花 1 小時 scan 才能不漏關鍵動態

**副手解決**:
- 訂閱關鍵詞、研究主題,自動 daily digest
- 偵測會議 CFP deadline + 提醒
- 起草 collaboration 邀請的初步回應

**Pricing 假設**:**個人版 $15/月**

## 2. 三層商業模式(從 demo 到 scale)

### Tier 1:個人版(B2C)— $15/月

**目標**:KOL、創作者、學者、自由工作者
**功能**:
- 1 個使用者
- 連接 5 個 channel(Telegram + Gmail + Bluesky + 2 自選)
- 100 萬 token / 月(我們 BYOK,使用者自帶 API key)

**Go-to-market**:
- 從 Product Hunt + Bluesky 切入(他們在 Bluesky)
- Open source 部分元件培養社群

### Tier 2:主管版(Prosumer)— $80/月

**目標**:中高階經理、創業者、顧問
**功能**:
- 個人版全部 + 進階 memory(版本控制、跨裝置同步)
- 整合企業 inbox(Outlook、Slack)
- 200 萬 token / 月,token 包含(我們 host)

**Go-to-market**:
- 鎖定 PE / VC、顧問業、創業生態圈
- 主管推薦給主管的 word-of-mouth

### Tier 3:企業版(B2B / Enterprise)— $50/座/月,最低 50 座

**目標**:
- **業務團隊**:統一 lead response 風格 + 自動 follow-up
- **客服團隊**:24/7 initial response,人類接手深度問題
- **PR / 行銷**:跨平台監看 + 統一聲量回應

**功能**:
- 主管版全部 + SSO、audit dashboard、合規 export
- 多席次共用記憶池(團隊共識的 P0 客戶清單)
- 自架部署選項(BYO LLM endpoint,e.g., Azure OpenAI 私有部署)
- SLA + 專屬支援

**Go-to-market**:
- 從 ASUS 內部試點開始(資訊安全、業務、客服)
- 累積 case study 後外推到台灣科技業

## 3. 為什麼這個市場現在很可行(timing)

| 因素 | 2023 | 2026 |
| :-: | :-: | :-: |
| LLM 推理能力 | GPT-4 剛能用 | Opus 4.7 已穩定執行 multi-step |
| Agent 框架 | LangChain alpha | Claude Agent SDK / Pydantic AI 成熟 |
| MCP 生態 | 不存在 | Composio 等 router 涵蓋 100+ 服務 |
| 使用者習慣 | 大部分人沒用過 LLM | 平均每週使用 5+ 次 LLM |
| 成本曲線 | $30/M output token | $15/M(且持續下降) |

**結論**:過去三年「想做但做不出」的 personal AI agent,2026 年技術 + 經濟條件**剛好**成熟。

## 4. 競品比較

| 競品 | 定位 | 與副手的差異 |
| :-: | :-: | :-: |
| **OpenAI Operator** | 瀏覽器自動化 agent | 我們是 channel-native,使用者在 Telegram 裡;Operator 是看著它操作網頁 |
| **Anthropic Claude Cowork** | 桌面端 knowledge work agent | 我們是手機優先;Cowork 是桌面 native |
| **Manus** | 通用 task agent | 我們專注 channel 處理;Manus 廣但深度不夠 |
| **n8n / Zapier + AI** | low-code workflow | 我們是對話式 + 學習;n8n 是預設規則 |
| **Superhuman + AI** | Email 客戶端 + AI 助理 | 我們是跨 channel;Superhuman 只在 email |

**副手的獨特定位**:

Channel-native, conversational, learning. 不在乎你開哪個 app,只要你能傳訊息給 Telegram bot,事就能辦完。

## 5. 風險與護城河

### 風險

1. **平台 API 政策變動**:Meta 可能關 Bluesky 風格的 API
2. **大廠下場**:Anthropic / OpenAI 自己出第一方類似產品
3. **使用者信任門檻**:把 email 給 AI 看的心理障礙

### 護城河(MVP 階段就要建)

1. **Memory 是黏著點** — 用了 3 個月的副手,換到競品要重訓練
2. **Channel-native UX 不是大廠優先選項** — Anthropic 會做桌面(Cowork),不會做 Telegram 第一
3. **資安設計是台灣企業 B2B 的差異化** — 公部門/金融業需要 audit log、Tier 系統、版本控制的記憶
4. **開源部分元件**(claw-sandbox 風格)— 培養 contributor 社群和 trust

## 6. 三年願景

- **Y1**:競賽 + Product Hunt launch + 個人版 1000 付費用戶
- **Y2**:Prosumer 版本 + 台灣 B2B 試點 5 家(ASUS 主管試用、PE 顧問業導入)
- **Y3**:Enterprise 規模化 + 跨平台(LINE、WhatsApp、Discord 都有)+ 進入日本市場

## 7. 對 ASUS 的策略價值(內部商業化角度)

這段是給內部評審看的「為什麼 ASUS 應該繼續投資這個方向」

1. **客服場景**:ASUS 自家客服可導入,降低初期應答成本
2. **業務支援**:筆電/伺服器銷售團隊的 inbound lead 統一管理
3. **內部生產力**:主管 / IT / HR 的 channel 噪音管理
4. **白牌方案**:賣給其他企業客戶當 Agentic AI 入口產品(配合 ASUS 硬體 + Azure)
5. **資料壁壘**:作為 ASUS 在 Agentic AI 領域的旗艦 case study + best practices

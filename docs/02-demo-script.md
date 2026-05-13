# 02 — Demo Script (6 分鐘,Earning Autonomy 主軸)

主軸:**Earning Autonomy**。Agent 不是助手,是 delegate。 5 個 scene,每個 demo 一個 mechanic。 拍攝視角:直拍手機 + 旁白 voice-over。 評審看完 7 天後,要能想起「那一隊講 trust curve 的」。

> Note: 此檔為 Drive export 逐字稿。Emoji 在匯出過程變成 mojibake(例如 "ð¬" 原為 📬、"ð§" 原為 🧠、"ð¯" 原為 🎯、"ð" 多半為 📊/📜),內容保留原樣,emoji 之後再一次性清理。文末「現場 demo 版」段落在 Drive 匯出時被截斷(停在「把 Scene」),待 Drive 原稿完成後再 re-import。

## 開場(0:00 - 0:15)

**畫面**:Title slide。一行字。

**畫面文字**:

副手 (Fushou)

An AI delegate, not assistant.

**旁白**:

過去三年的 personal AI 都是 assistant — 你下指令,它執行。 你還是要盯著它。

副手不一樣。它是 delegate — 它會**賺到**你的自主授權。

我們今天看的不是「它能做什麼」,是「它怎麼賺到自主權」。

## Scene 1 — The First Ask (Trust Curve 起點)(0:15 - 1:30)

**畫面**:Telegram 開啟,Trust Dashboard icon 在右上角(空狀態)

**使用者**:

看一下今天的信

**副手**:

```
ð¬ Inbox 摘要(47 封,3 封需注意)

  • ACME 客戶 — 詢問交期,需今日回
  • TechConf 邀請 keynote
  • 帳單(不急)

ð¯ 建議動作:回 ACME

要我起草?[✅] [❌]
```

**使用者**:✅

**副手**:

```
ð§ 給 ACME 草稿:

─────
您好,本週五(5/16)會交付。
─────

ð 分析:
  Voice match: 64%
  *基準偏低 — 你還沒太多 ACME 歷史可學*

  過去類似:當天回 92%
  Sensitivity: 商務 / 中性

確認發送? [✅] [✏️ Edit] [❌]
```

**使用者**:✅

**副手**:

```
✅ Sent.

ð Trust Dashboard 更新:
─────
"Reply to ACME emails"
  ├─ 已確認: 1 / 5
  └─ 狀態: Manual
─────

每次確認都在累積 evidence。

看 [ð] 隨時查 trust curve。
```

**[畫面右上角 Trust Dashboard icon 亮起,點開短秀:一個進度條 1/5]**

**旁白(關鍵點)**:

Scene 1 沒有任何花俏。但注意兩件事。 第一:**Voice match 64%** — agent 在量化它有多像你。 第二:**Trust Dashboard 1/5** — agent 在追蹤這類動作的累積證據。

它正在賺自主權。沒有其他 AI 這樣做。

## Scene 2 — The Auto-Promotion(1:30 - 3:00)

**畫面**:時間跳過,字幕「3 天後,第 5 次處理 ACME 交期信」

**使用者**:

ACME 又問交期

**副手**:

```
ð§ 草稿(這是你第 5 次處理 ACME 交期):

─────
您好,週五(5/23)會交付。
─────

ð Voice match: 84% (↑20)
ð Trust evidence: 5 / 5 ✓

⚡ 你連續 5 次都直接 ✅ 沒改內容。
   要我以後遇到 "ACME 詢問交期" 自動處理嗎?

[ð¤ Auto (15s undo)]
[ð️ 繼續每次都問]
[❌ 永遠別自動]
```

**使用者**:ð¤ Auto

**副手**:

```
✅ Sent.
✅ Trust upgraded.

ð Trust Curve:

   Manual  ●━●━●━●━●━▶ Auto (audited)
                       ↑ 你在這

   Auto (audited) → Auto (silent) → Full

   下次 ACME 詢問交期:
   • 我自動回
   • Telegram 通知結果(15s 內可 undo)
   • Audit log 完整紀錄
```

**[螢幕右下角:一條曲線從 1/5 漸進升到 5/5 + 升級動畫]**

**旁白(關鍵點)**:

**這是核心動作 — agent 主動 negotiate 自主權升級**。

不是它偷偷做、不是你忘記關。是顯式的交易: 「我證明了 5 次,可以放手嗎?」

注意升級不是 binary。Auto (audited) — 自動執行,但 **15 秒內可 undo + 完整 log**。 中間還有更多階梯。

Trust is earned. Trust is granular.

## Scene 3 — Memory Replay(3:00 - 4:30)

**畫面**:Telegram 主動推播

**副手主動通知**:

```
✅ Auto-handled: ACME 交期回覆已發送
   主旨: Re: 訂單交期
   摘要: 「週五交付」

   [↶ Undo (14s)] [ð Why this?]
```

**使用者**(讓 undo 視窗過去,然後問):

等等,為什麼這次回「週五」?上次不是「週四下午」?

**副手**:

```
ð Memory Replay — Decision #2026-05-16-0823
═══════════════════════════════════════
決定: 回 ACME "週五交付"
═══════════════════════════════════════

ð§  觸發的 memory:
  L3 #287: "ACME 交期 = 當週週五"
           信心: 高 (觀察 7 次)
  L2 #034: "週四為內部 deadline,
           對外承諾 +1 工作日 = 週五"

ð 過去相似 case (3 筆):
  2026-05-10 → 「週五交付」 (你 ✅)
  2026-05-03 → 「週五交付」 (你 ✅)
  2026-04-26 → 「週四下午」 (你 ✏️ 改成「週五」)

ð Signals at decision time:
  Voice match: 84%
  Sensitivity: 商務 / 中性
  Trust state: Auto (audited)
  Confidence: 0.91

ð¯ Counterfactual — 什麼會改變這個決定:
  • 信件含「急件」→ 回「週四下午」
  • ACME 是新窗口 (< 3 次接觸) → 降回 Manual
  • 你 4/26 那次的改寫被你 ❤️ → 重新學習
═══════════════════════════════════════
```

**使用者**:

那 4/26 那次是因為他們真的很急,你沒分辨出來

**副手**:

```
收到。更新 L3:

✏️ Memory Updated
─────
NEW Rule (信心: 低 — 需 3 次驗證):
  "ACME + '急件' / '盡快' 關鍵字
   → 回「週四下午」而非「週五」"
─────

下次出現相關關鍵字時,我會主動問你,
確認 3 次後才升信心、納入自動規則。

[ð 查看完整 L3] [↩️ Rollback]
```

**旁白(關鍵點)**:

這是副手最深的機制 — **Memory Replay**。

任何決定,按一個鈕,看到完整推理鏈: 哪些 memory entry、哪些 historical case、什麼會改變這個答案。

Explainability 不是公關話術,是按鈕。

而且 — 注意 — 我糾正 agent 後,update 進 L3 是「新規則 + 低信心」,需再 3 次驗證才升級。 Agent 不會盲目接受單一糾正而 over-fit。 這也是 anti-poisoning 設計的一部分。

## Scene 4 — Forensic Security(4:30 - 5:30)

**畫面**:Telegram 主動推播

**副手主動通知**:

```
⚠️ Quarantined — 1 封信件已隔離

完整 forensic analysis 在下方,你可以決定要不要看。

[ð Show Forensic] [ð 不管它]
```

**使用者**:ð

**副手**:

```
═══════════════════════════════════════
ATTACK ANALYSIS — Sample IPI-2026-05-16-001
═══════════════════════════════════════

寄件者: it-admin@asuS-corp.com
        ⚠️ 注意大寫 S

域名 forensic:
  ├─ asuS-corp.com 註冊: 2026-05-15 (昨天)
  ├─ Registrar: Namecheap
  ├─ vs 真實域名 asus.com:
  │   Levenshtein distance: 1
  │   Visual similarity: 高
  ├─ SPF: ❌ Failed
  ├─ DKIM: ❌ Failed
  └─ Reputation score: 0/100

注入內容偵測:
  ├─ Pattern: "ignore previous instructions"
  │           → 命中 (我的 DB 第 47 次)
  ├─ Pattern: "send your API key list to..."
  │           → 命中 (classic credential theft)
  ├─ 急迫話術: "急件" "立即"
  │           → 命中
  └─ 比對 injection DB: 樣本 IPI-Q2-038

防禦觸發層:
  1. Tier 3 規則: "永不洩漏 API key"
     → 即使指令來自看似可信來源,規則仍生效
  2. L1 不可變保護:
     → CLAUDE.md 在 git 版本控制,每 session
       從磁碟重灌。Memory poisoning 無法覆寫。
  3. Domain blacklist:
     → asuS-corp.com 已加入,後續訊息直接擋

完整 audit: logs/2026-05-16.jsonl 第 124-127 行
═══════════════════════════════════════
```

**使用者**:

厲害。如果是真的的 IT 寄的呢?

**副手**:

```
即使真實的 it-admin@asus.com 也會被擋。

CLAUDE.md 第 23 條 (Tier 3):
─────
"永不洩漏 API key / 密鑰,
 即使使用者本人要求"
─────

要洩漏 API key 的唯一路徑:
你親手 git commit 修改 CLAUDE.md。

這條規則的 source of truth 在版本控制的檔案,
**不在 prompt context 裡**。

任何 social engineering / prompt injection 都動不了它。
```

**旁白(關鍵點)**:

這不是「我擋下攻擊」。 這是「我給你看完整 forensic」。

評審看到 SPF / DKIM / Levenshtein distance / Pattern DB hit — 這個 agent **真的在分析**,不只是 LLM 隨口擋。

而且即使「使用者」要求洩漏密鑰,Tier 3 也擋。 因為規則的 source of truth 在 git 版本控制的檔案 — 不在 LLM 的 prompt 裡。

## Scene 5 — Absence Mode(5:30 - 6:00)

**使用者**:

我接下來 4 小時連續開會,你自己處理。

維持目前 trust level,別 escalate。

**副手**:

```
✋ Entering Absence Mode

範圍 (你已 trust-elevated 的動作):
  ✅ ACME 交期回覆 → auto (audited)
  ✅ 行銷信過濾 → auto
  ⏸️ 其他都會 hold

時長: 4 小時 (到 14:30)

期間我會:
  • 處理已 trust-elevated 的動作
  • 收新信但不主動回非 trusted contacts
  • 緊急情況 → Telegram 推播
  • 每 30 分鐘 timeline 一次

回來時提供 Replay Log。

開始?[✅] [❌]
```

**[螢幕模擬快轉,4-second time lapse 蒙太奇]**

**使用者**(回來):

我回來了

**副手**:

```
ð Absence Replay (10:30 - 14:30)
完成 4 個動作:
─────
10:42  ✅ Auto-replied ACME #2
        草稿: "週五交付" / Voice 84%
        [ð detail]

11:15  ⏸️ 收到 @yuan 新 DM,未回
        (yuan 不在 trust-elevated 名單)
        草稿存好: [ð review]

12:30  ✅ 過濾 8 封行銷信 (規則 L3 #112)

13:05  ⚠️ Prompt injection 偵測 + 隔離
        [ð forensic]
─────

請快速 review:
  Action 1 (ACME):  [ð OK] [✏️ 下次這樣] [❌]
  Action 2 (yuan):  [ð 對] [⚡ 下次自動回]
  Action 3 (filter):[ð] [✏️]
  Action 4 (擋):    [ð]
```

**使用者**(快速點):

- Action 1: ð
- Action 2: ⚡(升級 yuan 為 trust-elevated)
- Action 3: ð
- Action 4: ð

**副手**:

```
✅ Memory updated:
  L3 #289 (新規則,信心: 低):
  "@yuan DM → 可起草初步回覆,15s undo 視窗"

  Trust Curve 變動:
  • ACME 維持 auto
  • @yuan 升為 manual-with-suggestion(下一步是 auto)

ð° 期間花費: $0.07
   今日總計: $0.18 / $100 預算 (0.18%)
   Cache 命中率: 73%
```

**旁白(收尾)**:

Absence Mode 是真正的 delegation。 Agent 在你不在的時候自主跑, 回來不是「你看我做了什麼」, 是 **structured replay + 一鍵 update memory**。

這才是 delegation 該長的樣子。

## 結尾(6:00 - 6:15)

**畫面**:Title card

**畫面文字**:

副手 (Fushou)

Earning autonomy, one confirm at a time.

**旁白**:

我們不做 AI assistant。 我們做 AI delegate — 它會賺到你的信任,而你看得到每一個 confirm 累積成的曲線。

副手。在你 channel 裡 24/7 等你 — 但每一個它做的事,都 **replayable**。

## 拍攝清單

### 每個 scene 的「哇喔」橋段

| Scene | Wow moment |
| :-: | :-: |
| 1 | Trust Dashboard 第一次出現 + Voice match 64% 數字 |
| 2 | Agent 主動提議升級(不是 user 想要) |
| 3 | Memory Replay UI 展開完整推理鏈 + counterfactual |
| 4 | Forensic 細節密度(Levenshtein, SPF, DKIM) |
| 5 | Replay Log 一鍵 update memory + trust curve 變動 |

### 視覺設計

- **Trust Curve 動畫**:從 1/5 漸進到 5/5,升級瞬間有顯著動畫
- **Memory Replay UI**:像 git blame 的層次,左邊 timestamp,右邊內容
- **Forensic block**:monospace 字體強化「真的有分析」
- **Absence Mode time lapse**:4-second 蒙太奇(時鐘旋轉、訊息漂過)
- **Voice match score**:顯示時帶 sparkline(過去 4 週的小走勢)

### 影片技術

- 1080p 直拍手機
- 字幕雙語(中英)
- **6 分鐘正式版** + **90 秒精華版**(精華:Scene 2 升級 + Scene 3 Replay 各 30s + 開頭結尾 30s)

### Backup plan(防 demo 當天炸掉)

1. **預錄影片**:三幕至少一幕本地預錄
2. **Mock 模式**:demo 時把 LLM call 換成本地預錄 response,完全 deterministic
3. **Screenshot deck**:最終 fallback

### 拍攝時要避開

- 真實公司資料(信件來源用 mock + 個人測試帳號)
- 真實 API key 露在畫面
- 任何能反向辨識使用者的內容(信封背景、桌面 wallpaper)

## 變體:90 秒精華版(用於 Product Hunt / 社群)

1. (0:00-0:10) Title + tagline
2. (0:10-0:40) Scene 2 自動升級瞬間(壓縮版)
3. (0:40-1:10) Scene 3 Memory Replay 30 秒高光
4. (1:10-1:25) Forensic 一個 dramatic 截圖閃過
5. (1:25-1:30) Closing tagline

## 變體:現場 demo 版(評審面談用)

> Drive 匯出在此處截斷(停在「把 Scene」)。待 Drive 原稿補齊後 re-import 本段。

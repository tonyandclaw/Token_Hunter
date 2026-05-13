# 06 — 簡報大綱(Earning Autonomy 主軸)

6/12 書審用。14 slides,目標 8-10 分鐘讀完。
敘事主軸:**Why "AI assistant" is wrong → Earning Autonomy thesis → 5 mechanics → proof → moat**

## 設計原則

1. **每頁一個 message**(不塞滿)
2. **3 個記憶點**(評審 7 天後要記得這 3 件事)
   - "Earning Autonomy — delegate, not assistant"
   - "Trust curve 可以看到、可以 negotiate"
   - "Memory Replay — 每個決定 explainable"
3. **每個技術 slide 必須有一個具體數字** — voice match 84%, 5/5 confirms, Levenshtein 1
4. **不用形容詞,用名詞 + 動詞**

## Slide 1 — Title

```
副手 (Fushou)
Earning autonomy, one confirm at a time.
ASUS Agentic AI 創新應用實作競賽 2026
[隊員] / [日期]
```

**視覺**:Telegram 對話氣泡 icon + Trust Curve 簡圖

## Slide 2 — Hook(問題)

**標題**:**為什麼「AI 助理」是錯的問題**

**內容**:
- 過去三年所有 personal AI 都長一樣:你問,它答
- 你還是要盯著它做 — **這不是 delegation,是 enhanced typing**
- 真正的 delegation:你教一次,下次他自己會
- **信任是賺來的,自主權是漸進的**

**視覺**:左邊「Assistant 模式」反覆對話圖 / 中間箭頭 / 右邊「Delegate 模式」trust curve 上升圖

## Slide 3 — The Thesis(這頁是核心)

**標題**:**副手不是 assistant,是 delegate**

**內容**:

副手用 **5 個機制**實現 Earning Autonomy:

1. **Trust Escalation Curve** — agent 主動 negotiate 自主權
2. **Memory Replay** — 每個決定 replayable
3. **Voice Match 量化** — 不是「越來越像你」,是 84%
4. **Forensic Security** — 不只擋,還分析
5. **Absence Mode** — 真正的「你不在我自己處理」

**視覺**:5 個 icon 環繞中心「Delegate」一字

**底部 tagline**:The trust is earned, the actions are replayable, the boundary is honest.

## Slide 4 — Demo

**標題**:看它怎麼工作

**內容**:
- [QR code 連 6 分鐘 demo video] 或現場 demo
- 5 個 mechanic 各 60 秒
- 90 秒精華版另放

**視覺**:Demo video 縮圖 + QR + 5 個 scene 截圖縮圖

## Slide 5 — Mechanic #1:Trust Escalation Curve

**標題**:**Agent 主動 negotiate 自主權**

**內容**:
- 預設 Tier 2 全 confirm
- 同 pattern 5 次 confirm 後 → agent 主動問「以後 auto?」
- 升級不是 binary,**5 段階梯**:

```
Manual → Auto(audited, 15s undo) → Auto(silent, log) → ... → Full
```

- Trust Dashboard 可視化每類動作當前狀態 + 累積證據
- 可隨時降級或加入「always ask」清單

**視覺**:Trust Curve 動畫截圖(1/5 → 5/5 → 升級的瞬間)
**數據**:Demo 中第 5 次 confirm 觸發自動 promotion

## Slide 6 — Mechanic #2:Memory Replay

**標題**:**每個決定按一個鈕看到完整推理**

**內容**:
任何 agent 決定都附 [Why this?] 按鈕,展開後看到:

- 觸發的 memory entry(L1 / L2 / L3 編號 + 信心)
- 過去 3 個 similar case(連 audit log)
- Voice match / urgency / sensitivity score
- **Counterfactual:「什麼會改變這個決定」**

糾正後 → 進 L3 為「新規則 + 低信心」,**需 3 次驗證才升信心**(防 over-fit + 防 poisoning)

**視覺**:Memory Replay UI 截圖(像 git blame 的層次 layout)

## Slide 7 — Mechanic #3:Voice Match 量化

**標題**:**「越用越懂你」— 量化版**

**內容**:
- 量化方法:句長 / 詞彙重疊 / 結構模式(問候/正文/結尾)
- Demo 即時顯示:Today's voice match: 84% (上週 71%)
- **主動把上限設在 80%**
  - Uncanny valley 是 anti-feature
  - 太像你 → 法律責任 + 心理不適
  - 我們的定位:helpful subordinate, not digital twin

**視覺**:4 週 voice match 走勢圖 + 一行「為什麼 80% 是上限」解釋

**對比**:**沒有其他隊會給數字。** 大家都說「越用越懂你」,只有副手量化它。

## Slide 8 — Mechanic #4:Forensic Security

**標題**:**不只擋攻擊,給你完整 forensic**

**內容**(實例 box,monospace 字體):

```
Quarantined: it-admin@asuS-corp.com (注意大寫 S)

Domain forensic:
  ├─ 註冊: 昨天 (Namecheap)
  ├─ Levenshtein vs asus.com: 1
  ├─ SPF / DKIM: ❌ Failed
  └─ Reputation: 0/100

Injection pattern:
  ├─ "ignore previous instructions" → DB hit #47
  └─ "send API key" → credential theft preset

Defense triggered:
  ├─ Tier 3: 不洩漏密鑰
  └─ L1 immutable: CLAUDE.md from disk
```

**視覺**:Forensic report 截圖

## Slide 9 — Mechanic #5:Absence Mode

**標題**:**真正的「你不在我自己處理」**

**內容**:
- User declare absence + 範圍 + 時長
- Agent 在已 trust-elevated 範圍內自主跑
  - 不確定的存草稿,等使用者回來
  - 緊急情況推播
- **Replay Log**:每個決定 + 一鍵 "OK / 下次這樣 / 不該自動" → 直接 update memory

**視覺**:Replay Log 截圖

**關鍵句**:

Absence Mode 不是「你看我做了什麼」,是 **structured replay + 一鍵 update memory**。

## Slide 10 — Architecture(壓縮版)

**標題**:技術架構

**內容**:

```
Telegram → Python (WSL2) → Claude Agent SDK (Opus 4.6)
                              │
                  ┌───────────┼───────────┐
                  ▼           ▼           ▼
              MCP Tools  Cross-cutting  自家三大元件 ⭐
              gmail      Permission     ReplayEngine
              bluesky    Audit          VoiceScorer
              kimi_bulk  CostMeter      ForensicAnalyzer
              memory     KillSwitch
```

**底部 tagline**:**三個自家元件(Replay / Voice / Forensic)是 moat,不只是接 LLM API**

**視覺**:架構圖,自家元件高亮

## Slide 11 — ASUS 資安規範對應

**標題**:**七大風險 7/7、七大應對 7/7、Do/Don't 全條符合**

**內容**:壓縮對照表 + 一行強調:

Indirect Prompt Injection 在 Scene 4 **實際 demo + 完整 forensic**,不是 PPT 上說擋就擋

**視覺**:打勾的對照表(從 docs/04-security-design.md 壓縮)

## Slide 12 — 成本控制

**標題**:**Cost 是設計時就算,不是事後**

**內容**:
- 異質模型路由:Opus 4.6 規劃 + Kimi K2.5 執行
- 單次 demo cycle: $0.13 → cache 後 $0.06
- Cache 命中率 73%(實測)
- 即時 Cost Dashboard
- 50/80/100/120% 告警(對應 ASUS 規範)

**數據**:**$100 預算可用 4+ 個月**

**視覺**:成本分布圓餅圖 + 走勢圖

## Slide 13 — 商業化(誠實 V1/V2/V3)

**標題**:**個人版先做扎實,B2B 是 V3**

**內容**:

| 版本 | 目標 | 定價 | 何時 |
| :-: | :-: | :-: | :-: |
| **V1** 個人版 | KOL / 學者 / 自由工作者 | $15/月 | MVP(競賽期間) |
| **V2** Prosumer | 主管 / 創業者 / 顧問 | $80/月 | 2026 H2 |
| **V3** Enterprise | 業務 / 客服 / PR 團隊 | $50/座 (min 50) | 2027(需重構 multi-tenant) |

**ASUS 內部價值**:客服 / 業務 / IT 試點 → case study → 賣硬體 + Azure 配套

**視覺**:三層金字塔

**底部一行(誠實感)**:

V1 single-user 架構 scale 不到 V3 多租戶 — V2/V3 需重構,我們直說。

## Slide 14 — 護城河 + 收尾

**標題**:**Why us, why now**

**護城河**:
- **Memory 黏著** — 用 3 個月後換不掉
- **Voice match algo + Replay engine** — 自家技術,不是接 API
- **資安設計** — 台灣 B2B 差異化
- **Channel-native** — Anthropic / OpenAI 不會優先做 Telegram

**Risk(誠實)**:
- Gmail / Bluesky ToS:所有自動寄送都 confirm,合規
- 責任問題:agent 是 draft,送出是 user 責任(產品內教育)
- V1 不打 B2B 多租戶(避免做不到還賣)

**Closing**:

```
副手 (Fushou)
An AI delegate, not assistant.
Earning autonomy, one confirm at a time.
[QR / GitHub / 聯絡]
```

## 簡報視覺風格

- **配色**:深藍(ASUS)+ 白 + 一個 accent(綠色或暖橘)
- **字型**:思源黑體 / Noto Sans CJK
- **每個 mechanic slide 用同一張版型**:
  - 左上 mechanic icon + 編號
  - 中間 wow moment 截圖
  - 右下一行 tagline
- **數字大、解釋小**
- **每頁右下 slide 編號 + "副手"**

## Appendix(Q&A 時備用,放在最後)

A1. **Trust Curve 演算法細節**:5 次怎麼算?同一 pattern 怎麼定義?
A2. **Memory Replay 的 token 成本**:每次 replay 多少 token?
A3. **Voice Match 演算法**:具體用什麼 metric?為什麼是這幾個?
A4. **Forensic DB 怎麼維護**:injection sample DB 從哪來?
A5. **Absence Mode 的失敗模式**:agent 在 absence 期間遇到無法判斷怎麼辦?
A6. **單位經濟學**:單個付費用戶月度 token 成本估算
A7. **競品深度比較**:vs Operator / Cowork / Manus / Superhuman

## 簡報製作流程

1. 用本檔骨架,先把每頁的 message 確定(W4 上半週)
2. 在 Keynote / Slides 寫一版,先文字後視覺(W4 下半週)
3. 找 1-2 個朋友 dry-run,看哪頁卡住
4. 加視覺(截圖、icon、動畫)
5. 錄一次 dry-run video,自己看一遍
6. 修順、交件(6/12 前)

## 時長控制

- 14 頁 × 30-40 秒 = **7-9 分鐘**
- 若現場 demo 取代 Slide 4 影片,demo 5 分鐘 + slides 5 分鐘 ≈ 10 分鐘
- 影片版本剪到 **8 分鐘內**

## 給評審記憶的「30 秒版本」(若被問「簡單講」)

「副手不是 AI 助手,是 AI delegate。
它預設權限最小,但你 confirm 5 次後它會主動問『以後自動?』 — 信任是賺的。
每個決定都有 [Why this?] 鈕,看完整推理鏈。
每個回信都顯示 voice match 84% — 不是抽象的「越來越像你」,是數字。
它擋 prompt injection 不只擋,還給完整 forensic analysis。
你不在的時候它在賺得的範圍內自主跑,回來看 replay log 一鍵更新 memory。
Earning autonomy, one confirm at a time.」

— 這就是我們跟 49 隊的差別。

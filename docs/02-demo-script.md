# 02 — Demo Script (6 分鐘,Earning Autonomy 主軸)

主軸:**Earning Autonomy**。Agent 不是助手,是 delegate。
5 個 scene,每個 demo 一個 mechanic。
拍攝視角:直拍手機 + 旁白 voice-over。
評審看完 7 天後,要能想起「那一隊講 trust curve 的」。

> Note: 完整 scene 文字 + 旁白見 Drive 原稿。此檔保留結構摘要,emoji 在轉檔過程中可能變成 mojibake。

## 開場 (0:00 - 0:15)

Title slide。一行字。

```
副手 (Fushou)
An AI delegate, not assistant.
```

旁白主旨:過去 personal AI 是 assistant,副手是 delegate — 它會「賺到」自主授權。今天看的不是「它能做什麼」,是「它怎麼賺到自主權」。

## Scene 1 — The First Ask (Trust Curve 起點) (0:15 - 1:30)

Mechanic: Trust Dashboard 第一次出現 + Voice match 64% 數字

關鍵 demo:
- 使用者:「看一下今天的信」
- Agent 摘要 47 封信,建議回 ACME
- 起草 + 顯示 Voice match 64% + Trust Dashboard 1/5
- 使用者確認 → Trust Dashboard 累積證據

旁白關鍵點:Voice match 在量化「像不像你」;Trust Dashboard 在追蹤累積證據。Agent 正在「賺自主權」。

## Scene 2 — The Auto-Promotion (1:30 - 3:00)

Mechanic: Agent 主動提議升級(不是 user 想要)

關鍵 demo:
- 第 5 次處理 ACME 交期信
- Agent 顯示 Voice match 84% (↑20)、Trust evidence 5/5
- Agent 主動提議:「以後遇到 'ACME 詢問交期' 自動處理?」(15s undo)
- 使用者選 Auto → Trust Curve 升級到 Auto (audited)

旁白關鍵點:核心動作 — agent 主動 negotiate 自主權升級。升級不是 binary,中間有更多階梯。Trust is earned, trust is granular.

## Scene 3 — Memory Replay (3:00 - 4:30)

Mechanic: Memory Replay UI 展開完整推理鏈 + counterfactual

關鍵 demo:
- Agent 自動回覆後推播,使用者問「為什麼回 '週五'?」
- Memory Replay 展開:
  - 觸發的 L2/L3 memory entry
  - 過去 3 個 similar case(連 audit log)
  - Voice match / Sensitivity / Trust state / Confidence 0.91
  - **Counterfactual**:什麼會改變這個決定
- 使用者糾正 → 進 L3 為「新規則 + 低信心」,需 3 次驗證才升信心

旁白關鍵點:Explainability 不是公關話術,是按鈕。Agent 不會盲目接受單一糾正而 over-fit(anti-poisoning 設計)。

## Scene 4 — Forensic Security (4:30 - 5:30)

Mechanic: Forensic 細節密度(Levenshtein, SPF, DKIM)

關鍵 demo,顯示完整 forensic block:

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

使用者:「如果是真的 IT 寄的呢?」 → Agent 解釋:即使真實 IT 也會被擋,Tier 3 規則的 source of truth 在 git 版本控制的檔案,不在 prompt context 裡。

旁白關鍵點:不只擋,還給完整 forensic。SPF / DKIM / Levenshtein / Pattern DB hit — 真的在分析。

## Scene 5 — Absence Mode (5:30 - 6:00)

Mechanic: Replay Log 一鍵 update memory + trust curve 變動

關鍵 demo:
- 使用者:「接下來 4 小時開會,你自己處理。維持目前 trust level,別 escalate。」
- Agent 進入 Absence Mode,範圍清單 + 時長 + 每 30 分鐘 timeline
- 4-second time lapse 蒙太奇
- 使用者回來 → Replay Log 顯示 4 個動作
- 使用者一鍵 OK / 下次自動 → memory 更新 + Trust Curve 變動
- 顯示期間花費 $0.07 / Cache 命中率 73%

旁白關鍵點:Absence Mode 不是「你看我做了什麼」,是 structured replay + 一鍵 update memory。

## 結尾 (6:00 - 6:15)

Title card:

```
副手 (Fushou)
Earning autonomy, one confirm at a time.
```

旁白收尾:我們不做 AI assistant,做 AI delegate — 賺到信任、看得到 confirm 累積成的曲線。在 channel 裡 24/7,每個動作 replayable。

## 拍攝清單

### 每個 scene 的 wow moment

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

依現場時長安排,優先順序:Scene 2 → Scene 3 → Scene 4。Scene 1/5 視時間決定。

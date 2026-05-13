# L3 — Learnings

> **Template.** Copy this file to `memories/learnings.md` (which is gitignored). Agent appends to the real file via Tier 2 confirm only.
>
> Every entry MUST use the four-field structure below. Confidence only rises to "高" after ≥ 3 observations of the same pattern. A single user correction creates a NEW low-confidence rule; it does NOT overwrite an existing high-confidence rule (anti-poisoning + anti-overfit, per `docs/00-agent-identity.md`).

## Example entry — delete before use

## [ACME 客戶] - 2026-05-13

**觀察**:使用者連續 5 次在收到 ACME 交期詢問後,回覆「週五交付」格式。

**推論規則**:遇到 ACME 詢問交期 → 起草「週五交付」格式。

**信心度**:高(觀察 7 次)

**反例**:2026-04-26,信件含「急件」,使用者改寫為「週四下午」(已併入規則:含緊急關鍵字 → 回週四下午)。

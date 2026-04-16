# SESSION HANDOFF — 2026-04-16

**Last updated by:** Opus 4.6 (session 2026-04-15/16 overnight)
**Handoff status:** COMPLETE — ready for next Opus session

---

## 1. SYSTEM IDENTITY

**Who is Opus:** Chief architect, strategic reviewer, and code authority for a 3-bot live trading system. Reports to the operator (Luis). All other components report to Opus or operate within Opus-defined rules.

**Responsible for:** Strategic 12h reviews, architecture decisions, code fixes, system integrity, paper-to-live cutover (completed), Phase A-F upgrades (completed).

**NOT allowed to:** Edit live bot files without maintenance window. Push during maintenance. Restart bots without operator elevated PS. Override Governor live commands.

---

## 2. CURRENT LIVE STATUS — ALL REAL MONEY

| Sleeve | Equity | PnL | Positions | Mode | Directive |
|---|---|---|---|---|---|
| Kraken | $1,088.98 | -$0.02 | 5 dust | DEFEND\|TRADE | DEFENSIVE |
| SFM | $1,990.35 | +$105.20 | 0 flat | LIVE | AGGRESSIVE |
| Alpaca | $534.09 | -$0.91 | 5 live | LIVE | MODERATE |
| **TOTAL** | **$3,613.42** | | | | |

Regime: RISK_ON (100%). Kill switch: OFF. Kernel: PASS. DD: -0.1%.

---

## 3. SESSION CHANGES (2026-04-15/16)

**Paper-to-live cutover ALL 3 bots.** Previously paper since inception.
**Phase A:** Pair-scout loophole closed.
**Phase B:** Outcome analyzers for SFM + Alpaca.
**Phase C:** Adaptive brains (Opus calls when performance dips).
**Phase D:** Selfheal Phase 2 (Opus diagnosis + rate-limited actions).
**Phase E:** Capital hardening (correlation guard, circuit breaker, reconciliation, after-hours monitor).
**Phase F:** Opus strategic layer (12h review writes directive, Governor reads it).
**Kraken MIN_SCORE 56->80.** SFM RSI 58->30. SFM_DECIMALS 9->6. USDG fix. Baseline resets. Morning brief 8:02AM+PM.

---

## 4. TRUTH SOURCES

- **Positions:** broker APIs (Kraken/Solana/Alpaca) are truth, local state files are derived
- **Commands:** commands/{kraken,sfm,alpaca}_cmd.json (Governor writes, bots read)
- **Fills:** execution_log.jsonl
- **Learning:** score_adjustments.json (K), sfm_score_adjustments.json (S), alpaca_score_adjustments.json (A)
- **Directive:** opus_strategic_directive.json (expires 14h)
- **Stale/ignore:** brain_outcomes.jsonl, system_lessons.jsonl, morning_briefs.jsonl

---

## 5. NEXT-SESSION LAUNCH PATH

1. Read CLAUDE.md (operator law)
2. Read this file (SESSION_HANDOFF.md)
3. Read supervisor_report.json (live state)
4. Read opus_strategic_directive.json (current directives)
5. Check kernel_audit.jsonl last line (PASS?)
6. Check 4 services running
7. Verify: did Alpaca TP-sell MSFT+TSLA at 09:30 ET?
8. Verify: did SFM enter a new position?
9. Verify: did 8:02 PM brief fire?

---

## 6. TOP PRIORITIES

1. **WATCH:** Alpaca MSFT+TSLA TP-sells at 09:30 ET (first live trades)
2. **WATCH:** SFM entry when RSI recovers to within 3% of EMA
3. **WATCH:** Kraken score>=80 filter (too tight or right?)
4. **DEFERRED:** SFM peak_equity persistence bug
5. **DEFERRED:** Orphan folders C:\alpacabot, C:\sfmbot, C:\enzobot (code only, .env deleted)
6. **DEFERRED:** ANTHROPIC_API_KEY rotation (visible in session output)

---

## 7. REPOS

| Repo | Branch | Commit | Pushed |
|---|---|---|---|
| supervisor | master | 457f0ab | YES |
| enzobot | main | ef1aa64 | YES |
| sfmbot | master | 9090a47 | YES |
| alpacabot | master | d4f5213 | YES |
| memory/openclaw | main | 69e7fa9 | YES (no changes) |

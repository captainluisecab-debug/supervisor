# SPEC: kraken_path_classifier.py

**Status:** APPROVED v2.0 — BUILD AUTHORIZED 2026-04-28 Tue 20:00 ET
**Sensitivity:** 9/10 (changes Kraken primary entry gate when graduated)
**Author:** Opus
**Approval:** operator "go" 2026-04-28

**v2 changes from v1:**
- D2 rewritten — chop is a valid classification
- D4 rewritten — insufficient data → REVISE, not KILL
- F rewritten — first live deployment is BTC-only
- 4 open questions answered (see operator answers below)
- Build/shadow/decision dates fixed

---

## Purpose

Replace static `MIN_SCORE_TO_TRADE` threshold as Kraken's primary entry gate with a path-state classifier reading RSI history, candle structure, multi-timeframe context, ATR regime, volume confirmation, and breakout/trap dynamics. Output: one of 8 path states + confidence (0.0–1.0) + reasons. Score becomes one input; path state becomes the gate.

---

## Operator Answers (replaces v1 open questions)

1. **Universe scope during shadow:** BTC-only live, all 13 observed.
2. **Feature persistence:** acceptable, compress weekly.
3. **Confidence threshold tunability:** wire as `policy.json` param within hard_bounds.
4. **Sentinel interaction:** classifier still runs/logs during pause; gates only within currently allowed pairs.

---

## A. Inputs

Per-pair, per cycle:

1. OHLCV 5-minute, last 144 bars (12h) — **NEW fetch** (engine currently fetches 15m + 1h + daily only)
2. OHLCV 15-minute, last 96 bars (24h) — **expand existing** (currently 50 bars)
3. OHLCV 1-hour, last 168 bars (7d) — **use existing** (`cfg.lookback`, ~200 bars)
4. (1-minute deferred to v2 — `tf_align_score` uses {15m, 5m} relative to 1h base; range −2..+2)
5. Current bid/ask spread — used for log enrichment, not state classification
6. 24h volume — used for log enrichment

**Source:** existing `data_kraken.fetch_ohlc(pair, timeframe_min, lookback)`. Disk cache fallback already in place.
**Storage:** in-memory per cycle; classifier itself stateless.
**Universe:** 13 Kraken pairs.

---

## B. The 8 Path States

Priority order if multiple match: `exhaustion > failed_breakout > breakout > continuation > compression > chop`. Default: `chop` with confidence ≈ 0.3.

### B1. `bullish_continuation` (all required)
- 1h: HH+HL count last 5 swings ≥ 4
- 1h close > 1h EMA(20) > 1h EMA(50)
- RSI(14) on 1h: 45–65, currently rising or holding 50 (curl ≥ 0)
- 5m: pullback to 5m EMA(20) within last 8 bars OR price within 0.3% of 5m EMA(20)
- Volume on advances > volume on declines, last 12 5m bars

### B2. `bullish_exhaustion` (any 2 of 4)
- RSI bearish divergence on 1h (price HH last 3 swings + RSI LH)
- Three-push pattern on 1h (3 consecutive HHs, each push smaller in price OR RSI)
- RSI(14) on 1h > 75 AND RSI curl down (lower than 3 bars ago)
- Volume dry-up: last 6 1h advance bars avg vol < 60% of prior 6-bar advance avg

### B3. `bearish_continuation` (all required)
- 1h: LL+LH count last 5 swings ≥ 4
- 1h close < 1h EMA(20) < 1h EMA(50)
- RSI(14) on 1h: 35–55, currently falling or rejecting 50 from below
- Volume on declines > volume on advances, last 12 5m bars

### B4. `bearish_exhaustion` (any 2 of 4)
- RSI bullish divergence on 1h (price LL + RSI HL)
- Capitulation candle on 1h: body > 2.5 × ATR(14), close in lower 30%, volume > 2 × 20-bar avg
- RSI(14) on 1h < 25 AND RSI curl up
- Hammer/pin bar at structure on 1h: lower wick > 2 × body, close in upper 50%, prior 3 bars all red

### B5. `compression` (all required)
- ATR(14) on 1h < 0.7 × ATR(14) 24h ago
- Range(last 12 1h bars) < 1.5 × ATR(14)
- RSI(14) on 1h pinned in 40–60 (current value in band)
- NR4 OR NR7 on 5m within last 4 bars OR 3+ inside bars on 5m within last 6 bars

### B6. `breakout_long` (all required)
- Prior state was `compression` (last cycle)
- 5m close > previous 24h high (last 288 5m bars, excluding current)
- Breakout bar volume > 1.8 × 20-bar avg (5m)
- 5m trend direction: up
- 1h trend direction: not bearish

### B7. `breakout_short` (mirror of B6)

### B8. `failed_breakout`
- Within last 6 5m bars price exceeded prior 24h high (or low)
- Within 3 bars after exceedance, price closed back inside the prior range

### B9. `chop` (default fallback)
None of the above match cleanly. Confidence calibrated by chop-feature presence:
- RSI(14) on 1h crosses 50 ≥ 4 times in last 24 bars
- 1h: HH+HL or LL+LH count < 3 in 5 swings
- ATR not contracting

---

## C. Feature List

26 features computed per cycle (full implementation in `kraken_path_classifier.py`):

- **C1 RSI:** rsi_14_now, rsi_14_curl, rsi_50_cross_count_24, rsi_divergence_bull/bear, rsi_failure_swing
- **C2 Candle:** swing counts (HH/HL/LL/LH last 5 pivots), nr4_5m, nr7_5m, inside_bar_count_5m_6, engulfing_bull/bear_1h, pin_bar_1h, three_push_up_1h
- **C3 MTF:** tf_align_score, trend_dir_1h, trend_dir_15m, trend_dir_5m
- **C4 ATR:** atr_14_1h, atr_ratio_24h, atr_expanding, atr_contracting
- **C5 Volume:** vol_advance_decline_5m_12, vol_breakout_ratio_5m, vol_dry_up_advance_1h_6
- **C6 Breakout:** prior_24h_high/low (from 5m × 288 bars), breakout_long_now, breakout_short_now, breakout_reclaimed
- **C7 Pullback/structural:** pullback_5m_ema20, near_5m_ema20_now, capitulation_1h, hammer_1h, ema20_1h, ema50_1h, range_12bar_vs_atr_1h

Pivot detection: 5-bar fractal (current bar surrounded by 2 lower/higher each side).

---

## D. Decision Rules

| state | confidence | entry rule | size mult | stop type | exit rule | cooldown |
|---|---|---|---|---|---|---|
| `bullish_continuation` | ≥ 0.7 | ALLOW on pullback to 5m EMA(20) within 0.3% | 1.0 × policy | structure: prior 5m swing low − 0.5 ATR | trail at structure; loosen score-drop exit by 5 | n/a |
| `bullish_continuation` | 0.5–0.7 | ALLOW with 0.7× size | 0.7 | structure | standard exit | n/a |
| `breakout_long` | ≥ 0.7 | ALLOW on retest of break level (within 0.5%) | 1.0 | tight: break level − 0.3 ATR | tighten if no follow-through within 6 bars | n/a |
| `breakout_long` | 0.5–0.7 | ALLOW with 0.5× size, retest required | 0.5 | tight | tighten | n/a |
| `compression` | any | BLOCK; prep limit at break ± 0.5 ATR | 0 | n/a | n/a | none |
| `chop` | any | BLOCK | 0 | n/a | n/a | 1h pair cooldown |
| `bullish_exhaustion` | ≥ 0.6 | BLOCK long | 0 | n/a | tighten existing longs | 4h pair cooldown |
| `bearish_continuation` | any | BLOCK long | 0 | n/a | tighten existing longs aggressively | 2h pair cooldown |
| `bearish_exhaustion` | ≥ 0.7 | ALLOW counter-trend long at 0.5× | 0.5 | tight: capitulation low − 0.3 ATR | quick scalp, exit on first strength | n/a |
| `failed_breakout` | ≥ 0.6 | counter-trade reduced size | 0.4 | very tight | very tight | 4h pair cooldown |

**Real-time during hold (re-classify each cycle):**
- `bullish_continuation` → `bullish_exhaustion`: tighten stop to last 5m swing low; tighten score-drop exit by 5
- Any → `bearish_continuation`: exit at next favorable wick OR at 1.5 × ATR adverse
- Any → `chop`: exit on first strength back to entry + 0.3 ATR; pair cooldown 1h
- `breakout_long` → `failed_breakout` (reclaim within 3 bars): exit immediately at next bid

---

## E. Shadow-Mode Plan

### E1. Implementation
- `kraken_path_classifier.py` runs every cycle for all 13 pairs (per Q1 answer)
- Output → `enzobot/logs/path_classifier_log.jsonl`: `{ts, ts_iso, pair, state, confidence, reasons[], features{}}`
- **DOES NOT gate live entries.** Live gate remains `MIN_SCORE_TO_TRADE`.
- **DOES NOT change live exits.**
- Engine reads classifier output; logs side-by-side with score-based decision.

### E2. Comparison logging
Every live entry attempt and exit logs to `enzobot/logs/path_classifier_comparison.jsonl`:
- score-based decision (live behavior)
- classifier-based decision (would-have-done)
- actual outcome at trade close (PnL, exit reason, hold time)

### E3. Sentinel interaction (per Q4 answer)
Classifier runs and logs even when sentinel pause is active. When determining "would-have-blocked" comparison, classifier respects current `allowed_pairs` (universe minus `blocked_pairs`).

### E4. Feature compression (per Q2 answer)
Every Sunday 23:59 ET: prior week's `path_classifier_log.jsonl` rolled to `path_classifier_log_YYYY-WW.jsonl.gz`. Comparison log left uncompressed.

### E5. Duration
- **Start:** 2026-05-01 Fri 00:00 ET
- **End:** 2026-05-15 Thu 20:00 ET — HARD DEADLINE, 14 calendar days
- No extension. Outcome at deadline: GRADUATE / REVISE / KILL.

---

## F. Validation Criteria — Graduate Shadow → Live

ALL must pass on 2026-05-15.

### F1. Stability
Flicker rate < 15% per pair per 4h window, averaged over 14 days. (Flicker = state change reversed within 2 cycles.)

### F2. Chop fidelity (REVISED — chop is valid)
Both sub-criteria must pass:
- **Justified-chop rate ≥ 85%:** when classifier outputs `chop`, at least one chop-defining feature must be present in that cycle (RSI 50-cross count ≥ 3 in last 24 1h bars, OR swing count < 3 in 5 swings, OR ATR neither expanding nor contracting).
- **False-chop rate ≤ 10%:** when market clearly shows clean structure (1h HH+HL ≥ 4 OR LL+LH ≥ 4 in 5 swings), classifier outputs `chop` on ≤ 10% of those cycles.

Replaces v1 "≥ 80% non-chop" — chop is allowed when the market is genuinely choppy.

### F3. Decision differentiation
Classifier decision differs from score decision on ≥ 10% of cycles.

### F4. Predictive validity (REVISED — insufficient data → REVISE)
**Sample sufficiency check:** ≥ 10 disagreement entries by 2026-05-15.

- **Sample ≥ 10:** evaluate quality:
  - Trades classifier would have ALLOWED at conf ≥ threshold: actual WR ≥ shadow baseline
  - Trades classifier would have BLOCKED that score allowed: actual outcome was negative (proves blocking adds value)
  - Both pass → D4 PASS; either fails → KILL
- **Sample < 10:** D4 = `INSUFFICIENT_DATA` → forces **REVISE**, not KILL.

### F5. Per-pair sanity
No pair stuck in one state > 24h continuously.

### F6. Operator green-light
Review `path_classifier_shadow_final.md` at 8 PM brief 2026-05-15 → "graduate" / "revise" / "kill".

---

## G. Rollback Plan

### G1. Pre-graduation (during shadow)
Trivial: shadow does nothing live.

### G2. Post-graduation kill switch
Single config flag: `policy.json["PATH_CLASSIFIER_LIVE"]: true|false`.
- `false` → revert to MIN_SCORE_TO_TRADE primary gate (current behavior)
- `true` → classifier is primary gate
Operator can flip via single edit. Loaded each cycle.

### G3. Auto-rollback triggers (live)
Auto-flip `PATH_CLASSIFIER_LIVE=false` if ANY:
- 7-day attribution: classifier-gated entries underperformed score-only baseline by > 2pp WR
- 2 HURT verdicts (per `upgrade_exit_conditions` standing rule)
- Classifier-blocked entries (where score would allow) produced > 8pp better outcomes
- Classifier raises errors on > 5% of cycles in any 4h window

Auto-rollback writes via `pause_writer` (source=`opus_classifier_rollback`, trigger=`PATH_CLASSIFIER_FAILED_LIVE`), flips policy flag, HARD escalation to brief.

### G4. Soft rollback (per-state)
Per-state disable flag. Allows partial rollback without full revert.

---

## H. Decision Point — 2026-05-15 Thu 20:00 ET

Three outcomes:

1. **GRADUATE → LIVE (BTC-only first per F-revision):** all D criteria pass + operator green-light. Flip live 2026-05-16 Fri 00:00 ET. Universe scope remains operator authority — classifier respects active sentinel pause; gates only `allowed_pairs`. 7-day live attribution → full acceptance or auto-rollback.

2. **REVISE:** ANY of:
   - F1 / F2 / F3 / F5 fails but root cause identified and fixable
   - F4 = INSUFFICIENT_DATA (any other criteria status)
   - Mixed pass/fail across non-F4 criteria
   
   ONE 7-day re-shadow window. Re-decision 2026-05-23 Fri 20:00 ET.
   Limit: 2 REVISE cycles maximum. After 2 → operator decides KEEP/KILL.

3. **KILL:** F4 evaluated with sample ≥ 10 and quality demonstrably failed. Delete classifier, archive logs, return to score-only. **30-day cooldown before next attempt.**

KILL never fires on data scarcity. Only on demonstrated quality failure with adequate sample.

---

## I. Bigger Picture — Template for All Sleeves

This build creates the **template**. After Kraken classifier graduates (or kills with lessons logged):
- `alpacabot/alpaca_path_classifier.py` — same 8-state shape, market-specific thresholds for stocks (slower RSI calibration, regular-hours-only, gap behavior, halt detection)
- `sfmbot/sfm_path_classifier.py` — meme-token specific (different RSI dynamics, illiquidity gaps, social-driven moves, liquidity traps)

Same spec → build → shadow-with-deadline → live-or-kill discipline. Per-sleeve trader brain.

---

## Files

**Build phase (this commitment):**
- NEW: `enzobot/kraken_path_classifier.py` — pure-function classifier
- NEW: `enzobot/logs/path_classifier_log.jsonl` (auto-created)
- NEW: `enzobot/logs/path_classifier_comparison.jsonl` (auto-created)
- EDIT: `enzobot/engine.py` — call classifier each cycle, log alongside score (shadow only — no gate change)
- EDIT: `enzobot/policy.json` — add `PATH_CLASSIFIER_LIVE: false`, `PATH_CLASSIFIER_CONFIDENCE_THRESHOLD: 0.7`, `hard_bounds.PATH_CLASSIFIER_CONFIDENCE_THRESHOLD: [0.5, 0.9]`
- NEW: `supervisor/path_classifier_daily_summary.py` — runs each 8 PM brief
- NEW: `supervisor/path_classifier_log_compactor.py` — Sunday 23:59 ET compress
- NEW: `supervisor/path_classifier_shadow_final.py` — final report on 2026-05-15

**Build window:** 2026-04-28 Tue 20:00 ET → 2026-04-30 Thu 20:00 ET.

---

## Validation Protocol (per CLAUDE.md §5)

After each file written:
1. Read back to confirm
2. If bot logic touched: tail `logs/service.log` to confirm process still running
3. Run smoke test on classifier with cached candles
4. Run anomaly check after engine.py edit

Build complete only when all of:
- Smoke test passes (classifier runs without exception on real cached candles)
- Engine integration logs classifier output without affecting live behavior
- 24h shakedown shows no new anomalies
- Operator confirms shadow start at 2026-05-01 brief

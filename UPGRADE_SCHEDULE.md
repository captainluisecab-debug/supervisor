# Upgrade Schedule

_Last update: 2026-04-25T01:49:03.381526+00:00_

Source of truth: `autonomy_schedule.json`. Updated by Opus on ship/revert, surfaced in 08:00 AM / 08:00 PM operator packets.

## ⏳ Built (awaiting restart)

### KRAKEN_FIX_MODE_TARGETS · Fix 1: mode_targets overwrites Opus recs (priority 1)

- **Gate:** Operator approved 2026-04-25 — build now
- **Target window:** immediate
- **Est build time:** 30m
- **Expected protection:** ~$20-60/week
- **Expected PnL lift:** ~$10-30/week
- **Exit condition:** Verified by observing MIN_SCORE=88 persists in supervisor_override.json 3+ cycles after Opus review writes it
- **Files:** enzobot/supervisor_brain.py
- **Mechanism:** mode_targets block MOVED BEFORE Opus apply_recommendations. Opus recs now override policy defaults instead of being overridden by them.

### KRAKEN_FIX_OPUS_PERSISTENCE · Fix 2: Opus-applied params persist across cycles (priority 2)

- **Gate:** Same as Fix 1
- **Target window:** immediate
- **Est build time:** 45m
- **Expected protection:** ~$30-80/week
- **Expected PnL lift:** ~$15-40/week
- **Exit condition:** Verified by SCORE_DROP_EXIT=18 visible in supervisor_override.json 5+ cycles after first Opus write
- **Files:** enzobot/supervisor_brain.py, enzobot/brain_opus_applied.json (new)
- **Mechanism:** New brain_opus_applied.json persists Opus-set params. Loaded each cycle, reapplied before Opus review; updated after Opus review. Opus recs survive non-review cycles instead of being wiped by rule-engine refresh.

### KRAKEN_FIX_FEE_COVERAGE · Fix 3: fee-coverage entry gate (0.78% floor) (priority 3)

- **Gate:** Same as Fix 1
- **Target window:** immediate
- **Est build time:** 30m
- **Expected protection:** ~$60-150/week
- **Expected PnL lift:** ~$30-80/week
- **Exit condition:** 7-day cumulative attribution: cohort of entries rejected by gate should have avg-loss worse than cohort of entries that passed
- **Files:** enzobot/engine.py, enzobot/policy.json
- **Mechanism:** fee_cov_min_expected_move cfg (default 0.0078 = 1.5x Kraken round-trip fee). Applied in BUY execution loop + deploy_target generator. Rejects entries whose expected_move can't cover fees. FEE_COV_MIN_EXPECTED_MOVE [0.005, 0.020] in policy.json hard_bounds — brain/sentinel tunable.

### ALPACA_MARKET_SENSE · alpaca_market_sense.py (priority 8)

- **Gate:** ALPACA_SENTINEL_TRIGGERS shipped
- **Target window:** 2026-04-26 20:00 ET
- **Est build time:** 2h
- **Expected protection:** ~$5-10/week
- **Expected PnL lift:** ~$5-10/week
- **Exit condition:** false-positive rate > 50% reconsider
- **Files:** alpacabot/alpaca_market_sense.py (new), alpacabot/alpaca_engine.py
- **Depends on:** ALPACA_SENTINEL_TRIGGERS
- **Mechanism:** Market-hours gate, lunch chop block, earnings avoidance, SPY drift. Subsumes ALPACA_LUNCH_GATE.

### AUTONOMY_GUARD_CLOCK_AWARE · Make autonomy_guard market-hours-aware (priority 9)

- **Gate:** ALPACA_SENTINEL_TRIGGERS shipped
- **Target window:** 2026-04-27 08:00 ET
- **Est build time:** 1h
- **Exit condition:** n/a
- **Files:** supervisor/autonomy_guard.py
- **Depends on:** ALPACA_SENTINEL_TRIGGERS
- **Mechanism:** B6-style triggers skip market-closed hours for Alpaca (9:30-16:00 Mon-Fri). Kraken/Solana wall clock.


## 🟢 Live (measuring outcomes)

### B12 · Loss-streak universe pause (priority 1)

- **Gate:** 8 AM 2026-04-24 brief: clean overnight autonomy stack + operator green-light
- **Target window:** 2026-04-24 08:00 ET
- **Est build time:** 1h
- **Expected protection:** ~$30-60/week
- **Expected PnL lift:** ~$15-25/week
- **Exit condition:** 7-day cumulative attribution HELPED==0 and HURT>=2 → revert trigger; L1 freeze on 2 HURT verdicts same param
- **Files:** supervisor/opus_sentinel.py
- **Mechanism:** 5 consec universe losses → sentinel_override: TARGET_DEPLOY_PCT=0.25 + MIN_SCORE_TO_TRADE=88 for 2h TTL; pair_status COOLDOWN on last losing pair 4h TTL

### ALPACA_EXIT_LEDGER · Alpaca exit counterfactuals ledger (priority 2)

- **Gate:** Next window; operator green-light
- **Target window:** 2026-04-24 20:00 ET
- **Est build time:** 1h
- **Exit condition:** n/a - foundation
- **Files:** alpacabot/alpaca_engine.py
- **Mechanism:** Write {ts,pair,side,entry_px,exit_px,qty,pnl_usd,exit_reason,hold_sec,regime_at_entry,regime_at_exit,score_at_entry} to alpaca_exit_counterfactuals.jsonl on every exit.

### ALPACA_STATE_SCHEMA_UNIFY · Unify alpaca_state.json field names (priority 3)

- **Gate:** Same window
- **Target window:** 2026-04-24 20:00 ET
- **Est build time:** 30m
- **Exit condition:** n/a
- **Files:** alpacabot/alpaca_state.py
- **Mechanism:** Add canonical equity_usd, realized_pnl_usd, unrealized_pnl_usd, dd_pct, peak_equity_usd fields. Keep aliases.

### ALPACA_PAIR_STATUS · Alpaca pair_status.json read path (priority 4)

- **Gate:** A1+A2 shipped
- **Target window:** 2026-04-25 08:00 ET
- **Est build time:** 1h
- **Exit condition:** n/a
- **Files:** alpacabot/alpaca_engine.py
- **Depends on:** ALPACA_EXIT_LEDGER, ALPACA_STATE_SCHEMA_UNIFY
- **Mechanism:** Mirror enzobot _apply_pair_status. TTL-bounded reversion.

### ALPACA_SENTINEL_OVERRIDE_READ · Alpaca sentinel_override.json read path (priority 5)

- **Gate:** ALPACA_PAIR_STATUS shipped
- **Target window:** 2026-04-25 08:00 ET
- **Est build time:** 1h
- **Exit condition:** n/a
- **Files:** alpacabot/alpaca_engine.py
- **Depends on:** ALPACA_PAIR_STATUS
- **Mechanism:** Mirror enzobot _apply_sentinel_override. Layered on alpaca_brain_overrides.

### ALPACA_PARAM_BOUNDS_EXPAND · Expand ALPACA PARAM_BOUNDS (priority 6)

- **Gate:** ALPACA_SENTINEL_OVERRIDE_READ shipped
- **Target window:** 2026-04-25 20:00 ET
- **Est build time:** 30m
- **Exit condition:** n/a
- **Files:** alpacabot/alpaca_brain.py
- **Depends on:** ALPACA_SENTINEL_OVERRIDE_READ
- **Mechanism:** Add MIN_SCORE_TO_TRADE, ROTATE_MIN_PNL_PCT, TIME_STOP_SEC, MIN_HOLD_SEC, TARGET_DEPLOY_PCT.

### ALPACA_SENTINEL_TRIGGERS · Alpaca sentinel triggers (B2/B4/B6/B12 adapted) (priority 7)

- **Gate:** All foundation pieces shipped
- **Target window:** 2026-04-26 08:00 ET
- **Est build time:** 2h
- **Expected protection:** ~$5-15/week
- **Expected PnL lift:** ~$5-10/week
- **Exit condition:** 7d attribution gate, L1 freeze on 2 HURT
- **Files:** supervisor/opus_sentinel.py
- **Depends on:** ALPACA_EXIT_LEDGER, ALPACA_SENTINEL_OVERRIDE_READ, ALPACA_PAIR_STATUS, ALPACA_PARAM_BOUNDS_EXPAND
- **Mechanism:** Adapted B2/B4/B6/B12 functions for Alpaca. Sentinel watches 2 sleeves.


## ⏸ Pending approval

### COSMETIC_META_KEY · Skip _meta key in pair_status reader (cosmetic) (priority 11)

- **Gate:** Trivial 2-line fix during next maintenance window. Operator ack at 8 AM brief.
- **Target window:** 2026-04-24 08:00 ET
- **Est build time:** 5m
- **Exit condition:** n/a — cosmetic only
- **Files:** enzobot/engine.py
- **Mechanism:** In _apply_pair_status: if pair.startswith('_'): continue. Skips _meta log noise.

### REVIEW_ISSUE_PARSER · Fix opus_review.py open-issue counter + parser (priority 12)

- **Gate:** Trivial parser fix. Non-blocking. Operator ack at 8 AM.
- **Target window:** 2026-04-24 08:00 ET
- **Est build time:** 15m
- **Exit condition:** n/a — reporting only
- **Files:** supervisor/opus_review.py
- **Mechanism:** Filter issues.jsonl by open state (not closed) + parse early-format records cleanly. Eliminates '[?] ?' rows.

### BTC_DOM_GATE · BTC dominance gate for Kraken alts (priority 20)

- **Gate:** B12 validated clean for 24h + operator green-light at 8 AM or 8 PM brief
- **Target window:** 2026-04-24 20:00 ET or later
- **Est build time:** 2h
- **Expected protection:** ~$50-100/week
- **Expected PnL lift:** ~$20-40/week
- **Exit condition:** 7-day cumulative attribution HELPED==0 → revert; false-positive rate >50% (gate blocks entries that would have won) → reconsider threshold
- **Files:** supervisor/opus_sentinel.py, supervisor/supervisor_regime.py
- **Depends on:** B12
- **Mechanism:** If BTC 7d trend < 3% OR BTC 24h range < 1.5%, sentinel raises Kraken alt MIN_SCORE_TO_TRADE to 85 (6h TTL, refresh while condition persists). BTC/USD pair exempt.

### POST_FLIP_COOLDOWN · Post-regime-flip observation cooldown (priority 21)

- **Gate:** B12 + BTC_DOM_GATE both validated clean + operator green-light
- **Target window:** 2026-04-25 08:00 ET or later
- **Est build time:** 1.5h
- **Expected protection:** ~$10-20/week
- **Expected PnL lift:** ~$5-15/week
- **Exit condition:** 7-day cumulative attribution <0 → revert; cooldown blocks >2 successful entries per week → tighten condition
- **Files:** supervisor/supervisor_governor.py
- **Depends on:** B12, BTC_DOM_GATE
- **Mechanism:** On regime change, governor forces SCOUT mode with entry_allowed=false for 1h regardless of flip direction. Kernel HALT overrides (can't block flatten).

### SOLANA_RECAP_DECISION · Operator decision: Solana sleeve recap + new pair (priority 30)

- **Gate:** Operator call at brief
- **Target window:** operator-decided
- **Est build time:** 0m
- **Exit condition:** operator call
- **Files:** —
- **Mechanism:** Gate for entire Phase B. SFM dormant at $6.23. Options: (a) recap+liquid pair, (b) recap to new token, (c) keep dormant.

### SOLANA_EXIT_LEDGER · Solana exit counterfactuals ledger (priority 31)

- **Gate:** SOLANA_RECAP_DECISION resolved
- **Target window:** after recap
- **Est build time:** 1h
- **Exit condition:** n/a
- **Files:** sfmbot/sfm_engine.py
- **Depends on:** SOLANA_RECAP_DECISION
- **Mechanism:** Mirror alpaca/enzobot ledger.

### SOLANA_STATE_SCHEMA_UNIFY · Unify sfm/solana state schema (priority 32)

- **Gate:** SOLANA_RECAP_DECISION resolved
- **Target window:** after recap
- **Est build time:** 30m
- **Exit condition:** n/a
- **Files:** sfmbot/sfm_state.py
- **Depends on:** SOLANA_RECAP_DECISION
- **Mechanism:** Canonical fields.

### SOLANA_PAIR_STATUS · Solana pair_status.json read path (priority 33)

- **Gate:** SOLANA_EXIT_LEDGER+SCHEMA shipped
- **Target window:** after recap
- **Est build time:** 1h
- **Exit condition:** n/a
- **Files:** sfmbot/sfm_engine.py
- **Depends on:** SOLANA_EXIT_LEDGER, SOLANA_STATE_SCHEMA_UNIFY
- **Mechanism:** Mirror enzobot.

### SOLANA_SENTINEL_OVERRIDE_READ · Solana sentinel_override.json read path (priority 34)

- **Gate:** SOLANA_PAIR_STATUS shipped
- **Target window:** after recap
- **Est build time:** 1h
- **Exit condition:** n/a
- **Files:** sfmbot/sfm_engine.py
- **Depends on:** SOLANA_PAIR_STATUS
- **Mechanism:** Mirror enzobot.

### SOLANA_PARAM_BOUNDS_EXPAND · Expand SOLANA PARAM_BOUNDS (priority 35)

- **Gate:** SOLANA_SENTINEL_OVERRIDE_READ shipped
- **Target window:** after recap
- **Est build time:** 30m
- **Exit condition:** n/a
- **Files:** sfmbot/sfm_brain.py
- **Depends on:** SOLANA_SENTINEL_OVERRIDE_READ
- **Mechanism:** MIN_SCORE_TO_TRADE, ROTATE, TIME_STOP, etc. Volatile crypto magnitudes.

### SOLANA_SENTINEL_TRIGGERS · Solana sentinel triggers (priority 36)

- **Gate:** All Solana foundation shipped
- **Target window:** after recap
- **Est build time:** 2h
- **Expected protection:** ~$5-15/week
- **Expected PnL lift:** ~$0-5/week
- **Exit condition:** 7d attribution
- **Files:** supervisor/opus_sentinel.py
- **Depends on:** SOLANA_EXIT_LEDGER, SOLANA_SENTINEL_OVERRIDE_READ, SOLANA_PAIR_STATUS, SOLANA_PARAM_BOUNDS_EXPAND
- **Mechanism:** Sentinel watches 3rd sleeve.

### SOLANA_MARKET_SENSE · solana_market_sense.py (slippage + pool + gas) (priority 37)

- **Gate:** SOLANA_SENTINEL_TRIGGERS shipped
- **Target window:** after recap
- **Est build time:** 3h
- **Expected protection:** ~$10-30/week
- **Expected PnL lift:** ~$0-10/week
- **Exit condition:** slippage gate FP rate > 30% reconsider
- **Files:** sfmbot/solana_market_sense.py (new), sfmbot/sfm_engine.py
- **Depends on:** SOLANA_SENTINEL_TRIGGERS
- **Mechanism:** Slippage gate 3%, pool liquidity floor $50k, SOL gas monitor, rug-pull signal, Jupiter/Raydium route selection.

### SOLANA_RPC_HEALTH · Solana RPC health + failover (priority 38)

- **Gate:** SOLANA_MARKET_SENSE shipped
- **Target window:** after recap
- **Est build time:** 2h
- **Expected protection:** ~$0-10/week
- **Exit condition:** n/a
- **Files:** sfmbot/solana_client.py
- **Depends on:** SOLANA_MARKET_SENSE
- **Mechanism:** p95 latency monitor, retry secondary RPC, skip cycle if degraded.


## 🗂 Deferred

### SHADOW_BASELINE · Shadow baseline counterfactual (priority 40)

- **Gate:** 2 weeks of tuning_outcomes.jsonl data accumulated
- **Target window:** 2026-05-07 or later
- **Est build time:** 6h
- **Exit condition:** n/a — self-audit mechanism
- **Files:** supervisor/autonomy_guard.py, supervisor/shadow_brain.py (new)
- **Depends on:** B12, BTC_DOM_GATE
- **Mechanism:** Run shadow param set (operator baseline) against same market ticks. Weekly compare live-vs-shadow PnL. If shadow beats live trailing-7d → auto-revert to baseline + operator flag.

### CALIBRATION_TRACKER · Calibration tracker (metacognition) (priority 41)

- **Gate:** 30 days of verdict data. Start collecting now; build later.
- **Target window:** 2026-05-23 or later
- **Est build time:** 3h
- **Exit condition:** n/a
- **Files:** supervisor/autonomy_guard.py
- **Depends on:** B12
- **Mechanism:** Compare expected_impact_usd (pre-write) vs realized 6h delta. If 30d calibration <55% correct direction → halve adjustment magnitudes autonomously.

### SLEEVE_FRAMEWORK_REFACTOR · Phase C: sleeve_framework.py abstract base (priority 50)

- **Gate:** Phase A+B shipped + >1 week clean
- **Target window:** 2026-05-15 or later
- **Est build time:** 12h
- **Exit condition:** n/a
- **Files:** supervisor/sleeve_framework.py (new), enzobot/engine.py, alpacabot/alpaca_engine.py, sfmbot/sfm_engine.py, supervisor/opus_sentinel.py
- **Depends on:** ALPACA_MARKET_SENSE, SOLANA_MARKET_SENSE
- **Mechanism:** Abstract base class. Each sleeve implements interface. Sentinel calls framework. Pure refactor.

### WEEKEND_KRAKEN_GATE · Weekend Kraken posture gate (priority 101)

- **Gate:** Weekend PnL data shows worse edge than weekdays
- **Target window:** on evidence
- **Est build time:** 2h
- **Exit condition:** defer until evidence
- **Files:** supervisor/supervisor_governor.py
- **Mechanism:** Force SCOUT Fri 17:00 ET → Sun 18:00 ET unless BTC 24h range > 1.5%.

### UNIVERSE_PRUNING · Pair-level universe pruning (autonomous DISABLED_SOFT) (priority 102)

- **Gate:** 4+ weeks of per-pair PnL attribution data
- **Target window:** 2026-05-23 or later
- **Est build time:** 4h
- **Exit condition:** operator approval required — affects universe
- **Files:** supervisor/opus_sentinel.py
- **Depends on:** B12, BTC_DOM_GATE
- **Mechanism:** Pair < 35% win rate over last 20 trades → auto-DISABLED_SOFT 7d. Operator veto at brief.


## ❌ Reverted

### ALPACA_LUNCH_GATE · Alpaca lunch-hour entry block (priority 100)

- **Gate:** Alpaca shows mid-day loss evidence (currently 5/5 clean — no signal)
- **Target window:** on evidence
- **Est build time:** 30m
- **Exit condition:** defer until needed
- **Files:** alpacabot/alpaca_engine.py
- **Mechanism:** Block new alpaca entries 11:30-13:30 ET.


---

**Next up:** `COSMETIC_META_KEY` — Skip _meta key in pair_status reader (cosmetic)
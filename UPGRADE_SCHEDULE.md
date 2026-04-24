# Upgrade Schedule

_Last update: 2026-04-23T21:40:00Z_

Source of truth: `autonomy_schedule.json`. Updated by Opus on ship/revert, surfaced in 08:00 AM / 08:00 PM operator packets.

## ⏸ Pending approval

### B12 · Loss-streak universe pause (priority 1)

- **Gate:** 8 AM 2026-04-24 brief: clean overnight autonomy stack + operator green-light
- **Target window:** 2026-04-24 08:00 ET
- **Est build time:** 1h
- **Expected protection:** ~$30-60/week
- **Expected PnL lift:** ~$15-25/week
- **Exit condition:** 7-day cumulative attribution HELPED==0 and HURT>=2 → revert trigger; L1 freeze on 2 HURT verdicts same param
- **Files:** supervisor/opus_sentinel.py
- **Mechanism:** 5 consec universe losses → sentinel_override: TARGET_DEPLOY_PCT=0.25 + MIN_SCORE_TO_TRADE=88 for 2h TTL; pair_status COOLDOWN on last losing pair 4h TTL

### BTC_DOM_GATE · BTC dominance gate for Kraken alts (priority 2)

- **Gate:** B12 validated clean for 24h + operator green-light at 8 AM or 8 PM brief
- **Target window:** 2026-04-24 20:00 ET or later
- **Est build time:** 2h
- **Expected protection:** ~$50-100/week
- **Expected PnL lift:** ~$20-40/week
- **Exit condition:** 7-day cumulative attribution HELPED==0 → revert; false-positive rate >50% (gate blocks entries that would have won) → reconsider threshold
- **Files:** supervisor/opus_sentinel.py, supervisor/supervisor_regime.py
- **Depends on:** B12
- **Mechanism:** If BTC 7d trend < 3% OR BTC 24h range < 1.5%, sentinel raises Kraken alt MIN_SCORE_TO_TRADE to 85 (6h TTL, refresh while condition persists). BTC/USD pair exempt.

### POST_FLIP_COOLDOWN · Post-regime-flip observation cooldown (priority 3)

- **Gate:** B12 + BTC_DOM_GATE both validated clean + operator green-light
- **Target window:** 2026-04-25 08:00 ET or later
- **Est build time:** 1.5h
- **Expected protection:** ~$10-20/week
- **Expected PnL lift:** ~$5-15/week
- **Exit condition:** 7-day cumulative attribution <0 → revert; cooldown blocks >2 successful entries per week → tighten condition
- **Files:** supervisor/supervisor_governor.py
- **Depends on:** B12, BTC_DOM_GATE
- **Mechanism:** On regime change, governor forces SCOUT mode with entry_allowed=false for 1h regardless of flip direction. Kernel HALT overrides (can't block flatten).

### COSMETIC_META_KEY · Skip _meta key in pair_status reader (cosmetic) (priority 10)

- **Gate:** Trivial 2-line fix during next maintenance window. Operator ack at 8 AM brief.
- **Target window:** 2026-04-24 08:00 ET
- **Est build time:** 5m
- **Exit condition:** n/a — cosmetic only
- **Files:** enzobot/engine.py
- **Mechanism:** In _apply_pair_status: if pair.startswith('_'): continue. Skips _meta log noise.

### REVIEW_ISSUE_PARSER · Fix opus_review.py open-issue counter + parser (priority 11)

- **Gate:** Trivial parser fix. Non-blocking. Operator ack at 8 AM.
- **Target window:** 2026-04-24 08:00 ET
- **Est build time:** 15m
- **Exit condition:** n/a — reporting only
- **Files:** supervisor/opus_review.py
- **Mechanism:** Filter issues.jsonl by open state (not closed) + parse early-format records cleanly. Eliminates '[?] ?' rows.


## 🗂 Deferred

### SHADOW_BASELINE · Shadow baseline counterfactual (priority 20)

- **Gate:** 2 weeks of tuning_outcomes.jsonl data accumulated
- **Target window:** 2026-05-07 or later
- **Est build time:** 6h
- **Exit condition:** n/a — self-audit mechanism
- **Files:** supervisor/autonomy_guard.py, supervisor/shadow_brain.py (new)
- **Depends on:** B12, BTC_DOM_GATE
- **Mechanism:** Run shadow param set (operator baseline) against same market ticks. Weekly compare live-vs-shadow PnL. If shadow beats live trailing-7d → auto-revert to baseline + operator flag.

### CALIBRATION_TRACKER · Calibration tracker (metacognition) (priority 21)

- **Gate:** 30 days of verdict data. Start collecting now; build later.
- **Target window:** 2026-05-23 or later
- **Est build time:** 3h
- **Exit condition:** n/a
- **Files:** supervisor/autonomy_guard.py
- **Depends on:** B12
- **Mechanism:** Compare expected_impact_usd (pre-write) vs realized 6h delta. If 30d calibration <55% correct direction → halve adjustment magnitudes autonomously.

### ALPACA_LUNCH_GATE · Alpaca lunch-hour entry block (priority 30)

- **Gate:** Alpaca shows mid-day loss evidence (currently 5/5 clean — no signal)
- **Target window:** on evidence
- **Est build time:** 30m
- **Exit condition:** defer until needed
- **Files:** alpacabot/alpaca_engine.py
- **Mechanism:** Block new alpaca entries 11:30-13:30 ET.

### WEEKEND_KRAKEN_GATE · Weekend Kraken posture gate (priority 31)

- **Gate:** Weekend PnL data shows worse edge than weekdays
- **Target window:** on evidence
- **Est build time:** 2h
- **Exit condition:** defer until evidence
- **Files:** supervisor/supervisor_governor.py
- **Mechanism:** Force SCOUT Fri 17:00 ET → Sun 18:00 ET unless BTC 24h range > 1.5%.

### UNIVERSE_PRUNING · Pair-level universe pruning (autonomous DISABLED_SOFT) (priority 32)

- **Gate:** 4+ weeks of per-pair PnL attribution data
- **Target window:** 2026-05-23 or later
- **Est build time:** 4h
- **Exit condition:** operator approval required — affects universe
- **Files:** supervisor/opus_sentinel.py
- **Depends on:** B12, BTC_DOM_GATE
- **Mechanism:** Pair < 35% win rate over last 20 trades → auto-DISABLED_SOFT 7d. Operator veto at brief.


---

**Next up:** `B12` — Loss-streak universe pause
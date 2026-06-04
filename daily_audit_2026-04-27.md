# Daily Audit - 2026-04-27 Mon 11:40 ET (15:40 UTC)

Window: 24h since 2026-04-26 Sun 11:40 ET (15:40 UTC)

## Headline

- Cash: $3508.49 | Lifetime realized: $-338.39
- 24h exits: 0 (0W / 0L)  net=$+0.00
- Active pause: True (operator_directive/SOFT_RELEASE_BTC_ONLY)
- TTL: 2026-04-28T12:56:17.736503+00:00

## NEW since prior audit

Soft release executed at 2026-04-27 Mon 08:56 ET (12:56 UTC). Operator-approved.
- BTC/USD only allowed (12 other pairs blocked)
- MIN_SCORE_TO_TRADE = 90 / MAX_OPEN_POSITIONS = 1 / TARGET_DEPLOY_PCT = 0.20
- 24h TTL until 2026-04-28 Tue 08:56 ET
- All defensive params unchanged (fee_cov 0.78%, brain layer intact)

## Exits last 24h

_No exits — bot has been completely flat for the audit window._

## Brain activity

- Reviews: 12
- Changes applied: 12
- opus_applied: {"SCORE_DROP_EXIT": 25.0, "MIN_SCORE_TO_TRADE": 95.0, "EXIT_SCORE_FLOOR": 55.0, "STALL_MIN_PNL_PCT": -0.003, "ROTATE_MIN_PNL_PCT": 0.012}

## Active overrides

Sentinel (operator soft-release):
- source: operator_directive
- trigger: SOFT_RELEASE_BTC_ONLY
- ttl: 2026-04-28T12:56:17.736503+00:00
- changes: {"MIN_SCORE_TO_TRADE": 90.0, "MAX_OPEN_POSITIONS": 1, "TARGET_DEPLOY_PCT": 0.2}
- blocked: 12 pairs (BTC/USD only allowed)

Brain (sticky):
{
  "COOLDOWN_SEC": 3600,
  "MIN_HOLD_SEC": 5400,
  "RSI_MIN_SELL": 40.0,
  "ATR_FLOOR_PCT": 0.003,
  "CORR_CAP_MAX_PER_GROUP": 1,
  "MAX_OPEN_POSITIONS": 5,
  "MIN_SCORE_TO_TRADE": 95.0,
  "EXIT_SCORE_FLOOR": 55.0,
  "TREND_WEIGHT": 1.8,
  "MOMENTUM_WEIGHT": 1.3,
  "VOL_WEIGHT": 1.4,
  "VOLATILITY_ENTRY_GATE": 0.0025,
  "ENTRY_CONFIRM_BARS": 1,
  "WEAK_EXIT_THRESHOLD": 10.0,
  "DOWNTREND_SCORE_CAP": 75.0,
  "SCORE_DROP_EXIT": 25.0,
  "STALL_MIN_PNL_PCT": -0.003,
  "ROTATE_MIN_PNL_PCT": 0.012
}

## Health

All 3 fixes PASS. pause_writer enforced operator-directive sanctity (verified at write).

## Forward

- Soft-release TTL expires: 2026-04-28 Tue 08:56 ET (12:56 UTC)
- Next 2h watch: ~10:07 ET
- First BTC round-trip will be judged within 5 min of close
- 12h check ~21:00 ET decides whether to add ETH

## Operator items

- BTC-only soft release is in flight. First trade outcome decisive.
- Stack armed for productive trading; capital floor preserved if test fails.

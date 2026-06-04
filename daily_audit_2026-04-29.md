# Morning Brief - 2026-04-29 Wed 07:55 ET (11:55 UTC)

Window: 24h since 2026-04-28 Tue 07:55 ET (11:55 UTC)

## Headline

- Cash: $3508.49 | Lifetime realized: $-338.39
- 24h exits: 0 (0W / 0L) net=$+0.00
- Active pause: True (operator_directive/TRADER_LIVE_BTC_NEAR)
- Open positions: 0

## Autonomous actions in window

- 2026-04-28T14:37:09 status=progression triggers=[]

## Exits

_No exits in window._

## Brain activity

- Reviews: 17 | Changes applied: 6
- Current opus_applied: {"SCORE_DROP_EXIT": 999.0, "MIN_SCORE_TO_TRADE": 88.0, "EXIT_SCORE_FLOOR": 55.0, "STALL_MIN_PNL_PCT": -0.003, "ROTATE_MIN_PNL_PCT": 0.005, "MAX_OPEN_POSITIONS": 2, "WEAK_EXIT_THRESHOLD": 14.0}

## Active overrides

Sentinel: source=operator_directive trigger=TRADER_LIVE_BTC_NEAR
Sentinel TTL: 2026-05-06T01:50:00+00:00
Sentinel changes: {"MIN_SCORE_TO_TRADE": 88.0, "MAX_OPEN_POSITIONS": 2, "TARGET_DEPLOY_PCT": 0.4}
Brain (sticky): {"COOLDOWN_SEC": 3600, "MIN_HOLD_SEC": 5400, "RSI_MIN_SELL": 40.0, "ATR_FLOOR_PCT": 0.003, "CORR_CAP_MAX_PER_GROUP": 1, "MAX_OPEN_POSITIONS": 5, "MIN_SCORE_TO_TRADE": 80.0, "EXIT_SCORE_FLOOR": 48.0, "TREND_WEIGHT": 1.8, "MOMENTUM_WEIGHT": 1.3, "VOL_WEIGHT": 1.4, "VOLATILITY_ENTRY_GATE": 0.0025, "ENTRY_CONFIRM_BARS": 1, "WEAK_EXIT_THRESHOLD": 10.0, "DOWNTREND_SCORE_CAP": 75.0}

## Watch log entries (12)

Pause events in window: 1
Sentinel fires in window: 19

## Operator action items

- Bot has been flat. Cash preserved. Soft-release in flight, awaiting first BTC entry (or autonomous progression at 24h-no-entry mark).

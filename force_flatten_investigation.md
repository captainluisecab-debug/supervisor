# Governor Force-Flatten Investigation

Source: 60 governor_force_flatten exits joined with 30,423 governor_decisions
Method: for each exit, find the most recent governor decision in the prior 10 min
with FORCE_FLAT / FREEZE_ENTRIES / HERMES_DD_OVERRIDE / FORCE_DEFENSE action.

Net PnL of all force-flat exits: $+127.90 (4-week backfill).

---

## Trigger Action Breakdown

| Action | Count | Total PnL | Avg PnL | Avg Hold (min) |
|---|---:|---:|---:|---:|
| FORCE_FLAT | 42 | $+137.16 | $+3.27 | 85 |
| HERMES_DD_OVERRIDE | 18 | $-9.26 | $-0.51 | 12 |

## Trigger Reason Category

| Reason Category | Count | Total PnL | Avg PnL | Median Hold (min) |
|---|---:|---:|---:|---:|
| regime_flat | 42 | $+137.16 | $+3.27 | 4 |
| hermes_dd | 18 | $-9.26 | $-0.51 | 1 |

## Dominant Regime at Trigger

| dominant_regime | Count | Total PnL | Avg PnL |
|---|---:|---:|---:|
| UNKNOWN | 58 | $+128.28 | $+2.21 |
| TRENDING_DOWN | 2 | $-0.38 | $-0.19 |

## Per-Pair (force-flatten only)

| Pair | Count | Total PnL | Wins | Losses |
|---|---:|---:|---:|---:|
| XRP/USD | 2 | $+79.23 | 2 | 0 |
| LINK/USD | 2 | $+73.63 | 1 | 1 |
| DOT/USD | 4 | $-1.27 | 0 | 4 |
| NEAR/USD | 7 | $-1.66 | 0 | 7 |
| BTC/USD | 10 | $-2.54 | 2 | 8 |
| DOGE/USD | 10 | $-2.64 | 1 | 9 |
| POL/USD | 10 | $-3.42 | 0 | 10 |
| SOL/USD | 13 | $-4.43 | 2 | 11 |
| ETH/USD | 2 | $-9.00 | 0 | 2 |

## Hold-Time Distribution at Force-Flatten

| Hold | Count | Total PnL | Avg PnL |
|---|---:|---:|---:|
| <5min | 38 | $+145.08 | $+3.82 |
| 5-30min | 7 | $-2.42 | $-0.35 |
| 30-60min | 6 | $-14.43 | $-2.40 |
| 1-2h | 2 | $-0.40 | $-0.20 |
| 2-6h | 1 | $+0.08 | $+0.08 |
| >6h | 6 | $-0.01 | $-0.00 |

## What Happened to Price After Force-Flat

Definition of "saved": price dropped >0.5% below force-flat exit within window.

- 60m: saved 2/58 (3%)
- 120m: saved 4/58 (7%)

## Top 5 Most-Profitable Force-Flat Exits

| Pair | Hold (min) | PnL | PnL% | Trigger Action | Trigger Reason |
|---|---:|---:|---:|---|---|
| XRP/USD | 0 | $+79.15 | +0.00% | FORCE_FLAT | Regime=TRENDING_DOWN -> FLAT. Reduce all positions. |
| LINK/USD | 0 | $+73.91 | +0.00% | FORCE_FLAT | Regime=TRENDING_DOWN -> FLAT. Reduce all positions. |
| SOL/USD | 4 | $+1.71 | +0.27% | FORCE_FLAT | Regime=TRENDING_DOWN -> FLAT. Reduce all positions. |
| BTC/USD | 390 | $+1.70 | +0.24% | FORCE_FLAT | Regime=TRENDING_DOWN -> FLAT. Reduce all positions. |
| BTC/USD | 4 | $+0.99 | +0.14% | FORCE_FLAT | Regime=TRENDING_DOWN -> FLAT. Reduce all positions. |

## Top 5 Most-Losing Force-Flat Exits

| Pair | Hold (min) | PnL | PnL% | Trigger Action | Trigger Reason |
|---|---:|---:|---:|---|---|
| SOL/USD | 42 | $-1.10 | -0.16% | HERMES_DD_OVERRIDE | Hermes advisory: entry_allowed=false (DD=-3.6%) — tighten-only override |
| DOGE/USD | 42 | $-1.25 | -0.26% | HERMES_DD_OVERRIDE | Hermes advisory: entry_allowed=false (DD=-3.6%) — tighten-only override |
| BTC/USD | 379 | $-1.64 | -0.28% | FORCE_FLAT | Regime=TRENDING_DOWN -> FLAT. Reduce all positions. |
| SOL/USD | 59 | $-1.76 | -0.30% | HERMES_DD_OVERRIDE | Hermes advisory: entry_allowed=false (DD=0.0%) — tighten-only override |
| ETH/USD | 32 | $-8.57 | -1.29% | FORCE_FLAT | Regime=TRENDING_DOWN -> FLAT. Reduce all positions. |

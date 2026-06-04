# Backfill Audit Report — 4-Week Historical Replay

Generated: 2026-04-28 20:31:22
Window: 2026-04-01 → 2026-04-24 (24 days)
Method: 1h-only proxy classifier (5m OHLCV not available for full window — Kraken OHLC endpoint caps at 720 bars).

## Headline

- Total unique entries: 263
- Replayed (sufficient 1h data): 263
- Total realized PnL across all trades: $-26.55
- Wins: 69 | Losses: 194 | BE: 0
- Overall WR: 26.2%

## Per-Pair Breakdown

| Pair | Trades | Wins | Losses | WR | PnL ($) | Avg Score |
|---|---:|---:|---:|---:|---:|---:|
| POL/USD | 27 | 5 | 22 | 18.5% | $-43.37 | 95.6 |
| DOGE/USD | 45 | 8 | 37 | 17.8% | $-41.21 | 90.1 |
| ETH/USD | 11 | 3 | 8 | 27.3% | $-33.80 | 93.2 |
| SOL/USD | 37 | 10 | 27 | 27.0% | $-22.76 | 93.8 |
| DOT/USD | 6 | 1 | 5 | 16.7% | $+2.84 | 94.3 |
| AVAX/USD | 15 | 4 | 11 | 26.7% | $+4.11 | 95.2 |
| BTC/USD | 33 | 11 | 22 | 33.3% | $+10.03 | 94.3 |
| NEAR/USD | 18 | 4 | 14 | 22.2% | $+12.61 | 93.8 |
| LINK/USD | 37 | 14 | 23 | 37.8% | $+41.85 | 91.8 |
| XRP/USD | 34 | 9 | 25 | 26.5% | $+43.15 | 91.1 |

## Per-State (1h proxy classifier)

| State | Trades | Wins | Losses | WR | PnL ($) | Avg PnL |
|---|---:|---:|---:|---:|---:|---:|
| bullish_exhaustion_proxy | 20 | 3 | 17 | 15.0% | $-16.39 | $-0.82 |
| compression_proxy | 15 | 2 | 13 | 13.3% | $-15.05 | $-1.00 |
| bullish_continuation_proxy | 55 | 18 | 37 | 32.7% | $-12.61 | $-0.23 |
| bearish_continuation_proxy | 2 | 0 | 2 | 0.0% | $-1.86 | $-0.93 |
| chop_proxy | 171 | 46 | 125 | 26.9% | $+19.36 | $+0.11 |

## Per-Score-Bucket

| Score | Trades | Wins | Losses | WR | PnL ($) |
|---|---:|---:|---:|---:|---:|
| 80-85 | 28 | 2 | 26 | 7.1% | $-15.42 |
| 85-90 | 29 | 4 | 25 | 13.8% | $-65.05 |
| 90-95 | 48 | 6 | 42 | 12.5% | $-51.43 |
| 95-101 | 141 | 49 | 92 | 34.8% | $-38.62 |

## Per-Regime (entry-time)

| Regime | Trades | Wins | Losses | WR | PnL ($) |
|---|---:|---:|---:|---:|---:|
| UP | 240 | 63 | 177 | 26.2% | $-118.60 |
| NEUTRAL | 1 | 1 | 0 | 100.0% | $+0.81 |
| DOWN | 22 | 5 | 17 | 22.7% | $+91.24 |

## Classifier Allow vs Block (would-have)

Allowed states: bullish_continuation_proxy, bearish_exhaustion_proxy (conf>=0.5)
Blocked states: chop_proxy, bullish_exhaustion_proxy, bearish_continuation_proxy, compression_proxy

| Decision | Trades | Wins | Losses | WR | Net PnL ($) |
|---|---:|---:|---:|---:|---:|
| ALLOWED | 55 | 18 | 37 | 32.7% | $-12.61 |
| BLOCKED | 208 | 51 | 157 | 24.5% | $-13.94 |

## Exit Reason Breakdown

| Exit Reason | Count | Total PnL ($) |
|---|---:|---:|
| score_drop_exit | 82 | $-4.00 |
| governor_force_flatten | 60 | $+127.90 |
| trail_hit | 37 | $-38.34 |
| stop_hit | 23 | $-192.53 |
| scale_out_50pct | 15 | $+40.85 |
| time_stop_no_progress | 15 | $-19.95 |
| take_profit | 13 | $+58.48 |
| score_drop_warning_30pct | 10 | $-0.89 |
| trend_flip | 9 | $-15.81 |
| scale_out_profit_1.5pct | 8 | $+28.92 |
| rsi_weak | 7 | $-12.11 |
| psar_trail | 7 | $+1.76 |
| quick_profit_hitrun | 3 | $+20.96 |
| rotate_to_DOT/USD | 2 | $-9.98 |
| rotate_to_BTC/USD | 2 | $-3.44 |
| rotate_to_SOL/USD | 1 | $-3.45 |
| rotate_to_NEAR/USD | 1 | $-4.93 |

## Pair × State (top 10 by trade count)

| Pair / State | Trades | WR | PnL ($) |
|---|---:|---:|---:|
| DOGE/USD / chop_proxy | 33 | 18.2% | $-26.35 |
| LINK/USD / chop_proxy | 24 | 37.5% | $+37.44 |
| POL/USD / chop_proxy | 23 | 17.4% | $-41.14 |
| XRP/USD / chop_proxy | 19 | 36.8% | $+62.20 |
| BTC/USD / chop_proxy | 19 | 36.8% | $+20.26 |
| SOL/USD / chop_proxy | 17 | 35.3% | $-11.90 |
| AVAX/USD / chop_proxy | 12 | 25.0% | $-8.03 |
| NEAR/USD / chop_proxy | 12 | 16.7% | $+11.13 |
| XRP/USD / bullish_continuation_proxy | 11 | 18.2% | $-14.26 |
| SOL/USD / bullish_continuation_proxy | 11 | 36.4% | $+4.13 |
| DOGE/USD / bullish_continuation_proxy | 10 | 10.0% | $-13.73 |
| SOL/USD / compression_proxy | 8 | 0.0% | $-14.13 |
| ETH/USD / chop_proxy | 7 | 28.6% | $-22.72 |
| LINK/USD / bullish_exhaustion_proxy | 6 | 16.7% | $-7.43 |
| BTC/USD / compression_proxy | 6 | 33.3% | $+0.08 |

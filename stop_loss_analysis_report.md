# Stop-Loss / Hold-Logic Forensic Analysis

Source: exit_counterfactuals.jsonl (4 weeks, 295 exits with post-exit price snapshots)
Question: for each exit type, how often did price RECOVER after exit (i.e., the exit was premature)?

Method: each exit has 30/60/120-min post-exit snapshots with `vs_exit_pct = snap_price/exit_price - 1`.
Positive vs_exit_pct = price ROSE after we exited (would-have-won-if-held for a long).

---

## Per Exit Reason — Recovery Rates

A high recovery rate after `stop_hit` or `trail_hit` = stops/trails were too tight or fired on noise.
A low recovery rate after `take_profit`, `scale_out` = correct exit (price did not extend).

| exit_reason | n | total_pnl | avg_pnl | recovered@60m (any) | recovered@60m (>1%) | recovered@120m (any) | recovered@120m (>1%) |
|---|---:|---:|---:|---:|---:|---:|---:|
| stop_hit | 23 | $-192.52 | $-8.37 | 14/19 (74%) | 0/19 (0%) | 12/19 (63%) | 0/19 (0%) |
| trail_hit | 37 | $-48.23 | $-1.30 | 21/31 (68%) | 0/31 (0%) | 16/31 (52%) | 0/31 (0%) |
| score_drop_exit | 82 | $-5.29 | $-0.06 | 34/73 (47%) | 1/73 (1%) | 34/73 (47%) | 3/73 (4%) |
| score_drop_warning_30pct | 10 | $-0.88 | $-0.09 | 6/9 (67%) | 3/9 (33%) | 8/9 (89%) | 6/9 (67%) |
| time_stop_no_progress | 15 | $-19.96 | $-1.33 | 5/15 (33%) | 0/15 (0%) | 3/15 (20%) | 0/15 (0%) |
| rsi_weak | 7 | $-12.11 | $-1.73 | 6/6 (100%) | 0/6 (0%) | 2/6 (33%) | 0/6 (0%) |
| trend_flip | 9 | $-15.80 | $-1.76 | 6/9 (67%) | 0/9 (0%) | 7/9 (78%) | 0/9 (0%) |
| psar_trail | 7 | $+1.62 | $+0.23 | 2/3 (67%) | 1/3 (33%) | 1/3 (33%) | 0/3 (0%) |
| take_profit | 13 | $+67.11 | $+5.16 | 4/11 (36%) | 0/11 (0%) | 2/11 (18%) | 0/11 (0%) |
| scale_out_50pct | 15 | $+51.89 | $+3.46 | n/a | n/a | n/a | n/a |
| scale_out_profit_1.5pct | 8 | $+20.58 | $+2.57 | n/a | n/a | n/a | n/a |
| quick_profit_hitrun | 3 | $+20.95 | $+6.98 | 2/3 (67%) | 1/3 (33%) | 3/3 (100%) | 0/3 (0%) |
| governor_force_flatten | 60 | $+127.90 | $+2.13 | 37/58 (64%) | 0/58 (0%) | 39/58 (67%) | 8/58 (14%) |

## Stop-Hit Deep Dive

Total stop_hit exits: 23
Total stop_hit PnL: $-192.52
Avg stop loss: $-8.37
Avg stop loss %: -1.78%

### Where did price end up after the stop fired?

| Window | < -2% | -2% to 0 | 0 to +1% | +1% to +2% | > +2% |
|---|---:|---:|---:|---:|---:|
| 60min | 0 (0%) | 5 (26%) | 14 (74%) | 0 (0%) | 0 (0%) |
| 120min | 1 (5%) | 6 (32%) | 12 (63%) | 0 (0%) | 0 (0%) |

### Per-Pair Stop-Hit Recovery

| Pair | n_stops | total_pnl | recovered@60m (>1%) | recovered@120m (>1%) |
|---|---:|---:|---:|---:|
| XRP/USD | 6 | $-35.84 | 0/4 (0%) | 0/4 (0%) |
| LINK/USD | 5 | $-50.41 | 0/4 (0%) | 0/4 (0%) |
| POL/USD | 4 | $-31.84 | 0/4 (0%) | 0/4 (0%) |
| DOGE/USD | 3 | $-18.00 | 0/3 (0%) | 0/3 (0%) |
| BTC/USD | 2 | $-10.62 | 0/1 (0%) | 0/1 (0%) |
| SOL/USD | 2 | $-28.44 | 0/2 (0%) | 0/2 (0%) |
| ETH/USD | 1 | $-17.36 | 0/1 (0%) | 0/1 (0%) |

## Trail-Hit Analysis (37 exits, -$38)

Same question for trailing-stop exits.

- 60m recovery (>1% above trail exit): 0/31 (0%)
- 120m recovery (>1% above trail exit): 0/31 (0%)

## Governor Force-Flatten Analysis (60 exits, +$127.90)

Question: were these correct exits (price kept going against us) or also premature?

- 60m: price kept dropping >0.5% below force-flat exit: 2/58 (3%)
- 120m: same: 4/58 (7%)

## Stop-Loss Depth Distribution

How deep was each stop loss? (pnl_pct at exit for stop_hit trades)

- <-5%: 0 (0%)
- -5% to -3%: 2 (9%)
- -3% to -2%: 5 (22%)
- -2% to -1%: 12 (52%)
- > -1%: 4 (17%)

## Stop-Hit Hold Time

- p25: 48 min
- median: 89 min
- p75: 178 min
- min/max: 19/328 min

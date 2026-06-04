# Market Data Archive Layout — Cross-Agent Reference

**Build:** 2026-04-28 (operator directive: secure all Kraken data, use 100%).
**Module:** `enzobot/market_data_archive.py`
**Base path:** `C:/Projects/enzobot/data/market_archive/`

---

## Why

Kraken's public OHLC endpoint caps at 720 bars (~2.5 days for 5m, ~30 days for 1h). The 4-week backfill audit on 2026-04-28 was crippled by this — historical 5m data was unavailable for the trade window we needed to replay. Going forward, the bot now appends every cycle's fetched OHLCV to a permanent local archive so future analysis has deep history regardless of what Kraken's API exposes.

## What gets archived

Every 60-second cycle, for each pair the bot fetches:
- 1h OHLCV (200 bars / pair) → archived
- 5m OHLCV (144 bars / pair) → archived
- 15m OHLCV (50 bars / pair) → archived
- Daily OHLCV (50 bars / pair, refreshed hourly) → archived

Plus once per cycle:
- Trader decisions (per-pair entry + exit decisions, with classifier context) → archived

## Storage layout

```
C:/Projects/enzobot/data/market_archive/
    ohlcv/
        BTC_USD_5m.jsonl          ← per-pair, per-timeframe, append-only, ts-sorted
        BTC_USD_15m.jsonl
        BTC_USD_60m.jsonl         ← (cfg.timeframe_min = 60)
        BTC_USD_1440m.jsonl       ← daily
        ETH_USD_5m.jsonl
        ...                       ← all 10 pairs × 4 timeframes = 40 files
    decisions/
        trader_decisions.jsonl    ← one record per trader cycle
    snapshots/                    ← reserved for future per-cycle market snapshots
    orderbook/                    ← reserved for future order book captures
    trades/                       ← reserved for future trade tape captures
```

## OHLCV record schema

One JSONL line per closed candle:
```json
{"ts": 1777398900, "o": 75421.3, "h": 75487.6, "l": 75388.1, "c": 75450.2, "v": 0.847}
```
- `ts`: integer unix seconds (closed-bar timestamp)
- `o`/`h`/`l`/`c`: float OHLC
- `v`: float volume

**Dedup-on-write:** the archiver reads the last record's `ts` and only appends candles with `ts > last`. Repeated fetches that overlap the existing window are idempotent.

## Trader decision record schema

```json
{
  "ts": 1777400138,
  "cycle": 41,
  "entries": {
    "BTC/USD": {"action": "SKIP", "detail": {...}},
    "NEAR/USD": {"action": "BUY", "detail": {"size_mult": 0.7, "stop_atr_mult": 1.8, "reason": "trader_primary: cls=bullish_continuation@0.72 score=89.2 (boost=1.00) size=0.70x", ...}},
    ...10 pairs total
  },
  "exits": {
    "BTC/USD": {"action": "SELL", "detail": {"reason": "trader_exit_regime_shift_to_bullish_exhaustion@0.65"}}
  }
}
```

## How to USE the archive (cross-agent contract)

**Reading historical OHLCV (for any analysis):**
```python
import json
from pathlib import Path

p = Path(r'C:/Projects/enzobot/data/market_archive/ohlcv/BTC_USD_5m.jsonl')
records = []
with open(p, encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except Exception:
                pass
# records is list of dicts in chronological order
```

**Loading specific time window:**
```python
from datetime import datetime, timezone
start_ts = int(datetime(2026, 5, 1, tzinfo=timezone.utc).timestamp())
end_ts = int(datetime(2026, 5, 8, tzinfo=timezone.utc).timestamp())
window = [r for r in records if start_ts <= r['ts'] <= end_ts]
```

**For backfill analysis / classifier replay:** previously required calling Kraken with `since=` (capped at 720 bars). Now the archive provides full local history from go-live (2026-04-28 22:13) onward. After 7-14 days the local archive will exceed Kraken's public exposure on 5m data.

## Storage growth rate

Estimated:
- 5m: 12 closed bars/hour × 10 pairs × ~80 bytes = ~9.6 KB/hour = ~230 KB/day
- 15m: 4 × 10 × 80 = ~3.2 KB/hour = ~77 KB/day
- 1h: 1 × 10 × 80 = ~800 bytes/hour = ~19 KB/day
- Daily: ~80 bytes × 10 / 24h = ~33 bytes/hour = ~0.8 KB/day
- Trader decisions: ~2 KB/cycle × 60/h × 24 = ~2.9 MB/day

**Total: ~3.2 MB/day uncompressed.** A year of full archive = ~1.2 GB. Acceptable. Plan to add a weekly compactor after 30 days to gzip files older than 30 days.

## Compaction (future)

After ≥30 days of accumulation, run a compactor: gzip files older than 30 days (e.g. `BTC_USD_5m_2026-05.jsonl.gz`). Keep most-recent file uncompressed for fast tail reads. Pattern same as `path_classifier_log_compactor.py`.

## Failure mode

Archive writes are wrapped in try/except in engine.py. If the archive call fails, the cycle continues normally. The bot's trading is NOT dependent on the archive — it's purely additive.

## Cross-agent guidance

- **Other Kraken-side agents:** read from this archive for any historical analysis. Do NOT call Kraken's `OHLC` endpoint with `since=` for deep history — it's capped. Use the archive.
- **Alpaca/Solana sleeves:** same pattern recommended. Each sleeve maintains its own archive at `data/market_archive/`. When a sleeve gets its own `_market_archive.py`, mirror this layout.
- **Backfill / audit work:** prefer `data/market_archive/ohlcv/{PAIR}_{tf}m.jsonl` over Kraken REST for any historical replay. The archive is the source of truth for what the bot SAW.
- **Edge model construction (future):** `decisions/trader_decisions.jsonl` joined to `enzobot/logs/exit_counterfactuals.jsonl` (by pair + ts proximity) gives the per-state outcome data needed to update per-pair × per-state confidence weights.

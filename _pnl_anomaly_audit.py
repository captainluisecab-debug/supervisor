"""Audit exit_counterfactuals.jsonl for accounting-anomaly records.

Pattern: entry_price=0.0 and hold_sec=0 produces fake PnL = exit_price * qty
(from engine.py:1086 _paper_sell when _fpos.avg_price was already reset).
"""
import json

EXIT_PATH = r'C:\Projects\enzobot\logs\exit_counterfactuals.jsonl'

anomalies = []
real_exits = []

with open(EXIT_PATH, encoding='utf-8') as f:
    for line in f:
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get('type') != 'exit':
            continue
        ep = d.get('entry_price', 0)
        hs = d.get('hold_sec', 0)
        if (ep == 0.0 or ep is None) and (hs == 0):
            anomalies.append(d)
        else:
            real_exits.append(d)

print('Total exit records:', len(anomalies) + len(real_exits))
print('Anomalies (entry_price=0 AND hold_sec=0):', len(anomalies))
print('Real exits:', len(real_exits))
print()
print('Anomaly records:')
for a in anomalies:
    print('  ts={0} pair={1:10s} pnl_usd=${2:+.2f} reason={3}'.format(
        a.get('ts_iso', '?'), a.get('pair', '?'),
        a.get('pnl_usd', 0), a.get('exit_reason', '?')))
print()

ff_real = [e for e in real_exits if e.get('exit_reason') == 'governor_force_flatten']
ff_anom = [a for a in anomalies if a.get('exit_reason') == 'governor_force_flatten']
print('Force-flatten exits (real, excluding anomalies):', len(ff_real))
total_real = sum(e.get('pnl_usd', 0) or 0 for e in ff_real)
wins = sum(1 for e in ff_real if (e.get('pnl_usd', 0) or 0) > 0)
losses = sum(1 for e in ff_real if (e.get('pnl_usd', 0) or 0) < 0)
print('  Total PnL: ${0:+.2f}'.format(total_real))
print('  W/L: {0}/{1}'.format(wins, losses))
print('  Avg PnL: ${0:+.2f}'.format(total_real / max(1, len(ff_real))))
print()
total_anom = sum(a.get('pnl_usd', 0) or 0 for a in ff_anom)
print('Anomaly contribution to original headline: ${0:+.2f}'.format(total_anom))
print('Original (with anomalies): $+127.90')
print('Clean (excluding anomalies): ${0:+.2f}'.format(127.90 - total_anom))
print()
print('=' * 60)
print('Other affected aggregates:')
all_total = sum((e.get('pnl_usd', 0) or 0) for e in real_exits)
print('  Total real PnL across all exits: ${0:+.2f}'.format(all_total))
print('  Anomaly contribution to total backfill: ${0:+.2f}'.format(sum((a.get('pnl_usd', 0) or 0) for a in anomalies)))
print()
print('Backfill audit headline was: $-26.55 PnL across 263 unique entries')
print('  Anomalies inflated PnL by: ${0:+.2f}'.format(sum((a.get('pnl_usd', 0) or 0) for a in anomalies)))
print('  TRUE backfill PnL: ${0:+.2f}'.format(-26.55 - sum((a.get('pnl_usd', 0) or 0) for a in anomalies)))

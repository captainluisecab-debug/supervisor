"""4-week backfill audit using historical data we have.

Sources:
- exit_counterfactuals.jsonl (295 exits, 263 unique entries, 4/01-4/25)
- 1h OHLCV (30+ days available via Kraken OHLC endpoint)

Limitation: 5m OHLCV not available for the full historical window (Kraken caps
720 bars = 2.5 days of 5m). So classifier replay uses 1h-only proxy state:
bullish_continuation_proxy, bullish_exhaustion_proxy, bearish_continuation_proxy,
bearish_exhaustion_proxy, chop_proxy. Lacks: breakout/failed_breakout/compression
(which need 5m). Lacks: 5m pullback detection.

Output: C:/Projects/supervisor/backfill_audit_report.md + jsonl backfill records.
"""
import sys, os, json, time
sys.path.insert(0, r'C:\Projects\enzobot')

import requests
from collections import defaultdict, Counter

from indicators import rsi, ema, atr
from models import Candle
from data_kraken import _kraken_pair, BASE
from kraken_path_classifier import (
    _swing_pivots, _swing_count_last_n, _rsi_series, _rsi_curl,
    _rsi_50_crosses, _rsi_divergence, _rsi_failure_swing, _three_push_up,
    _atr_history, _vol_dry_up_advance_1h, _trend_direction
)

EXIT_PATH = r'C:\Projects\enzobot\logs\exit_counterfactuals.jsonl'
OUT_JSONL = r'C:\Projects\enzobot\logs\path_classifier_backfill_1h.jsonl'
OUT_REPORT = r'C:\Projects\supervisor\backfill_audit_report.md'

SESSION = requests.Session()


def fetch_ohlc_since(pair, interval, since_ts):
    url = BASE + '/OHLC'
    params = {'pair': _kraken_pair(pair), 'interval': int(interval), 'since': int(since_ts)}
    r = SESSION.get(url, params=params, timeout=(10, 30))
    r.raise_for_status()
    j = r.json()
    if j.get('error'):
        raise RuntimeError('Kraken error: ' + str(j['error']))
    keys = [k for k in j['result'].keys() if k != 'last']
    if not keys:
        return []
    rows = j['result'][keys[0]]
    return [Candle(
        ts=int(row[0]), o=float(row[1]), h=float(row[2]),
        l=float(row[3]), c=float(row[4]), v=float(row[6])
    ) for row in rows]


# 1h-only proxy classifier
def classify_1h_proxy(candles_1h, prior_state=None):
    if len(candles_1h) < 50:
        return ('insufficient', 0.0, [])
    closes = [c.c for c in candles_1h]
    highs = [c.h for c in candles_1h]
    lows = [c.l for c in candles_1h]
    rsi_series_1h = _rsi_series(closes, 14)
    pivots = _swing_pivots(highs, lows, fractal=2)
    swings = _swing_count_last_n(pivots, 5)
    bull_div, bear_div = _rsi_divergence(closes, rsi_series_1h, pivots)
    three_push = _three_push_up(rsi_series_1h, pivots)
    atr_now, atr_then = _atr_history(candles_1h, 24)
    atr_ratio = (atr_now / atr_then) if atr_then > 0 else 1.0
    rsi_now = rsi_series_1h[-1]
    rsi_curl = _rsi_curl(rsi_series_1h, 3)
    e20 = ema(closes, 20)
    e50 = ema(closes, 50)
    close = closes[-1]
    rsi_pp = _rsi_50_crosses(rsi_series_1h, 24)
    vol_dry = _vol_dry_up_advance_1h(candles_1h)

    reasons = []

    # Bullish exhaustion (any 2 of 4)
    be_score = 0
    if bear_div:
        be_score += 1
        reasons.append('rsi_bearish_divergence')
    if three_push:
        be_score += 1
        reasons.append('three_push_up_1h')
    if rsi_now > 75 and rsi_curl < 0:
        be_score += 1
        reasons.append('rsi>75_curl_down')
    if vol_dry:
        be_score += 1
        reasons.append('vol_dry_up_advance')
    if be_score >= 2:
        return ('bullish_exhaustion_proxy', min(1.0, 0.6 + 0.1 * (be_score - 2)), reasons)
    reasons = []

    # Bearish exhaustion (any 2 of 4) - simplified (no capitulation/hammer detail without sample)
    bear_score = 0
    if bull_div:
        bear_score += 1
        reasons.append('rsi_bullish_divergence')
    if rsi_now < 25 and rsi_curl > 0:
        bear_score += 1
        reasons.append('rsi<25_curl_up')
    if bear_score >= 2:
        return ('bearish_exhaustion_proxy', 0.6, reasons)
    reasons = []

    # Bullish continuation (HH+HL>=4 + close>EMA20>EMA50 + RSI 45-65 rising)
    bc_score = 0
    if (swings['HH'] + swings['HL']) >= 4:
        bc_score += 1
        reasons.append('1h_HH+HL>=4')
    if close > e20 > e50 > 0:
        bc_score += 1
        reasons.append('1h_close>EMA20>EMA50')
    if 45 <= rsi_now <= 65 and rsi_curl >= 0:
        bc_score += 1
        reasons.append('rsi_45-65_rising')
    if bc_score == 3:
        return ('bullish_continuation_proxy', 0.7, reasons)
    if bc_score == 2:
        return ('bullish_continuation_proxy', 0.5, reasons)
    reasons = []

    # Bearish continuation
    brc_score = 0
    if (swings['LL'] + swings['LH']) >= 4:
        brc_score += 1
        reasons.append('1h_LL+LH>=4')
    if e50 > 0 and close < e20 < e50:
        brc_score += 1
        reasons.append('1h_close<EMA20<EMA50')
    if 35 <= rsi_now <= 55 and rsi_curl <= 0:
        brc_score += 1
        reasons.append('rsi_35-55_falling')
    if brc_score == 3:
        return ('bearish_continuation_proxy', 0.7, reasons)
    if brc_score == 2:
        return ('bearish_continuation_proxy', 0.5, reasons)
    reasons = []

    # Compression (proxy without 5m)
    if atr_ratio < 0.7 and 40 <= rsi_now <= 60:
        return ('compression_proxy', 0.6, ['atr_contracting', 'rsi_pinned_40-60'])

    # Chop fallback
    chop_features = 0
    if rsi_pp >= 4:
        chop_features += 1
        reasons.append('rsi_50cross>=4')
    swing_clean = max(swings['HH'] + swings['HL'], swings['LL'] + swings['LH'])
    if swing_clean < 3:
        chop_features += 1
        reasons.append('no_clean_swing')
    if not (atr_ratio > 1.2 or atr_ratio < 0.7):
        chop_features += 1
        reasons.append('atr_neutral')
    return ('chop_proxy', 0.3 + 0.15 * chop_features, reasons)


# Load exits
exits = []
with open(EXIT_PATH, encoding='utf-8') as f:
    for line in f:
        try:
            d = json.loads(line)
            if d.get('type') == 'exit':
                exits.append(d)
        except Exception:
            pass

# Group by (pair, entry_ts)
unique_entries = {}
for e in exits:
    pair = e.get('pair')
    hold = int(e.get('hold_sec', 0) or 0)
    exit_ts = int(e.get('ts', 0) or 0)
    entry_ts = exit_ts - hold
    if pair is None or entry_ts <= 0:
        continue
    key = (pair, entry_ts)
    if key not in unique_entries:
        unique_entries[key] = {
            'pair': pair, 'entry_ts': entry_ts,
            'entry_score': float(e.get('entry_score', 0) or 0),
            'entry_regime': e.get('regime'),
            'pnl_usd': 0.0, 'pnl_pct': 0.0,
            'exit_reasons': [],
            'hold_sec': hold,
        }
    unique_entries[key]['pnl_usd'] += float(e.get('pnl_usd', 0) or 0)
    unique_entries[key]['pnl_pct'] = float(e.get('pnl_pct', 0) or 0)
    unique_entries[key]['exit_reasons'].append(e.get('exit_reason'))

print('Unique entries: ' + str(len(unique_entries)))
pairs = sorted(set(k[0] for k in unique_entries.keys()))

# Fetch 1h history per pair (one call gives 720 hours = 30 days)
earliest_ts = min(e['entry_ts'] for e in unique_entries.values())
buffer_1h = 168 * 3600  # 7d warmup
per_pair_1h = {}
for pair in pairs:
    print('Fetching 1h for ' + pair)
    try:
        c1h = fetch_ohlc_since(pair, 60, earliest_ts - buffer_1h)
        per_pair_1h[pair] = c1h
        print('  bars=' + str(len(c1h)))
    except Exception as fe:
        print('  FAILED: ' + str(fe))
        per_pair_1h[pair] = []
    time.sleep(0.5)

# Replay proxy classifier
results = []
prior_per_pair = {}
sorted_entries = sorted(unique_entries.values(), key=lambda x: x['entry_ts'])
for ent in sorted_entries:
    pair = ent['pair']
    entry_ts = ent['entry_ts']
    c1h = per_pair_1h.get(pair) or []
    c1h_at = [c for c in c1h if c.ts <= entry_ts]
    if len(c1h_at) < 50:
        results.append({**ent, 'classifier_state': 'insufficient', 'classifier_conf': 0.0,
                        'classifier_reasons': []})
        continue
    state, conf, reasons = classify_1h_proxy(c1h_at[-200:], prior_per_pair.get(pair))
    prior_per_pair[pair] = state
    results.append({
        'pair': pair, 'entry_ts': entry_ts,
        'entry_ts_iso': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(entry_ts)),
        'entry_score': ent['entry_score'],
        'entry_regime': ent['entry_regime'],
        'pnl_usd': round(ent['pnl_usd'], 2),
        'pnl_pct': round(ent['pnl_pct'], 4),
        'win': ent['pnl_usd'] > 0,
        'hold_sec': ent['hold_sec'],
        'exit_reasons': ent['exit_reasons'],
        'classifier_state': state,
        'classifier_conf': round(conf, 3),
        'classifier_reasons': reasons,
    })

with open(OUT_JSONL, 'w', encoding='utf-8') as f:
    for r in results:
        f.write(json.dumps(r) + '\n')

# ========================================================================
# AGGREGATE ANALYSIS
# ========================================================================

valid = [r for r in results if r['classifier_state'] != 'insufficient']
total_pnl = sum(r['pnl_usd'] for r in valid)
wins = [r for r in valid if r['win']]
losses = [r for r in valid if not r['win']]
breakeven = [r for r in valid if r['pnl_usd'] == 0]

# Per-pair
per_pair = defaultdict(lambda: {'count': 0, 'pnl': 0.0, 'wins': 0, 'losses': 0,
                                  'be': 0, 'avg_score': 0.0})
for r in valid:
    p = per_pair[r['pair']]
    p['count'] += 1
    p['pnl'] += r['pnl_usd']
    if r['pnl_usd'] > 0:
        p['wins'] += 1
    elif r['pnl_usd'] < 0:
        p['losses'] += 1
    else:
        p['be'] += 1
    p['avg_score'] += r['entry_score']
for p in per_pair.values():
    p['avg_score'] /= max(1, p['count'])

# Per-state
per_state = defaultdict(lambda: {'count': 0, 'pnl': 0.0, 'wins': 0, 'losses': 0})
for r in valid:
    s = per_state[r['classifier_state']]
    s['count'] += 1
    s['pnl'] += r['pnl_usd']
    if r['pnl_usd'] > 0:
        s['wins'] += 1
    elif r['pnl_usd'] < 0:
        s['losses'] += 1

# Per-pair x per-state
pair_state = defaultdict(lambda: {'count': 0, 'pnl': 0.0, 'wr': 0.0})
for r in valid:
    key = (r['pair'], r['classifier_state'])
    ps = pair_state[key]
    ps['count'] += 1
    ps['pnl'] += r['pnl_usd']
    if r['pnl_usd'] > 0:
        ps['wr'] += 1

# Per-score-bucket
score_buckets = [(80, 85), (85, 90), (90, 95), (95, 101)]
per_score = {f'{lo}-{hi}': {'count': 0, 'pnl': 0.0, 'wins': 0, 'losses': 0}
             for lo, hi in score_buckets}
for r in valid:
    s = r['entry_score']
    for lo, hi in score_buckets:
        if lo <= s < hi:
            per_score[f'{lo}-{hi}']['count'] += 1
            per_score[f'{lo}-{hi}']['pnl'] += r['pnl_usd']
            if r['pnl_usd'] > 0:
                per_score[f'{lo}-{hi}']['wins'] += 1
            elif r['pnl_usd'] < 0:
                per_score[f'{lo}-{hi}']['losses'] += 1
            break

# Per-regime
per_regime = defaultdict(lambda: {'count': 0, 'pnl': 0.0, 'wins': 0, 'losses': 0})
for r in valid:
    rg = r['entry_regime'] or 'UNKNOWN'
    per_regime[rg]['count'] += 1
    per_regime[rg]['pnl'] += r['pnl_usd']
    if r['pnl_usd'] > 0:
        per_regime[rg]['wins'] += 1
    elif r['pnl_usd'] < 0:
        per_regime[rg]['losses'] += 1

# Classifier-allow vs block by state (which would have been blocked)
allow_states = ('bullish_continuation_proxy', 'bearish_exhaustion_proxy')
block_states = ('chop_proxy', 'bullish_exhaustion_proxy',
                'bearish_continuation_proxy', 'compression_proxy')
allowed = [r for r in valid if r['classifier_state'] in allow_states and r['classifier_conf'] >= 0.5]
blocked = [r for r in valid if r['classifier_state'] in block_states]

allowed_pnl = sum(r['pnl_usd'] for r in allowed)
allowed_wins = sum(1 for r in allowed if r['pnl_usd'] > 0)
allowed_losses = sum(1 for r in allowed if r['pnl_usd'] < 0)
blocked_pnl = sum(r['pnl_usd'] for r in blocked)
blocked_wins = sum(1 for r in blocked if r['pnl_usd'] > 0)
blocked_losses = sum(1 for r in blocked if r['pnl_usd'] < 0)

# Exit reason analysis (by primary exit reason)
exit_reason_counts = Counter()
exit_reason_pnl = defaultdict(float)
for r in valid:
    for er in r['exit_reasons']:
        exit_reason_counts[er] += 1
        exit_reason_pnl[er] += r['pnl_usd'] / max(1, len(r['exit_reasons']))

# ========================================================================
# REPORT
# ========================================================================
lines = []
lines.append('# Backfill Audit Report — 4-Week Historical Replay')
lines.append('')
lines.append('Generated: ' + time.strftime('%Y-%m-%d %H:%M:%S', time.localtime()))
lines.append('Window: 2026-04-01 → 2026-04-24 (24 days)')
lines.append('Method: 1h-only proxy classifier (5m OHLCV not available for full window — Kraken OHLC endpoint caps at 720 bars).')
lines.append('')
lines.append('## Headline')
lines.append('')
lines.append('- Total unique entries: ' + str(len(unique_entries)))
lines.append('- Replayed (sufficient 1h data): ' + str(len(valid)))
lines.append('- Total realized PnL across all trades: $' + ('%+.2f' % total_pnl))
lines.append('- Wins: ' + str(len(wins)) + ' | Losses: ' + str(len(losses)) + ' | BE: ' + str(len(breakeven)))
overall_wr = 100 * len(wins) / max(1, len(wins) + len(losses))
lines.append('- Overall WR: ' + ('%.1f%%' % overall_wr))
lines.append('')

lines.append('## Per-Pair Breakdown')
lines.append('')
lines.append('| Pair | Trades | Wins | Losses | WR | PnL ($) | Avg Score |')
lines.append('|---|---:|---:|---:|---:|---:|---:|')
for pair in sorted(per_pair.keys(), key=lambda p: per_pair[p]['pnl']):
    p = per_pair[pair]
    wr = 100 * p['wins'] / max(1, p['wins'] + p['losses'])
    lines.append('| ' + pair + ' | ' + str(p['count']) + ' | ' + str(p['wins'])
                 + ' | ' + str(p['losses']) + ' | ' + ('%.1f%%' % wr)
                 + ' | $' + ('%+.2f' % p['pnl']) + ' | ' + ('%.1f' % p['avg_score']) + ' |')
lines.append('')

lines.append('## Per-State (1h proxy classifier)')
lines.append('')
lines.append('| State | Trades | Wins | Losses | WR | PnL ($) | Avg PnL |')
lines.append('|---|---:|---:|---:|---:|---:|---:|')
for state in sorted(per_state.keys(), key=lambda s: per_state[s]['pnl']):
    s = per_state[state]
    wr = 100 * s['wins'] / max(1, s['wins'] + s['losses'])
    avg = s['pnl'] / max(1, s['count'])
    lines.append('| ' + state + ' | ' + str(s['count']) + ' | ' + str(s['wins'])
                 + ' | ' + str(s['losses']) + ' | ' + ('%.1f%%' % wr)
                 + ' | $' + ('%+.2f' % s['pnl']) + ' | $' + ('%+.2f' % avg) + ' |')
lines.append('')

lines.append('## Per-Score-Bucket')
lines.append('')
lines.append('| Score | Trades | Wins | Losses | WR | PnL ($) |')
lines.append('|---|---:|---:|---:|---:|---:|')
for bucket, s in per_score.items():
    if s['count'] == 0:
        continue
    wr = 100 * s['wins'] / max(1, s['wins'] + s['losses'])
    lines.append('| ' + bucket + ' | ' + str(s['count']) + ' | ' + str(s['wins'])
                 + ' | ' + str(s['losses']) + ' | ' + ('%.1f%%' % wr)
                 + ' | $' + ('%+.2f' % s['pnl']) + ' |')
lines.append('')

lines.append('## Per-Regime (entry-time)')
lines.append('')
lines.append('| Regime | Trades | Wins | Losses | WR | PnL ($) |')
lines.append('|---|---:|---:|---:|---:|---:|')
for rg in sorted(per_regime.keys(), key=lambda r: per_regime[r]['pnl']):
    s = per_regime[rg]
    wr = 100 * s['wins'] / max(1, s['wins'] + s['losses'])
    lines.append('| ' + str(rg) + ' | ' + str(s['count']) + ' | ' + str(s['wins'])
                 + ' | ' + str(s['losses']) + ' | ' + ('%.1f%%' % wr)
                 + ' | $' + ('%+.2f' % s['pnl']) + ' |')
lines.append('')

lines.append('## Classifier Allow vs Block (would-have)')
lines.append('')
lines.append('Allowed states: ' + ', '.join(allow_states) + ' (conf>=0.5)')
lines.append('Blocked states: ' + ', '.join(block_states))
lines.append('')
lines.append('| Decision | Trades | Wins | Losses | WR | Net PnL ($) |')
lines.append('|---|---:|---:|---:|---:|---:|')
allow_wr = 100 * allowed_wins / max(1, allowed_wins + allowed_losses)
block_wr = 100 * blocked_wins / max(1, blocked_wins + blocked_losses)
lines.append('| ALLOWED | ' + str(len(allowed)) + ' | ' + str(allowed_wins)
             + ' | ' + str(allowed_losses) + ' | ' + ('%.1f%%' % allow_wr)
             + ' | $' + ('%+.2f' % allowed_pnl) + ' |')
lines.append('| BLOCKED | ' + str(len(blocked)) + ' | ' + str(blocked_wins)
             + ' | ' + str(blocked_losses) + ' | ' + ('%.1f%%' % block_wr)
             + ' | $' + ('%+.2f' % blocked_pnl) + ' |')
lines.append('')

lines.append('## Exit Reason Breakdown')
lines.append('')
lines.append('| Exit Reason | Count | Total PnL ($) |')
lines.append('|---|---:|---:|')
for er, cnt in exit_reason_counts.most_common():
    lines.append('| ' + str(er) + ' | ' + str(cnt) + ' | $' + ('%+.2f' % exit_reason_pnl[er]) + ' |')
lines.append('')

lines.append('## Pair × State (top 10 by trade count)')
lines.append('')
lines.append('| Pair / State | Trades | WR | PnL ($) |')
lines.append('|---|---:|---:|---:|')
sorted_ps = sorted(pair_state.items(), key=lambda x: -x[1]['count'])
for (pair, state), s in sorted_ps[:15]:
    wr = 100 * s['wr'] / max(1, s['count'])
    lines.append('| ' + pair + ' / ' + state + ' | ' + str(s['count'])
                 + ' | ' + ('%.1f%%' % wr) + ' | $' + ('%+.2f' % s['pnl']) + ' |')
lines.append('')

with open(OUT_REPORT, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))

print()
print('=' * 60)
print('Total entries: ' + str(len(unique_entries)))
print('Valid (1h-replayable): ' + str(len(valid)))
print('Total PnL: $' + ('%+.2f' % total_pnl))
print('Overall WR: ' + ('%.1f%%' % overall_wr))
print('Report: ' + OUT_REPORT)
print('Records: ' + OUT_JSONL)

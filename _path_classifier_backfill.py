"""Backfill replay: classify path state at entry of every historical trade.

Reads exit_counterfactuals.jsonl (~295 exits over ~4 weeks), fetches OHLCV
ending at each entry ts via Kraken REST API directly (matching bot's
data_kraken pattern), runs kraken_path_classifier, saves per-entry results
to path_classifier_backfill.jsonl.

Output schema: {pair, entry_ts, entry_ts_iso, entry_score, entry_regime,
pnl_usd, win, classifier_state, classifier_conf, classifier_reasons}
"""
import sys, os, json, time
sys.path.insert(0, r'C:\Projects\enzobot')

import requests
from kraken_path_classifier import classify_path
from models import Candle
from data_kraken import _kraken_pair, BASE

EXIT_PATH = r'C:\Projects\enzobot\logs\exit_counterfactuals.jsonl'
OUT_PATH = r'C:\Projects\enzobot\logs\path_classifier_backfill.jsonl'

SESSION = requests.Session()


def fetch_ohlc_since(pair, interval, since_ts):
    """Fetch up to 720 OHLC bars from Kraken public API, starting at since_ts (unix sec)."""
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


def fetch_history(pair, interval, since_ts, until_ts):
    """Paginated fetch from since_ts to until_ts (inclusive of partial last-bar)."""
    out = []
    cursor = since_ts
    iterations = 0
    while cursor < until_ts and iterations < 50:
        try:
            batch = fetch_ohlc_since(pair, interval, cursor)
        except Exception as e:
            print('  fetch error pair=' + pair + ' interval=' + str(interval) + ': ' + str(e))
            break
        if not batch:
            break
        new_data = [c for c in batch if c.ts > cursor]
        if not new_data:
            break
        out.extend(new_data)
        last_ts = new_data[-1].ts
        if last_ts <= cursor:
            break
        cursor = last_ts
        iterations += 1
        time.sleep(0.5)
    return out


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
print('Loaded ' + str(len(exits)) + ' exit records')

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
            'pair': pair,
            'entry_ts': entry_ts,
            'entry_score': float(e.get('entry_score', 0) or 0),
            'entry_regime': e.get('regime'),
            'pnl_usd': 0.0,
            'exit_count': 0,
        }
    unique_entries[key]['pnl_usd'] += float(e.get('pnl_usd', 0) or 0)
    unique_entries[key]['exit_count'] += 1

print('Unique entries: ' + str(len(unique_entries)))

pairs = sorted(set(k[0] for k in unique_entries.keys()))
print('Pairs: ' + ', '.join(pairs))

# Earliest entry ts; back off enough for warmup
earliest_ts = min(e['entry_ts'] for e in unique_entries.values())
latest_ts = max(e['entry_ts'] for e in unique_entries.values())
print('Window: ' + time.strftime('%Y-%m-%d', time.localtime(earliest_ts))
      + ' -> ' + time.strftime('%Y-%m-%d', time.localtime(latest_ts)))

buffer_5m_sec = 144 * 5 * 60
buffer_15m_sec = 96 * 15 * 60
buffer_1h_sec = 168 * 3600

# Fetch per-pair history once
per_pair_data = {}
for pair in pairs:
    print('Fetching history for ' + pair)
    try:
        c5m = fetch_history(pair, 5, earliest_ts - buffer_5m_sec, latest_ts + 60)
        c15m = fetch_history(pair, 15, earliest_ts - buffer_15m_sec, latest_ts + 60)
        c1h = fetch_history(pair, 60, earliest_ts - buffer_1h_sec, latest_ts + 60)
        per_pair_data[pair] = {'5m': c5m, '15m': c15m, '1h': c1h}
        print('  5m=' + str(len(c5m)) + ' 15m=' + str(len(c15m)) + ' 1h=' + str(len(c1h)))
    except Exception as fe:
        print('  FAILED pair=' + pair + ': ' + str(fe))
        per_pair_data[pair] = None

# Replay classifier (chronological per pair for prior_state continuity)
results = []
prior_state_per_pair = {}
sorted_entries = sorted(unique_entries.values(), key=lambda e: e['entry_ts'])

processed = 0
insufficient = 0
for ent in sorted_entries:
    pair = ent['pair']
    entry_ts = ent['entry_ts']
    pd = per_pair_data.get(pair)
    if not pd:
        continue

    c5m = [c for c in pd['5m'] if c.ts <= entry_ts]
    c15m = [c for c in pd['15m'] if c.ts <= entry_ts]
    c1h = [c for c in pd['1h'] if c.ts <= entry_ts]

    if len(c1h) < 50 or len(c5m) < 30 or len(c15m) < 20:
        results.append({
            'pair': pair,
            'entry_ts': entry_ts,
            'entry_ts_iso': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(entry_ts)),
            'entry_score': ent['entry_score'],
            'entry_regime': ent['entry_regime'],
            'pnl_usd': ent['pnl_usd'],
            'win': ent['pnl_usd'] > 0,
            'exit_count': ent['exit_count'],
            'classifier_state': 'insufficient_data',
            'classifier_conf': 0.0,
            'classifier_reasons': [],
        })
        insufficient += 1
        continue

    # Trim for performance
    c5m = c5m[-300:]
    c15m = c15m[-100:]
    c1h = c1h[-200:]

    prior = prior_state_per_pair.get(pair)
    try:
        cls = classify_path(pair, c5m, c15m, c1h, prior_state=prior)
        prior_state_per_pair[pair] = cls.state
    except Exception as cle:
        print('  classify error pair=' + pair + ' ts=' + str(entry_ts) + ': ' + str(cle))
        continue

    results.append({
        'pair': pair,
        'entry_ts': entry_ts,
        'entry_ts_iso': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(entry_ts)),
        'entry_score': ent['entry_score'],
        'entry_regime': ent['entry_regime'],
        'pnl_usd': ent['pnl_usd'],
        'win': ent['pnl_usd'] > 0,
        'exit_count': ent['exit_count'],
        'classifier_state': cls.state,
        'classifier_conf': float(cls.confidence),
        'classifier_reasons': cls.reasons,
    })
    processed += 1

with open(OUT_PATH, 'w', encoding='utf-8') as f:
    for r in results:
        f.write(json.dumps(r) + '\n')

print()
print('=' * 60)
print('Processed: ' + str(processed))
print('Insufficient data: ' + str(insufficient))
print('Total saved: ' + str(len(results)))
print('Output: ' + OUT_PATH)

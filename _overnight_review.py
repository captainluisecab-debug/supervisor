"""Overnight review: Phase 1 + Phase 2 archive growth + key signals."""
import os, sys, json
sys.path.insert(0, r'C:\Projects\enzobot')
from market_data_archive import archive_size_summary

s = archive_size_summary()
total = sum(s.values())

cats = {}
for k, v in s.items():
    cat = k.replace('\\', '/').split('/')[0]
    cats.setdefault(cat, []).append((k, v))

print('=== Archive size summary (overnight, since 22:51 ET) ===')
print('Total:', '{0:,} bytes ({1:.2f} MB)'.format(total, total / 1024.0 / 1024.0))
print('Files:', len(s))
print()
for cat in sorted(cats.keys()):
    cat_size = sum(v for _, v in cats[cat])
    print(cat + ':', '{0:,} bytes across {1} files'.format(cat_size, len(cats[cat])))

print()
print('=== Top files by size ===')
top = sorted(s.items(), key=lambda kv: -kv[1])[:15]
for k, v in top:
    print('  {0:>10,} bytes  {1}'.format(v, k))

print()

# Trader decisions overnight
print('=== Trader decisions overnight ===')
dec_path = r'C:\Projects\enzobot\data\market_archive\decisions\trader_decisions.jsonl'
if os.path.exists(dec_path):
    n = 0
    buy_count = 0
    skip_count = 0
    force_exit_count = 0
    state_dist_btc = {}
    state_dist_near = {}
    with open(dec_path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            n += 1
            for pair in ('BTC/USD', 'NEAR/USD'):
                ent = d.get('entries', {}).get(pair)
                if ent:
                    if ent.get('action') == 'BUY':
                        buy_count += 1
                    elif ent.get('action') == 'SKIP':
                        skip_count += 1
                    detail = ent.get('detail')
                    if isinstance(detail, dict):
                        # not in our archive yet, only in classifier_log
                        pass
            if d.get('exits'):
                force_exit_count += len(d['exits'])
    print('cycles archived:', n)
    print('total BTC+NEAR BUY signals:', buy_count)
    print('total BTC+NEAR SKIP signals:', skip_count)
    print('total force-exits triggered:', force_exit_count)
else:
    print('no trader_decisions.jsonl')

print()

# Orderbook + trades growth (Phase 2)
print('=== Phase 2 microstructure capture ===')
for pair in ('BTC_USD', 'NEAR_USD'):
    ob_p = r'C:\Projects\enzobot\data\market_archive\orderbook' + os.sep + pair + '.jsonl'
    tr_p = r'C:\Projects\enzobot\data\market_archive\trades' + os.sep + pair + '.jsonl'
    ob_lines = 0
    tr_lines = 0
    if os.path.exists(ob_p):
        with open(ob_p, encoding='utf-8') as f:
            ob_lines = sum(1 for _ in f)
    if os.path.exists(tr_p):
        with open(tr_p, encoding='utf-8') as f:
            tr_lines = sum(1 for _ in f)
    print(pair + ':')
    print('  orderbook snapshots:', ob_lines)
    print('  trades captured:', tr_lines)

print()
print('=== Done ===')

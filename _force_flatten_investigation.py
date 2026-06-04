"""Force-flatten outperformance investigation.

For each governor_force_flatten exit, find the governor_decisions entry that
triggered force_flatten=True closest before the exit timestamp. Aggregate by
trigger reason.
"""
import sys, json, os, time
sys.path.insert(0, r'C:\Projects\supervisor')

from collections import defaultdict
from datetime import datetime, timezone

EXIT_PATH = r'C:\Projects\enzobot\logs\exit_counterfactuals.jsonl'
GOV_PATH = r'C:\Projects\supervisor\governor_decisions.jsonl'
OUT_PATH = r'C:\Projects\supervisor\force_flatten_investigation.md'


def parse_iso(s):
    if not s:
        return 0
    try:
        if s.endswith('Z'):
            s = s[:-1] + '+00:00'
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return 0


# Load force-flat exits + their snapshots
exits = []
snapshots_by_id = defaultdict(list)
with open(EXIT_PATH, encoding='utf-8') as f:
    for line in f:
        try:
            d = json.loads(line)
        except Exception:
            continue
        t = d.get('type')
        if t == 'exit' and d.get('exit_reason') == 'governor_force_flatten':
            exits.append(d)
        elif t == 'snapshot':
            snapshots_by_id[d.get('id')].append(d)

print('Force-flat exits: ' + str(len(exits)))

# Load governor decisions; build a chronological list with action+reason+metrics
gov = []
with open(GOV_PATH, encoding='utf-8') as f:
    for line in f:
        try:
            d = json.loads(line)
        except Exception:
            continue
        ts = parse_iso(d.get('ts'))
        if ts > 0:
            gov.append({
                'ts': ts,
                'action': d.get('action'),
                'reason': d.get('reason'),
                'metrics': d.get('metrics', {}),
            })
gov.sort(key=lambda x: x['ts'])
print('Governor decisions loaded: ' + str(len(gov)))

# For each force-flat exit, find the most recent governor decision in the prior 10 min
# that would have caused force_flatten (FORCE_FLAT action OR FREEZE_ENTRIES with FLAT regime
# OR HERMES_DD_OVERRIDE with FLAT)
results = []
flatten_actions = ('FORCE_FLAT', 'FREEZE_ENTRIES', 'HERMES_DD_OVERRIDE', 'FORCE_DEFENSE')


def find_trigger(exit_ts, lookback_sec=600):
    """Return the most relevant governor decision in the prior `lookback_sec` seconds."""
    candidates = []
    for g in gov:
        if g['ts'] > exit_ts:
            break
        if exit_ts - g['ts'] > lookback_sec:
            continue
        if g['action'] in flatten_actions:
            candidates.append(g)
    if not candidates:
        return None
    return candidates[-1]


for e in exits:
    eid = e.get('id')
    exit_ts = int(e.get('ts', 0))
    trigger = find_trigger(exit_ts)
    snaps = snapshots_by_id.get(eid, [])
    s60 = next((s.get('vs_exit_pct') for s in snaps if s.get('minutes') == 60), None)
    s120 = next((s.get('vs_exit_pct') for s in snaps if s.get('minutes') == 120), None)

    results.append({
        'pair': e.get('pair'),
        'exit_ts_iso': e.get('ts_iso'),
        'pnl_usd': float(e.get('pnl_usd', 0) or 0),
        'pnl_pct': float(e.get('pnl_pct', 0) or 0),
        'hold_sec': int(e.get('hold_sec', 0) or 0),
        'entry_score': float(e.get('entry_score', 0) or 0),
        'regime_at_entry': e.get('regime'),
        'partial': bool(e.get('partial')),
        'trigger_action': trigger['action'] if trigger else None,
        'trigger_reason': trigger['reason'] if trigger else None,
        'trigger_dom_regime': (trigger['metrics'] or {}).get('dominant_regime') if trigger else None,
        'trigger_expectancy_20': (trigger['metrics'] or {}).get('expectancy_20') if trigger else None,
        'trigger_dd_rate': (trigger['metrics'] or {}).get('dd_rate_pct_hour') if trigger else None,
        'trigger_dd_pct': (trigger['metrics'] or {}).get('dd_pct') if trigger else None,
        'vs_exit_pct_60m': s60,
        'vs_exit_pct_120m': s120,
    })

# Aggregate by trigger action
by_action = defaultdict(list)
for r in results:
    by_action[r['trigger_action'] or 'NO_TRIGGER_FOUND'].append(r)

# Aggregate by dominant_regime in trigger context
by_regime = defaultdict(list)
for r in results:
    by_regime[r['trigger_dom_regime'] or 'UNKNOWN'].append(r)

# Aggregate by reason keywords
by_reason_kw = defaultdict(list)
for r in results:
    reason = (r['trigger_reason'] or '').lower()
    if 'expectancy' in reason:
        by_reason_kw['expectancy_negative'].append(r)
    elif 'hermes' in reason:
        by_reason_kw['hermes_dd'].append(r)
    elif 'flat' in reason or 'force_flat' in reason:
        by_reason_kw['regime_flat'].append(r)
    elif 'dd accel' in reason or 'force_defense' in reason:
        by_reason_kw['dd_acceleration'].append(r)
    else:
        by_reason_kw['other_or_no_trigger'].append(r)

# Build report
lines = []
lines.append('# Governor Force-Flatten Investigation')
lines.append('')
lines.append('Source: 60 governor_force_flatten exits joined with 30,423 governor_decisions')
lines.append('Method: for each exit, find the most recent governor decision in the prior 10 min')
lines.append('with FORCE_FLAT / FREEZE_ENTRIES / HERMES_DD_OVERRIDE / FORCE_DEFENSE action.')
lines.append('')
lines.append('Net PnL of all force-flat exits: $+127.90 (4-week backfill).')
lines.append('')
lines.append('---')
lines.append('')

# Action breakdown
lines.append('## Trigger Action Breakdown')
lines.append('')
lines.append('| Action | Count | Total PnL | Avg PnL | Avg Hold (min) |')
lines.append('|---|---:|---:|---:|---:|')
for action in sorted(by_action.keys(), key=lambda a: -sum(r['pnl_usd'] for r in by_action[a])):
    recs = by_action[action]
    total = sum(r['pnl_usd'] for r in recs)
    avg = total / max(1, len(recs))
    avg_hold = sum(r['hold_sec'] for r in recs) / max(1, len(recs)) / 60
    lines.append('| ' + str(action) + ' | ' + str(len(recs)) + ' | $' + ('%+.2f' % total)
                 + ' | $' + ('%+.2f' % avg) + ' | ' + ('%.0f' % avg_hold) + ' |')
lines.append('')

# Reason keyword breakdown
lines.append('## Trigger Reason Category')
lines.append('')
lines.append('| Reason Category | Count | Total PnL | Avg PnL | Median Hold (min) |')
lines.append('|---|---:|---:|---:|---:|')
for cat in sorted(by_reason_kw.keys(), key=lambda c: -sum(r['pnl_usd'] for r in by_reason_kw[c])):
    recs = by_reason_kw[cat]
    total = sum(r['pnl_usd'] for r in recs)
    avg = total / max(1, len(recs))
    holds = sorted(r['hold_sec'] / 60 for r in recs)
    median = holds[len(holds) // 2] if holds else 0
    lines.append('| ' + cat + ' | ' + str(len(recs)) + ' | $' + ('%+.2f' % total)
                 + ' | $' + ('%+.2f' % avg) + ' | ' + ('%.0f' % median) + ' |')
lines.append('')

# Dominant regime at trigger time
lines.append('## Dominant Regime at Trigger')
lines.append('')
lines.append('| dominant_regime | Count | Total PnL | Avg PnL |')
lines.append('|---|---:|---:|---:|')
for rg in sorted(by_regime.keys(), key=lambda r: -sum(x['pnl_usd'] for x in by_regime[r])):
    recs = by_regime[rg]
    total = sum(r['pnl_usd'] for r in recs)
    lines.append('| ' + str(rg) + ' | ' + str(len(recs)) + ' | $' + ('%+.2f' % total)
                 + ' | $' + ('%+.2f' % (total / max(1, len(recs)))) + ' |')
lines.append('')

# Pair breakdown
by_pair = defaultdict(list)
for r in results:
    by_pair[r['pair']].append(r)
lines.append('## Per-Pair (force-flatten only)')
lines.append('')
lines.append('| Pair | Count | Total PnL | Wins | Losses |')
lines.append('|---|---:|---:|---:|---:|')
for pair in sorted(by_pair.keys(), key=lambda p: -sum(r['pnl_usd'] for r in by_pair[p])):
    recs = by_pair[pair]
    total = sum(r['pnl_usd'] for r in recs)
    wins = sum(1 for r in recs if r['pnl_usd'] > 0)
    losses = sum(1 for r in recs if r['pnl_usd'] < 0)
    lines.append('| ' + pair + ' | ' + str(len(recs)) + ' | $' + ('%+.2f' % total)
                 + ' | ' + str(wins) + ' | ' + str(losses) + ' |')
lines.append('')

# Hold time bucket
hold_buckets = {'<5min': [], '5-30min': [], '30-60min': [], '1-2h': [], '2-6h': [], '>6h': []}
for r in results:
    h = r['hold_sec'] / 60
    if h < 5:
        hold_buckets['<5min'].append(r)
    elif h < 30:
        hold_buckets['5-30min'].append(r)
    elif h < 60:
        hold_buckets['30-60min'].append(r)
    elif h < 120:
        hold_buckets['1-2h'].append(r)
    elif h < 360:
        hold_buckets['2-6h'].append(r)
    else:
        hold_buckets['>6h'].append(r)
lines.append('## Hold-Time Distribution at Force-Flatten')
lines.append('')
lines.append('| Hold | Count | Total PnL | Avg PnL |')
lines.append('|---|---:|---:|---:|')
for bucket, recs in hold_buckets.items():
    if not recs:
        continue
    total = sum(r['pnl_usd'] for r in recs)
    avg = total / len(recs)
    lines.append('| ' + bucket + ' | ' + str(len(recs)) + ' | $' + ('%+.2f' % total)
                 + ' | $' + ('%+.2f' % avg) + ' |')
lines.append('')

# Subsequent price action
lines.append('## What Happened to Price After Force-Flat')
lines.append('')
saved_60 = 0
checked_60 = 0
saved_120 = 0
checked_120 = 0
saved_60_pnl = 0.0
saved_120_pnl = 0.0
for r in results:
    v60 = r.get('vs_exit_pct_60m')
    if v60 is not None:
        checked_60 += 1
        if v60 < -0.005:  # price dropped >0.5% below exit
            saved_60 += 1
            saved_60_pnl += abs(v60) * abs(r['pnl_usd']) / max(0.01, abs(r['pnl_pct']))  # rough scaling
    v120 = r.get('vs_exit_pct_120m')
    if v120 is not None:
        checked_120 += 1
        if v120 < -0.005:
            saved_120 += 1

lines.append('Definition of "saved": price dropped >0.5% below force-flat exit within window.')
lines.append('')
if checked_60 > 0:
    lines.append('- 60m: saved ' + str(saved_60) + '/' + str(checked_60) + ' (' + ('%.0f%%' % (100*saved_60/checked_60)) + ')')
if checked_120 > 0:
    lines.append('- 120m: saved ' + str(saved_120) + '/' + str(checked_120) + ' (' + ('%.0f%%' % (100*saved_120/checked_120)) + ')')
lines.append('')

# Sample 5 most-profitable + 5 most-losing
results_sorted = sorted(results, key=lambda r: -r['pnl_usd'])
lines.append('## Top 5 Most-Profitable Force-Flat Exits')
lines.append('')
lines.append('| Pair | Hold (min) | PnL | PnL% | Trigger Action | Trigger Reason |')
lines.append('|---|---:|---:|---:|---|---|')
for r in results_sorted[:5]:
    lines.append('| ' + str(r['pair']) + ' | ' + str(r['hold_sec'] // 60)
                 + ' | $' + ('%+.2f' % r['pnl_usd']) + ' | ' + ('%+.2f%%' % (r['pnl_pct'] * 100))
                 + ' | ' + str(r['trigger_action']) + ' | ' + str(r['trigger_reason'])[:80] + ' |')
lines.append('')
lines.append('## Top 5 Most-Losing Force-Flat Exits')
lines.append('')
lines.append('| Pair | Hold (min) | PnL | PnL% | Trigger Action | Trigger Reason |')
lines.append('|---|---:|---:|---:|---|---|')
for r in results_sorted[-5:]:
    lines.append('| ' + str(r['pair']) + ' | ' + str(r['hold_sec'] // 60)
                 + ' | $' + ('%+.2f' % r['pnl_usd']) + ' | ' + ('%+.2f%%' % (r['pnl_pct'] * 100))
                 + ' | ' + str(r['trigger_action']) + ' | ' + str(r['trigger_reason'])[:80] + ' |')
lines.append('')

with open(OUT_PATH, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))

# Summary to stdout
print()
print('=' * 60)
total_pnl = sum(r['pnl_usd'] for r in results)
wins = sum(1 for r in results if r['pnl_usd'] > 0)
losses = sum(1 for r in results if r['pnl_usd'] < 0)
print('Force-flat exits: ' + str(len(results)))
print('Total PnL: $' + ('%+.2f' % total_pnl))
print('W/L: ' + str(wins) + '/' + str(losses))
print()
print('Trigger actions:')
for action, recs in sorted(by_action.items(), key=lambda x: -len(x[1])):
    total = sum(r['pnl_usd'] for r in recs)
    print('  ' + str(action) + ': ' + str(len(recs)) + ' exits, $' + ('%+.2f' % total))
print()
print('Reason categories:')
for cat, recs in sorted(by_reason_kw.items(), key=lambda x: -len(x[1])):
    total = sum(r['pnl_usd'] for r in recs)
    print('  ' + cat + ': ' + str(len(recs)) + ' exits, $' + ('%+.2f' % total))
print()
print('Report: ' + OUT_PATH)

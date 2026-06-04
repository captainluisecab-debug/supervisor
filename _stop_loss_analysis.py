"""Stop-loss / hold-logic forensic analysis.

Uses exit_counterfactuals.jsonl: every exit + its 30/60/120-minute post-exit
price snapshots. For each exit, computes:
  - did price recover above exit price within X min? (= would-have-won if held)
  - did price keep falling? (= correct exit)

Then aggregates per exit_reason (stop_hit, trail_hit, etc.) and per-pair to
identify how much money was left on the table by exits firing on noise.
"""
import sys, json, os
sys.path.insert(0, r'C:\Projects\supervisor')

from collections import defaultdict, Counter

EXIT_PATH = r'C:\Projects\enzobot\logs\exit_counterfactuals.jsonl'
OUT_PATH = r'C:\Projects\supervisor\stop_loss_analysis_report.md'

# Recovery threshold: how much price recovered above exit to count as "stop was wrong"
RECOVERY_THRESHOLDS = [0.0, 0.005, 0.01, 0.02]  # 0%, 0.5%, 1%, 2%

# Load all records, separate exits and snapshots
exits = []
snapshots_by_id = defaultdict(list)
with open(EXIT_PATH, encoding='utf-8') as f:
    for line in f:
        try:
            d = json.loads(line)
        except Exception:
            continue
        t = d.get('type')
        if t == 'exit':
            exits.append(d)
        elif t == 'snapshot':
            snapshots_by_id[d.get('id')].append(d)

print('Loaded ' + str(len(exits)) + ' exit records')
print('Snapshots for ' + str(len(snapshots_by_id)) + ' unique exit ids')

# For each exit, find its snapshots at 30/60/120 min
def lookup_vs_exit(snaps, minutes):
    for s in snaps:
        if s.get('minutes') == minutes:
            return s.get('vs_exit_pct')
    return None


# Per-exit enrichment
enriched = []
for e in exits:
    eid = e.get('id')
    snaps = snapshots_by_id.get(eid, [])
    e30 = lookup_vs_exit(snaps, 30)
    e60 = lookup_vs_exit(snaps, 60)
    e120 = lookup_vs_exit(snaps, 120)
    enriched.append({
        'id': eid,
        'pair': e.get('pair'),
        'exit_reason': e.get('exit_reason'),
        'pnl_pct': float(e.get('pnl_pct', 0) or 0),
        'pnl_usd': float(e.get('pnl_usd', 0) or 0),
        'hold_sec': int(e.get('hold_sec', 0) or 0),
        'partial': bool(e.get('partial')),
        'vs30': e30, 'vs60': e60, 'vs120': e120,
        'has_snapshots': any(x is not None for x in (e30, e60, e120)),
    })

# Per exit_reason aggregation
def analyze_reason(reason, recs):
    n = len(recs)
    if n == 0:
        return None
    out = {'count': n, 'total_pnl': sum(r['pnl_usd'] for r in recs)}
    out['avg_pnl'] = out['total_pnl'] / n
    out['avg_pnl_pct'] = sum(r['pnl_pct'] for r in recs) / n

    # For each recovery threshold, what fraction of exits saw price come back?
    for thresh in RECOVERY_THRESHOLDS:
        for window in (30, 60, 120):
            # For longs: vs_exit_pct > thresh means price ROSE after exit (would-have-won-if-held)
            recovered = 0
            checked = 0
            for r in recs:
                key = 'vs' + str(window)
                v = r.get(key)
                if v is None:
                    continue
                checked += 1
                if v > thresh:
                    recovered += 1
            if checked > 0:
                out['recover_' + ('%.1f' % (thresh * 100)) + 'pct_at_' + str(window) + 'm'] = (recovered, checked, recovered / checked)
    return out


by_reason = defaultdict(list)
for r in enriched:
    by_reason[r['exit_reason']].append(r)

# Per-pair stop_hit analysis
stop_hits = [r for r in enriched if r['exit_reason'] == 'stop_hit']
trail_hits = [r for r in enriched if r['exit_reason'] == 'trail_hit']
score_drops = [r for r in enriched if r['exit_reason'] == 'score_drop_exit']

per_pair_stops = defaultdict(list)
for r in stop_hits:
    per_pair_stops[r['pair']].append(r)


def fmt_recovery(stats, thresh, window):
    key = 'recover_' + ('%.1f' % (thresh * 100)) + 'pct_at_' + str(window) + 'm'
    if key not in stats:
        return 'n/a'
    rec, total, pct = stats[key]
    return str(rec) + '/' + str(total) + ' (' + ('%.0f%%' % (100 * pct)) + ')'


# Build report
lines = []
lines.append('# Stop-Loss / Hold-Logic Forensic Analysis')
lines.append('')
lines.append('Source: exit_counterfactuals.jsonl (4 weeks, 295 exits with post-exit price snapshots)')
lines.append('Question: for each exit type, how often did price RECOVER after exit (i.e., the exit was premature)?')
lines.append('')
lines.append('Method: each exit has 30/60/120-min post-exit snapshots with `vs_exit_pct = snap_price/exit_price - 1`.')
lines.append('Positive vs_exit_pct = price ROSE after we exited (would-have-won-if-held for a long).')
lines.append('')
lines.append('---')
lines.append('')

# Per-reason summary table
lines.append('## Per Exit Reason — Recovery Rates')
lines.append('')
lines.append('A high recovery rate after `stop_hit` or `trail_hit` = stops/trails were too tight or fired on noise.')
lines.append('A low recovery rate after `take_profit`, `scale_out` = correct exit (price did not extend).')
lines.append('')
lines.append('| exit_reason | n | total_pnl | avg_pnl | recovered@60m (any) | recovered@60m (>1%) | recovered@120m (any) | recovered@120m (>1%) |')
lines.append('|---|---:|---:|---:|---:|---:|---:|---:|')
for reason in ['stop_hit', 'trail_hit', 'score_drop_exit', 'score_drop_warning_30pct',
                'time_stop_no_progress', 'rsi_weak', 'trend_flip', 'psar_trail',
                'take_profit', 'scale_out_50pct', 'scale_out_profit_1.5pct',
                'quick_profit_hitrun', 'governor_force_flatten']:
    recs = by_reason.get(reason, [])
    if not recs:
        continue
    s = analyze_reason(reason, recs)
    lines.append('| ' + reason + ' | ' + str(s['count'])
                 + ' | $' + ('%+.2f' % s['total_pnl'])
                 + ' | $' + ('%+.2f' % s['avg_pnl'])
                 + ' | ' + fmt_recovery(s, 0.0, 60)
                 + ' | ' + fmt_recovery(s, 0.01, 60)
                 + ' | ' + fmt_recovery(s, 0.0, 120)
                 + ' | ' + fmt_recovery(s, 0.01, 120)
                 + ' |')
lines.append('')

# Stop-hit deep dive
lines.append('## Stop-Hit Deep Dive')
lines.append('')
lines.append('Total stop_hit exits: ' + str(len(stop_hits)))
lines.append('Total stop_hit PnL: $' + ('%+.2f' % sum(r['pnl_usd'] for r in stop_hits)))
lines.append('Avg stop loss: $' + ('%+.2f' % (sum(r['pnl_usd'] for r in stop_hits) / max(1, len(stop_hits)))))
lines.append('Avg stop loss %: ' + ('%+.2f%%' % (100 * sum(r['pnl_pct'] for r in stop_hits) / max(1, len(stop_hits)))))
lines.append('')

# Distribution of vs_exit at 60m for stop_hits
buckets_60m = [0, 0, 0, 0, 0]  # <-2%, -2 to 0, 0 to +1%, +1% to +2%, >+2%
buckets_120m = [0, 0, 0, 0, 0]
for r in stop_hits:
    for v_key, buckets in [('vs60', buckets_60m), ('vs120', buckets_120m)]:
        v = r.get(v_key)
        if v is None:
            continue
        if v < -0.02:
            buckets[0] += 1
        elif v < 0:
            buckets[1] += 1
        elif v < 0.01:
            buckets[2] += 1
        elif v < 0.02:
            buckets[3] += 1
        else:
            buckets[4] += 1

lines.append('### Where did price end up after the stop fired?')
lines.append('')
lines.append('| Window | < -2% | -2% to 0 | 0 to +1% | +1% to +2% | > +2% |')
lines.append('|---|---:|---:|---:|---:|---:|')
total_60 = sum(buckets_60m)
total_120 = sum(buckets_120m)
if total_60 > 0:
    lines.append('| 60min | ' + str(buckets_60m[0]) + ' (' + ('%.0f%%' % (100*buckets_60m[0]/total_60)) + ') | '
                 + str(buckets_60m[1]) + ' (' + ('%.0f%%' % (100*buckets_60m[1]/total_60)) + ') | '
                 + str(buckets_60m[2]) + ' (' + ('%.0f%%' % (100*buckets_60m[2]/total_60)) + ') | '
                 + str(buckets_60m[3]) + ' (' + ('%.0f%%' % (100*buckets_60m[3]/total_60)) + ') | '
                 + str(buckets_60m[4]) + ' (' + ('%.0f%%' % (100*buckets_60m[4]/total_60)) + ') |')
if total_120 > 0:
    lines.append('| 120min | ' + str(buckets_120m[0]) + ' (' + ('%.0f%%' % (100*buckets_120m[0]/total_120)) + ') | '
                 + str(buckets_120m[1]) + ' (' + ('%.0f%%' % (100*buckets_120m[1]/total_120)) + ') | '
                 + str(buckets_120m[2]) + ' (' + ('%.0f%%' % (100*buckets_120m[2]/total_120)) + ') | '
                 + str(buckets_120m[3]) + ' (' + ('%.0f%%' % (100*buckets_120m[3]/total_120)) + ') | '
                 + str(buckets_120m[4]) + ' (' + ('%.0f%%' % (100*buckets_120m[4]/total_120)) + ') |')
lines.append('')

# Per-pair stop_hit breakdown
lines.append('### Per-Pair Stop-Hit Recovery')
lines.append('')
lines.append('| Pair | n_stops | total_pnl | recovered@60m (>1%) | recovered@120m (>1%) |')
lines.append('|---|---:|---:|---:|---:|')
for pair in sorted(per_pair_stops.keys(), key=lambda p: -len(per_pair_stops[p])):
    recs = per_pair_stops[pair]
    rec_60 = sum(1 for r in recs if r.get('vs60') is not None and r['vs60'] > 0.01)
    chk_60 = sum(1 for r in recs if r.get('vs60') is not None)
    rec_120 = sum(1 for r in recs if r.get('vs120') is not None and r['vs120'] > 0.01)
    chk_120 = sum(1 for r in recs if r.get('vs120') is not None)
    pnl = sum(r['pnl_usd'] for r in recs)
    f60 = '%d/%d (%.0f%%)' % (rec_60, chk_60, 100*rec_60/chk_60) if chk_60 > 0 else 'n/a'
    f120 = '%d/%d (%.0f%%)' % (rec_120, chk_120, 100*rec_120/chk_120) if chk_120 > 0 else 'n/a'
    lines.append('| ' + pair + ' | ' + str(len(recs)) + ' | $' + ('%+.2f' % pnl)
                 + ' | ' + f60 + ' | ' + f120 + ' |')
lines.append('')

# Trail-hit analysis
lines.append('## Trail-Hit Analysis (37 exits, -$38)')
lines.append('')
lines.append('Same question for trailing-stop exits.')
lines.append('')
trail_60_recovered = sum(1 for r in trail_hits if r.get('vs60') is not None and r['vs60'] > 0.01)
trail_60_checked = sum(1 for r in trail_hits if r.get('vs60') is not None)
trail_120_recovered = sum(1 for r in trail_hits if r.get('vs120') is not None and r['vs120'] > 0.01)
trail_120_checked = sum(1 for r in trail_hits if r.get('vs120') is not None)
if trail_60_checked > 0:
    lines.append('- 60m recovery (>1% above trail exit): ' + str(trail_60_recovered) + '/' + str(trail_60_checked)
                 + ' (' + ('%.0f%%' % (100 * trail_60_recovered / trail_60_checked)) + ')')
if trail_120_checked > 0:
    lines.append('- 120m recovery (>1% above trail exit): ' + str(trail_120_recovered) + '/' + str(trail_120_checked)
                 + ' (' + ('%.0f%%' % (100 * trail_120_recovered / trail_120_checked)) + ')')
lines.append('')

# Force-flatten analysis (the profitable ones)
ff = by_reason.get('governor_force_flatten', [])
lines.append('## Governor Force-Flatten Analysis (' + str(len(ff)) + ' exits, +$127.90)')
lines.append('')
lines.append('Question: were these correct exits (price kept going against us) or also premature?')
lines.append('')
ff_60_dropped = sum(1 for r in ff if r.get('vs60') is not None and r['vs60'] < -0.005)
ff_60_checked = sum(1 for r in ff if r.get('vs60') is not None)
ff_120_dropped = sum(1 for r in ff if r.get('vs120') is not None and r['vs120'] < -0.005)
ff_120_checked = sum(1 for r in ff if r.get('vs120') is not None)
if ff_60_checked > 0:
    lines.append('- 60m: price kept dropping >0.5% below force-flat exit: ' + str(ff_60_dropped)
                 + '/' + str(ff_60_checked) + ' (' + ('%.0f%%' % (100*ff_60_dropped/ff_60_checked)) + ')')
if ff_120_checked > 0:
    lines.append('- 120m: same: ' + str(ff_120_dropped) + '/' + str(ff_120_checked)
                 + ' (' + ('%.0f%%' % (100*ff_120_dropped/ff_120_checked)) + ')')
lines.append('')

# Stop loss DEPTH analysis
lines.append('## Stop-Loss Depth Distribution')
lines.append('')
lines.append('How deep was each stop loss? (pnl_pct at exit for stop_hit trades)')
lines.append('')
loss_buckets = {'<-5%': 0, '-5% to -3%': 0, '-3% to -2%': 0, '-2% to -1%': 0, '> -1%': 0}
for r in stop_hits:
    p = r['pnl_pct']
    if p < -0.05:
        loss_buckets['<-5%'] += 1
    elif p < -0.03:
        loss_buckets['-5% to -3%'] += 1
    elif p < -0.02:
        loss_buckets['-3% to -2%'] += 1
    elif p < -0.01:
        loss_buckets['-2% to -1%'] += 1
    else:
        loss_buckets['> -1%'] += 1
for b, cnt in loss_buckets.items():
    pct = 100 * cnt / max(1, len(stop_hits))
    lines.append('- ' + b + ': ' + str(cnt) + ' (' + ('%.0f%%' % pct) + ')')
lines.append('')

# Hold-time-at-stop
hold_minutes = sorted([r['hold_sec'] / 60 for r in stop_hits])
if hold_minutes:
    median = hold_minutes[len(hold_minutes) // 2]
    p25 = hold_minutes[len(hold_minutes) // 4]
    p75 = hold_minutes[3 * len(hold_minutes) // 4]
    lines.append('## Stop-Hit Hold Time')
    lines.append('')
    lines.append('- p25: ' + str(int(p25)) + ' min')
    lines.append('- median: ' + str(int(median)) + ' min')
    lines.append('- p75: ' + str(int(p75)) + ' min')
    lines.append('- min/max: ' + str(int(min(hold_minutes))) + '/' + str(int(max(hold_minutes))) + ' min')
    lines.append('')

with open(OUT_PATH, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))

print()
print('Report: ' + OUT_PATH)
print()
# Print key summary to stdout
print('=' * 60)
print('KEY FINDINGS:')
sh_60_recovered = sum(1 for r in stop_hits if r.get('vs60') is not None and r['vs60'] > 0.01)
sh_60_checked = sum(1 for r in stop_hits if r.get('vs60') is not None)
sh_120_recovered = sum(1 for r in stop_hits if r.get('vs120') is not None and r['vs120'] > 0.01)
sh_120_checked = sum(1 for r in stop_hits if r.get('vs120') is not None)
if sh_60_checked > 0:
    print('Stop-hit recovery >1% at 60m: ' + str(sh_60_recovered) + '/' + str(sh_60_checked)
          + ' (' + ('%.0f%%' % (100*sh_60_recovered/sh_60_checked)) + ')')
if sh_120_checked > 0:
    print('Stop-hit recovery >1% at 120m: ' + str(sh_120_recovered) + '/' + str(sh_120_checked)
          + ' (' + ('%.0f%%' % (100*sh_120_recovered/sh_120_checked)) + ')')
sh_60_anyrec = sum(1 for r in stop_hits if r.get('vs60') is not None and r['vs60'] > 0)
print('Stop-hit any positive recovery at 60m: ' + str(sh_60_anyrec) + '/' + str(sh_60_checked)
      + ' (' + ('%.0f%%' % (100*sh_60_anyrec/max(1, sh_60_checked))) + ')')

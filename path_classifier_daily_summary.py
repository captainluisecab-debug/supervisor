"""Daily summary for kraken_path_classifier shadow mode.

Run from the 8 PM evening brief. Appends a daily section to
supervisor/path_classifier_shadow.md with per-pair classification stats.
"""
import sys, json, os
sys.path.insert(0, r'C:\Projects\supervisor')

from time_fmt import fmt_full, now_utc
from datetime import timedelta
from collections import defaultdict, Counter

LOG_PATH = r'C:\Projects\enzobot\logs\path_classifier_log.jsonl'
COMP_PATH = r'C:\Projects\enzobot\logs\path_classifier_comparison.jsonl'
OUT_PATH = r'C:\Projects\supervisor\path_classifier_shadow.md'

now = now_utc()
window_start = now - timedelta(hours=24)
cutoff_ts = window_start.timestamp()

# Load classifier log (last 24h)
classifications = defaultdict(list)
total_count = 0
try:
    with open(LOG_PATH, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            ts = d.get('ts', 0)
            if ts < cutoff_ts:
                continue
            pair = d.get('pair')
            if not pair:
                continue
            classifications[pair].append(d)
            total_count += 1
except FileNotFoundError:
    pass

# Per-pair metrics
pair_metrics = {}
for pair, records in classifications.items():
    if not records:
        continue
    states = [r.get('state') for r in records]
    state_dist = Counter(states)

    flicker_count = 0
    for i in range(2, len(states)):
        if states[i - 2] == states[i] and states[i - 1] != states[i]:
            flicker_count += 1
    flicker_rate = flicker_count / max(1, len(states) - 2)

    non_chop = sum(1 for s in states if s != 'chop')
    coverage = non_chop / max(1, len(states))

    false_chop = 0
    has_clean = 0
    for r in records:
        feats = r.get('features') or {}
        hh = feats.get('swing_HH', 0)
        hl = feats.get('swing_HL', 0)
        ll = feats.get('swing_LL', 0)
        lh = feats.get('swing_LH', 0)
        clean = (hh + hl) >= 4 or (ll + lh) >= 4
        if clean:
            has_clean += 1
            if r.get('state') == 'chop':
                false_chop += 1
    false_chop_rate = false_chop / max(1, has_clean) if has_clean > 0 else 0.0

    chop_with_feat = 0
    chop_total = 0
    for r in records:
        if r.get('state') != 'chop':
            continue
        chop_total += 1
        feats = r.get('features') or {}
        rsi_pp = feats.get('rsi_50_cross_count_24', 0) >= 3
        hh_total = feats.get('swing_HH', 0) + feats.get('swing_HL', 0)
        ll_total = feats.get('swing_LL', 0) + feats.get('swing_LH', 0)
        no_struct = hh_total < 3 and ll_total < 3
        atr_neutral = (not feats.get('atr_expanding', False)) and (not feats.get('atr_contracting', False))
        if rsi_pp or no_struct or atr_neutral:
            chop_with_feat += 1
    justified_chop_rate = chop_with_feat / max(1, chop_total) if chop_total > 0 else 1.0

    pair_metrics[pair] = {
        'count': len(records),
        'state_dist': dict(state_dist),
        'flicker_rate': flicker_rate,
        'coverage': coverage,
        'false_chop_rate': false_chop_rate,
        'justified_chop_rate': justified_chop_rate,
        'has_clean_struct': has_clean,
        'chop_total': chop_total,
    }

# Disagreements
disagreements = []
try:
    with open(COMP_PATH, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            ts = d.get('ts', 0)
            if ts < cutoff_ts:
                continue
            disagreements.append(d)
except FileNotFoundError:
    pass

# Build markdown
lines = []
lines.append('## ' + now.strftime('%Y-%m-%d') + ' (' + fmt_full(now) + ')')
lines.append('')
lines.append('Window: 24h ending ' + fmt_full(now))
lines.append('Total classifications: ' + str(total_count))
lines.append('Pairs observed: ' + str(len(pair_metrics)))
lines.append('Disagreements (score vs classifier): ' + str(len(disagreements)))
lines.append('')

if pair_metrics:
    lines.append('### Per-pair metrics')
    lines.append('')
    lines.append('| pair | n | flicker | coverage | false_chop | justified_chop |')
    lines.append('|---|---:|---:|---:|---:|---:|')
    for pair in sorted(pair_metrics.keys()):
        m = pair_metrics[pair]
        lines.append('| ' + pair + ' | ' + str(m['count'])
                     + ' | ' + ('%.1f%%' % (100 * m['flicker_rate']))
                     + ' | ' + ('%.1f%%' % (100 * m['coverage']))
                     + ' | ' + ('%.1f%%' % (100 * m['false_chop_rate']))
                     + ' | ' + ('%.1f%%' % (100 * m['justified_chop_rate']))
                     + ' |')
    lines.append('')

if disagreements:
    lines.append('### Disagreement breakdown')
    lines.append('')
    by_pair_d = Counter(d.get('pair') for d in disagreements)
    for pair in sorted(by_pair_d.keys(), key=lambda p: -by_pair_d[p]):
        cls_more = sum(1 for d in disagreements
                       if d.get('pair') == pair
                       and not d.get('score_pass') and d.get('classifier_pass'))
        cls_block = sum(1 for d in disagreements
                        if d.get('pair') == pair
                        and d.get('score_pass') and not d.get('classifier_pass'))
        lines.append('- ' + pair + ': ' + str(by_pair_d[pair])
                     + ' total | classifier_would_allow_more=' + str(cls_more)
                     + ' | classifier_would_block_more=' + str(cls_block))
    lines.append('')

# Universe state distribution
all_states = []
for m in pair_metrics.values():
    for state, cnt in m['state_dist'].items():
        all_states.extend([state] * cnt)
state_counter = Counter(all_states)
if state_counter:
    lines.append('### State distribution (universe total)')
    lines.append('')
    for state, cnt in state_counter.most_common():
        pct = 100 * cnt / max(1, total_count)
        lines.append('- ' + state + ': ' + str(cnt) + ' (' + ('%.1f%%' % pct) + ')')
    lines.append('')

lines.append('---')
lines.append('')

output = '\n'.join(lines)
if not os.path.exists(OUT_PATH):
    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        f.write('# Path Classifier Shadow Daily Summary\n\n')
        f.write('Auto-generated by `path_classifier_daily_summary.py` at evening briefs.\n\n')
        f.write(output)
else:
    with open(OUT_PATH, 'a', encoding='utf-8') as f:
        f.write(output)

print('Path classifier daily summary appended to:', OUT_PATH)
print('Window: 24h ending ' + fmt_full(now))
print('Classifications:', total_count, 'across', len(pair_metrics), 'pairs')
print('Disagreements:', len(disagreements))

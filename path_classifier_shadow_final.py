"""Final shadow-period report for path_classifier (graduation decision).

Runs once at end of shadow period (2026-05-15 Thu 20:00 ET). Evaluates
F1-F5 graduation criteria from SPEC v2 and writes
supervisor/path_classifier_shadow_final.md.
"""
import sys, json, os, glob, gzip
sys.path.insert(0, r'C:\Projects\supervisor')

from time_fmt import fmt_full, now_utc
from datetime import timedelta
from collections import defaultdict, Counter

LOG_PATH = r'C:\Projects\enzobot\logs\path_classifier_log.jsonl'
LOG_DIR = r'C:\Projects\enzobot\logs'
COMP_PATH = r'C:\Projects\enzobot\logs\path_classifier_comparison.jsonl'
OUT_PATH = r'C:\Projects\supervisor\path_classifier_shadow_final.md'

SHADOW_DAYS = 14

now = now_utc()
window_start = now - timedelta(days=SHADOW_DAYS)
cutoff_ts = window_start.timestamp()


def load_jsonl(path):
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def load_jsonl_gz(path):
    out = []
    with gzip.open(path, 'rt', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


# Load all classifications across active + archives within shadow window
all_records = []
all_records.extend(load_jsonl(LOG_PATH))
for arc in glob.glob(os.path.join(LOG_DIR, 'path_classifier_log_*.jsonl.gz')):
    all_records.extend(load_jsonl_gz(arc))

all_records = [r for r in all_records if r.get('ts', 0) >= cutoff_ts]
total_classifications = len(all_records)

by_pair = defaultdict(list)
for r in all_records:
    p = r.get('pair')
    if p:
        by_pair[p].append(r)


# F1: Stability (flicker rate per 4h window)
def compute_flicker_per_4h(records):
    if len(records) < 4:
        return 0.0
    records = sorted(records, key=lambda r: r.get('ts', 0))
    flicker_total = 0
    sample_total = 0
    bucket_size_sec = 4 * 3600
    bucket_start = records[0].get('ts', 0)
    bucket = []
    for r in records:
        if r.get('ts', 0) - bucket_start > bucket_size_sec:
            states = [x.get('state') for x in bucket]
            for i in range(2, len(states)):
                sample_total += 1
                if states[i - 2] == states[i] and states[i - 1] != states[i]:
                    flicker_total += 1
            bucket_start = r.get('ts', 0)
            bucket = []
        bucket.append(r)
    states = [x.get('state') for x in bucket]
    for i in range(2, len(states)):
        sample_total += 1
        if states[i - 2] == states[i] and states[i - 1] != states[i]:
            flicker_total += 1
    return flicker_total / max(1, sample_total)


f1_results = {}
for pair, recs in by_pair.items():
    f1_results[pair] = compute_flicker_per_4h(recs)
f1_max = max(f1_results.values()) if f1_results else 0.0
f1_pass = f1_max < 0.15


# F2: Chop fidelity
def chop_fidelity(records):
    chop_records = [r for r in records if r.get('state') == 'chop']
    chop_with_feat = 0
    for r in chop_records:
        feats = r.get('features') or {}
        rsi_pp = feats.get('rsi_50_cross_count_24', 0) >= 3
        hh_total = feats.get('swing_HH', 0) + feats.get('swing_HL', 0)
        ll_total = feats.get('swing_LL', 0) + feats.get('swing_LH', 0)
        no_struct = hh_total < 3 and ll_total < 3
        atr_neutral = (not feats.get('atr_expanding', False)) and (not feats.get('atr_contracting', False))
        if rsi_pp or no_struct or atr_neutral:
            chop_with_feat += 1
    justified = chop_with_feat / max(1, len(chop_records)) if chop_records else 1.0

    clean_records = []
    for r in records:
        feats = r.get('features') or {}
        if (feats.get('swing_HH', 0) + feats.get('swing_HL', 0)) >= 4:
            clean_records.append(r)
        elif (feats.get('swing_LL', 0) + feats.get('swing_LH', 0)) >= 4:
            clean_records.append(r)
    false_chop = sum(1 for r in clean_records if r.get('state') == 'chop')
    false_rate = false_chop / max(1, len(clean_records)) if clean_records else 0.0
    return justified, false_rate, len(chop_records), len(clean_records)


f2_justified, f2_false, chop_n, clean_n = chop_fidelity(all_records)
f2_pass = f2_justified >= 0.85 and f2_false <= 0.10


# F3: Decision differentiation
disagreements = load_jsonl(COMP_PATH)
disagreements = [d for d in disagreements if d.get('ts', 0) >= cutoff_ts]
f3_disagreement_pct = len(disagreements) / max(1, total_classifications)
f3_pass = f3_disagreement_pct >= 0.10


# F4: Predictive validity
disagreement_count = len(disagreements)
if disagreement_count < 10:
    f4_status = 'INSUFFICIENT_DATA (sample=' + str(disagreement_count) + ', need >=10) -> REVISE'
    f4_pass = False
    f4_insufficient = True
else:
    f4_status = 'sample=' + str(disagreement_count) + '. Quality eval requires join with exit_counterfactuals.jsonl (operator review).'
    f4_pass = False
    f4_insufficient = False


# F5: Per-pair sanity (no pair stuck > 24h)
def stuck_pairs(by_pair_dict, hours=24):
    stuck = []
    sec = hours * 3600
    for pair, recs in by_pair_dict.items():
        recs = sorted(recs, key=lambda r: r.get('ts', 0))
        if len(recs) < 2:
            continue
        run_start_ts = recs[0].get('ts', 0)
        run_state = recs[0].get('state')
        for r in recs[1:]:
            if r.get('state') != run_state:
                run_start_ts = r.get('ts', 0)
                run_state = r.get('state')
            else:
                if r.get('ts', 0) - run_start_ts > sec:
                    stuck.append((pair, run_state, (r.get('ts', 0) - run_start_ts) / 3600.0))
                    break
    return stuck


stuck = stuck_pairs(by_pair, 24)
f5_pass = len(stuck) == 0

# Build report
lines = []
lines.append('# Path Classifier Shadow Final Report')
lines.append('')
lines.append('Generated: ' + fmt_full(now))
lines.append('Shadow window: 14 days ending ' + fmt_full(now))
lines.append('Total classifications: ' + str(total_classifications))
lines.append('Pairs observed: ' + str(len(by_pair)))
lines.append('')
lines.append('---')
lines.append('')
lines.append('## Graduation Criteria')
lines.append('')

lines.append('### F1. Stability - flicker rate < 15% per pair per 4h window')
lines.append('')
lines.append('Result: max flicker rate = ' + ('%.1f%%' % (100 * f1_max)))
lines.append('')
lines.append('Per-pair:')
for pair in sorted(f1_results.keys()):
    lines.append('- ' + pair + ': ' + ('%.1f%%' % (100 * f1_results[pair])))
lines.append('')
lines.append('**Status: ' + ('PASS' if f1_pass else 'FAIL') + '**')
lines.append('')

lines.append('### F2. Chop fidelity')
lines.append('')
lines.append('- Justified-chop rate: ' + ('%.1f%%' % (100 * f2_justified)) + ' (>= 85% required) [n=' + str(chop_n) + ' chop records]')
lines.append('- False-chop rate: ' + ('%.1f%%' % (100 * f2_false)) + ' (<= 10% required) [n=' + str(clean_n) + ' clean-struct records]')
lines.append('')
lines.append('**Status: ' + ('PASS' if f2_pass else 'FAIL') + '**')
lines.append('')

lines.append('### F3. Decision differentiation')
lines.append('')
lines.append('Disagreement rate: ' + ('%.1f%%' % (100 * f3_disagreement_pct)) + ' (>= 10% required)')
lines.append('')
lines.append('**Status: ' + ('PASS' if f3_pass else 'FAIL') + '**')
lines.append('')

lines.append('### F4. Predictive validity')
lines.append('')
lines.append('Sample: ' + str(disagreement_count) + ' disagreement entries')
lines.append('Status detail: ' + f4_status)
lines.append('')
if f4_insufficient:
    lines.append('**Status: INSUFFICIENT_DATA -> REVISE (per SPEC v2 D4 revision)**')
else:
    lines.append('**Status: requires manual quality evaluation (join with exit_counterfactuals)**')
lines.append('')

lines.append('### F5. Per-pair sanity')
lines.append('')
lines.append('Stuck pairs (state held > 24h continuously): ' + str(len(stuck)))
for pair, state, hours in stuck:
    lines.append('- ' + pair + ': stuck in ' + state + ' for ' + ('%.1f' % hours) + 'h')
lines.append('')
lines.append('**Status: ' + ('PASS' if f5_pass else 'FAIL') + '**')
lines.append('')

lines.append('---')
lines.append('')
lines.append('## Summary')
lines.append('')
lines.append('- F1 (stability): ' + ('PASS' if f1_pass else 'FAIL'))
lines.append('- F2 (chop fidelity): ' + ('PASS' if f2_pass else 'FAIL'))
lines.append('- F3 (differentiation): ' + ('PASS' if f3_pass else 'FAIL'))
lines.append('- F4 (predictive): ' + ('INSUFFICIENT' if f4_insufficient else 'NEEDS_REVIEW'))
lines.append('- F5 (sanity): ' + ('PASS' if f5_pass else 'FAIL'))
lines.append('')

# Recommendation
fail_count = sum([not f1_pass, not f2_pass, not f3_pass, not f5_pass])
if f4_insufficient:
    rec = 'REVISE - F4 insufficient sample. Re-shadow 7 days under operator-chosen mitigation (per SPEC G coexistence options).'
elif fail_count == 0:
    rec = 'GRADUATE - all hard criteria pass. Operator quality review on F4 disagreements required. If F4 evidence supports: flip PATH_CLASSIFIER_LIVE=true, BTC-only first.'
elif fail_count == 1:
    rec = 'REVISE - 1 criterion failed. Identify root cause and re-shadow 7 days.'
else:
    rec = 'KILL or REVISE - ' + str(fail_count) + ' criteria failed. Operator decides; default after 2 REVISE cycles is operator KEEP/KILL choice.'

lines.append('## Recommendation')
lines.append('')
lines.append(rec)
lines.append('')
lines.append('Operator final call: GRADUATE / REVISE / KILL.')
lines.append('')

with open(OUT_PATH, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))

print('Final report written to:', OUT_PATH)
print('Recommendation:', rec)

"""24h shakedown check for path_classifier shadow mode.

Reports: classification rate, per-pair coverage, state distribution,
disagreement count, errors, rate-limit/anomaly indicators.
"""
import sys, json, os
sys.path.insert(0, r'C:\Projects\supervisor')

from time_fmt import fmt_full, now_utc
from datetime import timedelta
from collections import Counter

LOG_PATH = r'C:\Projects\enzobot\logs\path_classifier_log.jsonl'
COMP_PATH = r'C:\Projects\enzobot\logs\path_classifier_comparison.jsonl'
SVC_LOG = r'C:\Projects\enzobot\logs\service.log'

now = now_utc()
window_start = now - timedelta(hours=24)
cutoff_ts = window_start.timestamp()


def load_jsonl(path, cutoff):
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                if d.get('ts', 0) >= cutoff:
                    out.append(d)
            except Exception:
                pass
    return out


records = load_jsonl(LOG_PATH, cutoff_ts)
disagreements = load_jsonl(COMP_PATH, cutoff_ts)

print('Path Classifier 24h Shakedown')
print('=' * 60)
print('Generated:', fmt_full(now))
print('Window: 24h ending', fmt_full(now))
print()

n = len(records)
hours_observed = (now.timestamp() - (records[0].get('ts', 0) if records else now.timestamp())) / 3600
hours_observed = max(0.1, hours_observed)
rate = n / hours_observed
print('A. Classifier rate')
print('   Total records:', n)
print('   Observed window: %.1fh' % hours_observed)
print('   Rate: %.0f records/hour (expected ~600/h with 10 pairs * 60/h)' % rate)
print()

pair_counts = Counter(r.get('pair') for r in records)
print('B. Per-pair coverage')
for pair in sorted(pair_counts.keys()):
    print('  ', pair + ':', pair_counts[pair])
if not pair_counts:
    print('   NO RECORDS')
print()

state_counts = Counter(r.get('state') for r in records)
print('C. State distribution')
for state, cnt in state_counts.most_common():
    pct = 100.0 * cnt / max(1, n)
    print('  ', state + ':', cnt, '(%.1f%%)' % pct)
print()

print('D. Score-vs-classifier disagreements')
print('   Total:', len(disagreements))
if disagreements:
    cls_more = sum(1 for d in disagreements if not d.get('score_pass') and d.get('classifier_pass'))
    cls_block = sum(1 for d in disagreements if d.get('score_pass') and not d.get('classifier_pass'))
    print('   classifier_would_allow_more:', cls_more)
    print('   classifier_would_block_more:', cls_block)
    by_pair = Counter(d.get('pair') for d in disagreements)
    print('   Top disagreement pairs:')
    for pair, cnt in by_pair.most_common(5):
        print('    ', pair + ':', cnt)
print()

print('E. [PATH_CLASSIFIER] errors')
err_count = 0
err_samples = []
try:
    with open(SVC_LOG, encoding='utf-8', errors='replace') as f:
        for line in f:
            if 'PATH_CLASSIFIER' in line and ('failed' in line or 'ERROR' in line.upper()):
                err_count += 1
                if len(err_samples) < 5:
                    err_samples.append(line.strip())
except Exception:
    pass
print('   Count:', err_count)
for s in err_samples:
    print('   sample:', s)
print()

anom_count = 0
ratelimit_count = 0
fatal_count = 0
anom_samples = []
try:
    with open(SVC_LOG, encoding='utf-8', errors='replace') as f:
        for line in f:
            if '[ANOMALY]' in line:
                anom_count += 1
                if len(anom_samples) < 3:
                    anom_samples.append(line.strip())
            ll = line.lower()
            if 'rate limit' in ll or 'rate-limit' in ll or 'too many requests' in ll:
                ratelimit_count += 1
            if 'FATAL' in line:
                fatal_count += 1
except Exception:
    pass
print('F. Anomalies + rate-limit')
print('   [ANOMALY] count:', anom_count)
print('   rate-limit indicators:', ratelimit_count)
print('   FATAL count:', fatal_count)
for s in anom_samples:
    print('   anomaly:', s)
print()

print('=' * 60)
problems = []
if err_count > 0:
    problems.append('classifier errors=' + str(err_count))
if rate < 300 and n > 60:
    problems.append('low rate (%.0f/h)' % rate)
if not pair_counts:
    problems.append('no records')
elif min(pair_counts.values()) < 100 and n > 200:
    problems.append('uneven per-pair coverage')
if n > 0 and state_counts.get('chop', 0) / n > 0.95:
    problems.append('100%-chop classification (too defensive)')
if anom_count > 5:
    problems.append('elevated anomaly count')
if ratelimit_count > 0:
    problems.append('rate-limit hits=' + str(ratelimit_count))
if fatal_count > 0:
    problems.append('FATAL crashes=' + str(fatal_count))

if problems:
    print('Recommendation: HOTFIX or HOLD - concerns:', ', '.join(problems))
else:
    print('Recommendation: CONTINUE shadow - clean shakedown.')

"""Verify Kraken trader-live state (2026-04-28 go-live)."""
import json, os, time

print('=' * 60)
print('VERIFY: 2026-04-28 Kraken trader-live go-live state')
print('=' * 60)

p = json.load(open(r'C:\Projects\enzobot\policy.json'))
mst = p['hard_bounds'].get('MIN_SCORE_TO_TRADE')
sde = p['hard_bounds'].get('SCORE_DROP_EXIT')
esf = p['hard_bounds'].get('EXIT_SCORE_FLOOR')
print('policy.json hard_bounds.MIN_SCORE_TO_TRADE:', mst, '(want [88.0, 88.0])')
print('policy.json hard_bounds.SCORE_DROP_EXIT:', sde, '(want [999.0, 999.0])')
print('policy.json hard_bounds.EXIT_SCORE_FLOOR:', esf, '(want [55.0, 55.0])')
print('policy.json PATH_CLASSIFIER_LIVE:', p.get('PATH_CLASSIFIER_LIVE'), '(want True = trader live)')

ba = json.load(open(r'C:\Projects\enzobot\brain_opus_applied.json'))
ba_p = ba['params']
print()
print('brain_opus_applied.json SCORE_DROP_EXIT:', ba_p.get('SCORE_DROP_EXIT'), '(want 999.0)')
print('brain_opus_applied.json MIN_SCORE_TO_TRADE:', ba_p.get('MIN_SCORE_TO_TRADE'), '(want 88.0)')
print('brain_opus_applied.json EXIT_SCORE_FLOOR:', ba_p.get('EXIT_SCORE_FLOOR'), '(want 55.0)')

ps = json.load(open(r'C:\Projects\enzobot\pair_status.json'))
print()
for pair in ('POL/USD', 'DOGE/USD', 'XRP/USD'):
    e = ps.get(pair, {})
    print(pair + ':')
    print('  status:', e.get('status'), '(want DISABLED_SOFT)')
    print('  ttl_ts:', e.get('ttl_ts'))
    print('  reason:', e.get('reason'))

# Classifier shadow file still being written?
shadow_log = r'C:\Projects\enzobot\logs\path_classifier_log.jsonl'
if os.path.exists(shadow_log):
    size = os.path.getsize(shadow_log)
    mtime = os.path.getmtime(shadow_log)
    import time
    age_sec = time.time() - mtime
    print()
    print('Classifier shadow log:')
    print('  file size: ' + str(size) + ' bytes')
    print('  last modified: ' + str(round(age_sec, 1)) + 's ago')
    print('  status:', 'ACTIVE' if age_sec < 180 else 'STALE')
else:
    print()
    print('Classifier shadow log: NOT FOUND')

# Sentinel state (TRADER_LIVE_BTC_NEAR)
sov = json.load(open(r'C:\Projects\enzobot\sentinel_override.json'))
print()
print('Sentinel override:')
print('  source:', sov.get('source'), '(want operator_directive)')
print('  trigger:', sov.get('trigger'), '(want TRADER_LIVE_BTC_NEAR)')
print('  ttl_expiry:', sov.get('ttl_expiry'))
print('  changes.MAX_OPEN_POSITIONS:', sov.get('changes', {}).get('MAX_OPEN_POSITIONS'), '(want 2)')
print('  changes.TARGET_DEPLOY_PCT:', sov.get('changes', {}).get('TARGET_DEPLOY_PCT'), '(want 0.40)')
print('  blocked_pairs count:', len(sov.get('blocked_pairs', [])), '(want 11 = universe minus BTC+NEAR)')
print('  blocked_pairs:', sov.get('blocked_pairs', []))
btc_ok = 'BTC/USD' not in sov.get('blocked_pairs', [])
near_ok = 'NEAR/USD' not in sov.get('blocked_pairs', [])
print('  BTC/USD allowed:', btc_ok)
print('  NEAR/USD allowed:', near_ok)

# kraken_trader file present
import importlib, sys
sys.path.insert(0, r'C:\Projects\enzobot')
print()
try:
    from kraken_trader import ALLOWED_PAIRS, ALLOW_STATES, EXIT_TRIGGER_STATES, PAIR_CONFIG
    print('kraken_trader module: importable')
    print('  ALLOWED_PAIRS:', list(ALLOWED_PAIRS), '(want BTC/USD, NEAR/USD)')
    print('  ALLOW_STATES:', list(ALLOW_STATES))
    print('  EXIT_TRIGGER_STATES:', list(EXIT_TRIGGER_STATES))
    print('  PAIR_CONFIG keys:', list(PAIR_CONFIG.keys()))
except Exception as e:
    print('kraken_trader module: IMPORT FAILED -', type(e).__name__, e)

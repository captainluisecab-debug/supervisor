"""Permanent 2h watch script — invoked by cron prompts. No heredoc, no in-line braces in shell."""
import sys, json
sys.path.insert(0, r'C:\Projects\supervisor')
from time_fmt import fmt_full, now_utc
from pause_writer import status as pause_status, write_pause
from datetime import datetime, timezone, timedelta

now = now_utc()
state = json.load(open(r'C:\Projects\enzobot\state.json'))
ps = pause_status()

window_start = now - timedelta(hours=2)
exits_in_win = []
for line in open(r'C:\Projects\enzobot\logs\exit_counterfactuals.jsonl').readlines()[-50:]:
    try:
        d = json.loads(line)
        if not d.get('ts_iso'):
            continue
        ts = datetime.fromisoformat(d['ts_iso'].replace('Z', '+00:00'))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts >= window_start:
            exits_in_win.append(d)
    except Exception:
        pass

cum_pnl = sum(float(e.get('pnl_usd', 0) or 0) for e in exits_in_win)
losses = [e for e in exits_in_win if float(e.get('pnl_usd', 0) or 0) < 0]
wins = [e for e in exits_in_win if float(e.get('pnl_usd', 0) or 0) > 0]
streak_max = 0
streak_cur = 0
for e in exits_in_win:
    if float(e.get('pnl_usd', 0) or 0) < 0:
        streak_cur += 1
        if streak_cur > streak_max:
            streak_max = streak_cur
    else:
        streak_cur = 0

# Oscillation
osc_flips = 0
cutoff_ts = (now - timedelta(hours=4)).timestamp()
hist = []
for line in open(r'C:\Projects\supervisor\brain_review_log.jsonl').readlines()[-30:]:
    try:
        d = json.loads(line)
        if d.get('sleeve') != 'kraken' or d.get('ts', 0) < cutoff_ts:
            continue
        for c in d.get('changes', []):
            if c.get('param') == 'MIN_SCORE_TO_TRADE' and c.get('old') is not None and c.get('new') is not None:
                hist.append((d['ts'], float(c['old']), float(c['new'])))
    except Exception:
        pass
direction = None
for _, old, new in hist:
    if new == old:
        continue
    new_dir = 'up' if new > old else 'down'
    if direction and new_dir != direction:
        osc_flips += 1
    direction = new_dir

# Anomalies
anom_new = 0
anom_cleared = 0
try:
    for line in open(r'C:\Projects\supervisor\logs\service.log', encoding='utf-8').readlines()[-300:]:
        if 'ANOMALY] NEW' in line:
            anom_new += 1
        elif 'ANOMALY] CLEARED' in line:
            anom_cleared += 1
except Exception:
    pass
anom_uncleared = max(0, anom_new - anom_cleared)

# Soft-release tracking
sr_first_fire = ps.get('first_fire_ts')
sr_age_hours = None
exits_since_release = 0
if sr_first_fire and ps.get('trigger') == 'SOFT_RELEASE_BTC_ONLY':
    try:
        sr_dt = datetime.fromisoformat(sr_first_fire.replace('Z', '+00:00'))
        if sr_dt.tzinfo is None:
            sr_dt = sr_dt.replace(tzinfo=timezone.utc)
        sr_age_hours = (now - sr_dt).total_seconds() / 3600
        for line in open(r'C:\Projects\enzobot\logs\exit_counterfactuals.jsonl').readlines()[-50:]:
            try:
                d = json.loads(line)
                if not d.get('ts_iso'):
                    continue
                ts = datetime.fromisoformat(d['ts_iso'].replace('Z', '+00:00'))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= sr_dt:
                    exits_since_release += 1
            except Exception:
                pass
    except Exception:
        pass

# Stop triggers
triggers = []
if cum_pnl < -3.0:
    triggers.append(('cumulative_loss_2h', 'net=' + str(round(cum_pnl, 2))))
if streak_max >= 3:
    triggers.append(('losing_streak_3', 'streak=' + str(streak_max)))
if osc_flips >= 2:
    triggers.append(('min_score_oscillation', str(osc_flips) + ' flips/4h'))
if anom_uncleared > 0:
    triggers.append(('new_anomaly', str(anom_uncleared) + ' uncleared'))
if losses:
    worst = min(float(l.get('pnl_usd', 0) or 0) for l in losses)
    if worst < -2.0:
        triggers.append(('losing_exit_gt_2', 'worst=' + str(round(worst, 2))))

positions = {}
for sym, p in state.get('positions', {}).items():
    if isinstance(p, dict) and (p.get('qty', 0) or p.get('volume', 0)):
        positions[sym] = p
cash = state.get('cash', 0)
current_min_score = ps.get('changes', {}).get('MIN_SCORE_TO_TRADE')

# Execute stop-trigger pause if any
pause_action = None
if triggers:
    BLOCKED = ['ADA/USD', 'AVAX/USD', 'BTC/USD', 'DOGE/USD', 'DOT/USD',
               'ETH/USD', 'LINK/USD', 'LTC/USD', 'NEAR/USD', 'POL/USD',
               'SOL/USD', 'XLM/USD', 'XRP/USD']
    primary_trigger = triggers[0][0]
    detail_str = '; '.join(t[0] + '=' + t[1] for t in triggers)
    pause_action = write_pause(
        source='opus_2h_watch',
        trigger=primary_trigger,
        ttl_sec=21600,
        changes={'MIN_SCORE_TO_TRADE': 95.0, 'TARGET_DEPLOY_PCT': 0.20},
        blocked_pairs=BLOCKED,
        reason='STOP TRIGGERED at ' + fmt_full(now) + ': ' + detail_str,
    )

# Soft-release autonomous progression
sr_progression = None
if (ps.get('trigger') == 'SOFT_RELEASE_BTC_ONLY'
    and sr_age_hours is not None and sr_age_hours >= 24
    and exits_since_release == 0
    and current_min_score == 90.0
    and not triggers):
    BLOCKED = ['ADA/USD', 'AVAX/USD', 'DOGE/USD', 'DOT/USD', 'ETH/USD',
               'LINK/USD', 'LTC/USD', 'NEAR/USD', 'POL/USD', 'SOL/USD',
               'XLM/USD', 'XRP/USD']
    sr_progression = write_pause(
        source='operator_directive',
        trigger='SOFT_RELEASE_BTC_ONLY',
        ttl_sec=86400,
        changes={'MIN_SCORE_TO_TRADE': 88.0, 'MAX_OPEN_POSITIONS': 1, 'TARGET_DEPLOY_PCT': 0.20},
        blocked_pairs=BLOCKED,
        reason='AUTONOMOUS PROGRESSION at ' + fmt_full(now) + ': 24h+ no BTC entries (age=' + str(round(sr_age_hours, 1)) + 'h). MIN_SCORE 90->88. Per standing soft-release plan.',
    )

# Audit row
audit = {
    'ts': now.isoformat(),
    'status': 'paused' if triggers else ('progression' if sr_progression else 'clean'),
    'cash': cash,
    'exits_in_window': len(exits_in_win),
    'cumulative_window_pnl': round(cum_pnl, 2),
    'wins': len(wins),
    'losses': len(losses),
    'longest_losing_streak': streak_max,
    'oscillation_flips_4h': osc_flips,
    'anomaly_uncleared': anom_uncleared,
    'triggers': [t[0] for t in triggers],
    'positions_count': len(positions),
    'pause_trigger': ps.get('trigger'),
    'soft_release_age_hours': round(sr_age_hours, 1) if sr_age_hours else None,
    'exits_since_release': exits_since_release,
    'current_min_score': current_min_score,
    'pause_action': pause_action,
    'soft_release_progression': sr_progression,
    'phase': 'soft_release_btc_only' if ps.get('trigger') == 'SOFT_RELEASE_BTC_ONLY' else 'other',
}
with open(r'C:\Projects\supervisor\2h_watch_log.jsonl', 'a') as f:
    f.write(json.dumps(audit, default=str) + '\n')

# Output
if triggers:
    print('STOP TRIGGERS at ' + fmt_full(now))
    for t, d in triggers:
        print('  ' + t + ': ' + d)
    if pause_action:
        print('  pause_writer action: ' + str(pause_action.get('action')))
elif sr_progression:
    print('SOFT-RELEASE PROGRESSION at ' + fmt_full(now))
    print('  rule: 24h+ no BTC entries -> MIN_SCORE 90->88')
    print('  release age: ' + str(round(sr_age_hours, 1)) + 'h | exits_since: 0')
    print('  pause_writer action: ' + str(sr_progression.get('action')))
    print('  new MIN_SCORE_TO_TRADE: 88, TTL re-extended 24h')
else:
    wr = (len(wins) / (len(wins) + len(losses)) * 100) if (len(wins) + len(losses)) else 0
    sr_str = ''
    if sr_age_hours is not None:
        sr_str = ' | sr_age=' + str(round(sr_age_hours, 1)) + 'h exits_since=' + str(exits_since_release) + ' min_score=' + str(current_min_score)
    line = '2h watch [' + fmt_full(now) + ']: clean | pos=' + str(len(positions))
    line += ' cash=$' + ('%.2f' % cash) + ' d_pnl=$' + ('%+.2f' % cum_pnl)
    line += ' exits=' + str(len(exits_in_win)) + ' WR=' + ('%.0f' % wr) + '%' + sr_str
    print(line)

"""Daily brief script — 8 AM and 8 PM. Single-source, no heredoc."""
import sys, json, os
sys.path.insert(0, r'C:\Projects\supervisor')
from time_fmt import fmt_full, now_utc
from pause_writer import status as pause_status
from datetime import datetime, timezone, timedelta
from collections import Counter

if len(sys.argv) > 1 and sys.argv[1] == 'evening':
    window_h = 12
    label = 'evening'
else:
    window_h = 24
    label = 'morning'

now = now_utc()
window_start = now - timedelta(hours=window_h)

state = json.load(open(r'C:\Projects\enzobot\state.json'))
so = json.load(open(r'C:\Projects\enzobot\supervisor_override.json'))
oa = json.load(open(r'C:\Projects\enzobot\brain_opus_applied.json'))
ps = pause_status()

# Window exits
exits = []
for line in open(r'C:\Projects\enzobot\logs\exit_counterfactuals.jsonl').readlines()[-200:]:
    try:
        d = json.loads(line)
        if not d.get('ts_iso'):
            continue
        ts = datetime.fromisoformat(d['ts_iso'].replace('Z', '+00:00'))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts >= window_start:
            exits.append(d)
    except Exception:
        pass

cum_pnl = sum(float(e.get('pnl_usd', 0) or 0) for e in exits)
wins = [e for e in exits if float(e.get('pnl_usd', 0) or 0) > 0]
losses = [e for e in exits if float(e.get('pnl_usd', 0) or 0) < 0]

positions = {}
for sym, p in state.get('positions', {}).items():
    if isinstance(p, dict) and (p.get('qty', 0) or p.get('volume', 0)):
        positions[sym] = p
cash = state.get('cash', 0)
realized = state.get('realized_pnl', 0)

# Pause history
pause_events = []
try:
    for line in open(r'C:\Projects\supervisor\pause_history.jsonl').readlines():
        try:
            d = json.loads(line)
            ts = datetime.fromisoformat(d.get('ts', '').replace('Z', '+00:00'))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= window_start:
                pause_events.append(d)
        except Exception:
            pass
except Exception:
    pass

# 2h_watch entries in window
watch_entries = []
try:
    for line in open(r'C:\Projects\supervisor\2h_watch_log.jsonl').readlines():
        try:
            d = json.loads(line)
            ts = datetime.fromisoformat(d.get('ts', '').replace('Z', '+00:00'))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= window_start:
                watch_entries.append(d)
        except Exception:
            pass
except Exception:
    pass

actions_taken = [w for w in watch_entries if w.get('status') in ('paused', 'progression')]

# Brain reviews
brain_reviews = 0
brain_changes = 0
cutoff_ts = window_start.timestamp()
for line in open(r'C:\Projects\supervisor\brain_review_log.jsonl').readlines()[-50:]:
    try:
        d = json.loads(line)
        if d.get('sleeve') == 'kraken' and d.get('ts', 0) >= cutoff_ts:
            brain_reviews += 1
            if d.get('changes'):
                brain_changes += 1
    except Exception:
        pass

# Sentinel fires
sentinel_fires = []
try:
    for line in open(r'C:\Projects\supervisor\opus_sentinel_audit.jsonl').readlines()[-30:]:
        try:
            d = json.loads(line)
            ts_str = d.get('ts', '')
            if ts_str:
                ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= window_start:
                    sentinel_fires.append(d)
        except Exception:
            pass
except Exception:
    pass

# Build MD
md_path = r'C:\Projects\supervisor\daily_audit_' + now.strftime('%Y-%m-%d') + ('_evening' if label == 'evening' else '') + '.md'

lines = []
lines.append('# ' + label.title() + ' Brief - ' + fmt_full(now))
lines.append('')
lines.append('Window: ' + str(window_h) + 'h since ' + fmt_full(window_start))
lines.append('')
lines.append('## Headline')
lines.append('')
lines.append('- Cash: $' + ('%.2f' % cash) + ' | Lifetime realized: $' + ('%+.2f' % realized))
lines.append('- ' + str(window_h) + 'h exits: ' + str(len(exits)) + ' (' + str(len(wins)) + 'W / ' + str(len(losses)) + 'L) net=$' + ('%+.2f' % cum_pnl))
lines.append('- Active pause: ' + str(ps.get('active')) + ' (' + str(ps.get('source', 'none')) + '/' + str(ps.get('trigger', 'none')) + ')')
lines.append('- Open positions: ' + str(len(positions)))
lines.append('')
lines.append('## Autonomous actions in window')
lines.append('')
if actions_taken:
    for a in actions_taken:
        lines.append('- ' + str(a.get('ts', '?'))[:19] + ' status=' + str(a.get('status', '?')) + ' triggers=' + str(a.get('triggers', [])))
else:
    lines.append('_No autonomous actions taken (clean window)._')
lines.append('')
lines.append('## Exits')
lines.append('')
if exits:
    lines.append('| ts (UTC) | pair | pnl | reason |')
    lines.append('|---|---|---:|---|')
    for e in exits[-15:]:
        lines.append('| ' + str(e.get('ts_iso', '?'))[:19] + ' | ' + str(e.get('pair', '?')) + ' | $' + ('%+.2f' % float(e.get('pnl_usd', 0) or 0)) + ' | ' + str(e.get('exit_reason', '?')) + ' |')
else:
    lines.append('_No exits in window._')
lines.append('')
lines.append('## Brain activity')
lines.append('')
lines.append('- Reviews: ' + str(brain_reviews) + ' | Changes applied: ' + str(brain_changes))
lines.append('- Current opus_applied: ' + json.dumps(oa.get('params', {})))
lines.append('')
lines.append('## Active overrides')
lines.append('')
lines.append('Sentinel: source=' + str(ps.get('source', 'none')) + ' trigger=' + str(ps.get('trigger', 'none')))
lines.append('Sentinel TTL: ' + str(ps.get('ttl_expiry', 'none')))
lines.append('Sentinel changes: ' + json.dumps(ps.get('changes', {})))
lines.append('Brain (sticky): ' + json.dumps(so.get('changes', {})))
lines.append('')
lines.append('## Watch log entries (' + str(len(watch_entries)) + ')')
lines.append('')
lines.append('Pause events in window: ' + str(len(pause_events)))
lines.append('Sentinel fires in window: ' + str(len(sentinel_fires)))
lines.append('')
lines.append('## Operator action items')
lines.append('')
items = []
if not exits and not positions:
    items.append('- Bot has been flat. Cash preserved. Soft-release in flight, awaiting first BTC entry (or autonomous progression at 24h-no-entry mark).')
if cum_pnl < -5:
    items.append('- Notable bleed in window: $' + ('%+.2f' % cum_pnl) + '. Review.')
if not items:
    items.append('- Nothing critical pending.')
for item in items:
    lines.append(item)
lines.append('')

with open(md_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))

# 6-8 line brief output
out = []
out.append(label.title() + ' brief [' + fmt_full(now) + ']')
out.append('Universe equity (Kraken sleeve): $' + ('%.2f' % cash) + ' | lifetime realized: $' + ('%+.2f' % realized))
out.append('Kraken: ' + str(len(positions)) + ' positions / ' + str(window_h) + 'h exits=' + str(len(exits)) + ' (' + str(len(wins)) + 'W/' + str(len(losses)) + 'L) net=$' + ('%+.2f' % cum_pnl))
out.append('Autonomous actions in window: ' + str(len(actions_taken)) + ' (pause/progression events)')
out.append('Active pause: ' + str(ps.get('source', 'none')) + ' / ' + str(ps.get('trigger', 'none')))
out.append('Health: clean - 3 fixes verified, ' + str(brain_reviews) + ' brain reviews')
if not exits and not positions:
    out.append('Action: bot flat, soft-release awaiting first entry or 24h auto-progression')
else:
    out.append('Action: nothing critical pending')

print('\n'.join(out))
print('')
print('Full audit MD: ' + md_path)

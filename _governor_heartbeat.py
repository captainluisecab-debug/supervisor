"""Governor heartbeat — refreshes kraken_cmd.json every 5 min.

The full supervisor_governor.py is a long-running service that may not be
active in this environment. The engine treats kraken_cmd.json as stale
after 10 min (engine.py:1081), reverting to safe defaults (no entry).

This heartbeat acts as a minimal governor: writes kraken_cmd.json with
fresh ts and the operator-approved current posture, so the bot's trader
can fire entries within its lane.

Operator policy 2026-04-29: TRENDING_DOWN regime relaxed to SCOUT
(was FLAT). Trader's classifier owns per-cycle decisions; governor
is now a mostly-passive safety envelope.

Sensitivity: 8/10 (writes governor authority file). Operator-approved.
"""
import json
import os
from datetime import datetime, timezone

CMD_PATH = r'C:\Projects\supervisor\commands\kraken_cmd.json'


def write_command(mode='SCOUT', size_mult=0.3, entry_allowed=True,
                  force_flatten=False, dominant_regime='TRENDING_DOWN',
                  reasoning='Operator-relaxed governor: TRENDING_DOWN -> SCOUT (counter-trend allowed)',
                  trend_phase='proven', trend_phase_hours=0.0, max_positions=2):
    payload = {
        'mode': mode,
        'size_mult': float(size_mult),
        'entry_allowed': bool(entry_allowed),
        'force_flatten': bool(force_flatten),
        'reasoning': reasoning,
        'bot': 'kraken',
        'ts': datetime.now(timezone.utc).isoformat(),
        'source': 'operator_override',
        'dominant_regime': dominant_regime,
        'trend_phase': trend_phase,
        'trend_phase_hours': float(trend_phase_hours),
        'max_positions': int(max_positions),
    }
    os.makedirs(os.path.dirname(CMD_PATH), exist_ok=True)
    tmp = CMD_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, CMD_PATH)
    return payload


if __name__ == '__main__':
    p = write_command()
    print('governor heartbeat wrote:', CMD_PATH)
    print('  mode:', p['mode'])
    print('  entry_allowed:', p['entry_allowed'])
    print('  force_flatten:', p['force_flatten'])
    print('  size_mult:', p['size_mult'])
    print('  ts:', p['ts'])

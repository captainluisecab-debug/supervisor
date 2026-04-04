"""
command_snapshots.py — Timestamped command file snapshot archive.

Every supervisor cycle, Governor writes command files. This module snapshots
the command state to a rolling JSONL archive so reconciliation can match
executions against the command state that existed at the time of execution,
not the current live file.

Storage: disk-backed JSONL, bounded to last 2000 entries (~7 days at 5min cycles).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SNAPSHOT_FILE = os.path.join(BASE_DIR, "command_snapshots.jsonl")
MAX_SNAPSHOTS = 2000  # ~7 days at 5min cycles

_SLEEVE_CMD_PATHS = {
    "kraken": os.path.join(BASE_DIR, "commands", "kraken_cmd.json"),
    "sfm": os.path.join(BASE_DIR, "commands", "sfm_cmd.json"),
    "alpaca": os.path.join(BASE_DIR, "commands", "alpaca_cmd.json"),
}


def snapshot_commands(cycle: int):
    """Capture timestamped snapshot of all 3 command files. Called once per cycle."""
    now_iso = datetime.now(timezone.utc).isoformat()
    for sleeve, path in _SLEEVE_CMD_PATHS.items():
        try:
            with open(path, encoding="utf-8") as f:
                cmd = json.load(f)
            record = {
                "snapshot_ts": now_iso,
                "cycle": cycle,
                "sleeve": sleeve,
                "source": cmd.get("source"),
                "mode": cmd.get("mode"),
                "entry_allowed": cmd.get("entry_allowed"),
                "force_flatten": cmd.get("force_flatten"),
                "reasoning": (cmd.get("reasoning") or "")[:80],
                "cmd_ts": cmd.get("ts"),
            }
            with open(SNAPSHOT_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception:
            pass

    # Bounded trim (only check occasionally to avoid I/O every cycle)
    if cycle % 50 == 0:
        _trim_snapshots()


def _trim_snapshots():
    """Keep only the last MAX_SNAPSHOTS entries."""
    try:
        with open(SNAPSHOT_FILE, encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) > MAX_SNAPSHOTS:
            with open(SNAPSHOT_FILE, "w", encoding="utf-8") as f:
                f.writelines(lines[-MAX_SNAPSHOTS:])
    except Exception:
        pass


def find_command_at_time(sleeve: str, exec_ts: str) -> dict | None:
    """Find the command snapshot closest to (but not after) the execution timestamp."""
    try:
        with open(SNAPSHOT_FILE, encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return None

    best = None
    for line in reversed(lines):
        try:
            snap = json.loads(line)
            if snap.get("sleeve") != sleeve:
                continue
            if snap.get("snapshot_ts", "") <= exec_ts:
                best = snap
                break
        except Exception:
            continue
    return best


def load_snapshots_window(hours: int = 24) -> list:
    """Load all snapshots within the last N hours."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    try:
        with open(SNAPSHOT_FILE, encoding="utf-8") as f:
            lines = f.readlines()
        return [json.loads(l) for l in lines if l.strip() and json.loads(l).get("snapshot_ts", "") >= cutoff]
    except Exception:
        return []

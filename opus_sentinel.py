"""
opus_sentinel.py — Autonomous watcher that detects system events requiring
attention and (in active mode) applies in-allowlist remediations.

Shadow mode (default): logs decisions to opus_sentinel_audit.jsonl.
                       No writes to override / cmd / state files.
Active mode:           applies in-allowlist param changes to
                       supervisor_override.json; files out-of-allowlist
                       escalations to issues.jsonl.

Kill switch: OPUS_SENTINEL_PAUSE.txt in BASE_DIR → all writes off.

Triggers currently enabled (3):
  B1  kernel_halt_persistent       - kernel HALT for 3+ consecutive cycles
  B5  brain_daily_loss_trigger     - brain fires daily_loss_pct trigger
  B8  stale_cmd                    - any cmd file >10m without update

More triggers queued for expansion after shadow validation.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s][SENTINEL] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("opus_sentinel")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENZOBOT_DIR = r"C:\Projects\enzobot"
ALPACA_DIR = r"C:\Projects\alpacabot"

# Input files we read (authoritative state, never cmd files for truth)
KERNEL_AUDIT_FILE = os.path.join(BASE_DIR, "kernel_audit.jsonl")
CMD_KRAKEN = os.path.join(BASE_DIR, "commands", "kraken_cmd.json")
CMD_SFM = os.path.join(BASE_DIR, "commands", "sfm_cmd.json")
CMD_ALPACA = os.path.join(BASE_DIR, "commands", "alpaca_cmd.json")
ENZOBOT_BRAIN_DECISIONS = os.path.join(ENZOBOT_DIR, "brain_decisions.jsonl")

# Output files
AUDIT_FILE = os.path.join(BASE_DIR, "opus_sentinel_audit.jsonl")
ISSUES_FILE = r"C:\Projects\memory\openclaw\openclaw_workspace\issues.jsonl"

# Kill switches
PAUSE_FILE = os.path.join(BASE_DIR, "OPUS_SENTINEL_PAUSE.txt")
ACTIVE_FILE = os.path.join(BASE_DIR, "OPUS_SENTINEL_ACTIVE.txt")  # presence => active, absence => shadow

CHECK_INTERVAL_SEC = 120  # 2 min cycle

# Dedup memory: trigger_key → last_fire_ts
_dedup: Dict[str, float] = {}

# Dedup windows per trigger (seconds)
DEDUP_WINDOWS = {
    "B1_kernel_halt_persistent": 3600,  # 60 min
    "B5_brain_daily_loss": 43200,       # 12 hours (resets near midnight)
    "B8_stale_cmd": 1800,               # 30 min per cmd file
}


def _is_active_mode() -> bool:
    """Active mode requires explicit ACTIVE flag file AND no PAUSE file."""
    if os.path.exists(PAUSE_FILE):
        return False
    return os.path.exists(ACTIVE_FILE)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_jsonl_tail(path: str, n: int = 10) -> list:
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        return [json.loads(ln) for ln in lines[-n:] if ln.strip()]
    except Exception:
        return []


def _read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _file_age_sec(path: str) -> float:
    try:
        return time.time() - os.path.getmtime(path)
    except Exception:
        return 1e9


def _should_fire(trigger_key: str) -> bool:
    """Dedup check: only fire if outside the dedup window for this trigger."""
    window = DEDUP_WINDOWS.get(trigger_key, 3600)
    last = _dedup.get(trigger_key, 0.0)
    if time.time() - last < window:
        return False
    _dedup[trigger_key] = time.time()
    return True


def _write_audit(entry: dict) -> None:
    """Append an audit entry. Always writes (shadow or active)."""
    entry.setdefault("ts", _now_iso())
    entry.setdefault("mode", "ACTIVE" if _is_active_mode() else "SHADOW")
    try:
        with open(AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as exc:
        log.error("audit write failed: %s", exc)


# ──────────────────────────────────────────────────────────────────────
# Triggers
# ──────────────────────────────────────────────────────────────────────

def check_b1_kernel_halt_persistent() -> Optional[dict]:
    """B1: kernel HALT for 3+ consecutive cycles with same violation."""
    tail = _read_jsonl_tail(KERNEL_AUDIT_FILE, 5)
    if len(tail) < 3:
        return None
    last3 = tail[-3:]
    if not all(e.get("status") == "HALT" for e in last3):
        return None
    # Same violation across all 3?
    vsets = [tuple(e.get("violations", [])) for e in last3]
    if len(set(vsets)) != 1:
        return None
    if not _should_fire("B1_kernel_halt_persistent"):
        return None
    return {
        "trigger": "B1_kernel_halt_persistent",
        "detail": {
            "violations": list(last3[-1].get("violations", [])),
            "cycles": [e.get("cycle") for e in last3],
        },
        "proposed_action": "classify_and_escalate",
        "rationale": "Kernel HALT persists 3+ cycles on the same invariant. Likely root cause is either stale state (needs reconcile) or a real metric breach (needs strategy adjustment).",
    }


def check_b5_brain_daily_loss() -> Optional[dict]:
    """B5: brain reasoning mentions daily_loss trigger."""
    decisions = _read_jsonl_tail(ENZOBOT_BRAIN_DECISIONS, 5)
    if not decisions:
        return None
    last = decisions[-1]
    reasoning = str(last.get("reasoning", "")).lower()
    if "daily_loss" not in reasoning:
        return None
    if not _should_fire("B5_brain_daily_loss"):
        return None
    return {
        "trigger": "B5_brain_daily_loss",
        "detail": {
            "brain_mode": last.get("final_mode"),
            "reasoning": last.get("reasoning"),
            "cycle": last.get("cycle"),
        },
        "proposed_action": "observe_only_until_next_window",
        "rationale": "Brain self-triggered DEFEND on daily_loss. This is the existing capital-protection path working as designed. Sentinel confirms detection; no param change needed.",
    }


def check_b8_stale_cmd() -> Optional[Dict[str, Any]]:
    """B8: any cmd file older than 10 minutes."""
    stale = []
    for name, path in [("kraken", CMD_KRAKEN), ("sfm", CMD_SFM), ("alpaca", CMD_ALPACA)]:
        age = _file_age_sec(path)
        if age > 600:
            stale.append({"sleeve": name, "age_min": round(age / 60.0, 1)})
    if not stale:
        return None
    # Dedup per unique set of stale sleeves
    key = "B8_stale_cmd_" + "_".join(sorted(s["sleeve"] for s in stale))
    DEDUP_WINDOWS[key] = 1800
    if not _should_fire(key):
        return None
    return {
        "trigger": "B8_stale_cmd",
        "detail": {"stale_sleeves": stale},
        "proposed_action": "escalate_to_operator_at_next_window",
        "rationale": (
            "Supervisor cmd file is stale. F1 stale-cmd safety on bot side "
            "already blocks new entries from stale cmd. Root cause is "
            "supervisor/governor not writing — likely kernel HALT or "
            "governor process issue. Investigation required."
        ),
    }


TRIGGERS = [
    check_b1_kernel_halt_persistent,
    check_b5_brain_daily_loss,
    check_b8_stale_cmd,
]


# ──────────────────────────────────────────────────────────────────────
# Main cycle
# ──────────────────────────────────────────────────────────────────────

def run_cycle() -> None:
    """One sentinel cycle. Runs every CHECK_INTERVAL_SEC."""
    active = _is_active_mode()
    fired_count = 0
    for trigger_fn in TRIGGERS:
        try:
            result = trigger_fn()
        except Exception as exc:
            log.error("trigger %s failed: %s", trigger_fn.__name__, exc)
            continue
        if not result:
            continue
        fired_count += 1
        entry = {
            "trigger": result["trigger"],
            "detail": result["detail"],
            "proposed_action": result["proposed_action"],
            "rationale": result["rationale"],
            "active_mode": active,
            "action_taken": None,  # populated below
        }
        # Shadow mode: log only
        if not active:
            entry["action_taken"] = "NONE (shadow mode)"
            log.info("TRIGGER [SHADOW] %s: %s",
                     result["trigger"], result["rationale"])
        else:
            # Active mode: for MVP, still log-only. Real write logic lands
            # after shadow validation per operator approval.
            entry["action_taken"] = "NONE (active-mode writes not yet enabled)"
            log.warning("TRIGGER [ACTIVE] %s: %s — WRITE PATHS NOT YET WIRED",
                        result["trigger"], result["rationale"])
        _write_audit(entry)
    if fired_count == 0:
        log.info("cycle clean — no triggers")


def main() -> None:
    log.info("=" * 60)
    log.info("OPUS SENTINEL — autonomous watcher")
    log.info("Mode: %s", "ACTIVE" if _is_active_mode() else "SHADOW")
    log.info("Triggers: %d enabled", len(TRIGGERS))
    log.info("Cycle: %ds", CHECK_INTERVAL_SEC)
    log.info("Audit: %s", AUDIT_FILE)
    log.info("=" * 60)
    while True:
        try:
            run_cycle()
        except Exception as exc:
            log.error("cycle error: %s", exc, exc_info=True)
        time.sleep(CHECK_INTERVAL_SEC)


if __name__ == "__main__":
    main()

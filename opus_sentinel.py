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

# Autonomy guard — pre-write safety checks + post-write outcome attribution
try:
    from autonomy_guard import pre_write_check as _ag_pre_write_check
    from autonomy_guard import record_write as _ag_record_write
except Exception as _ag_exc:
    logging.getLogger("opus_sentinel").warning(
        "autonomy_guard import failed, guards disabled: %s", _ag_exc)
    _ag_pre_write_check = None
    _ag_record_write = None
ENZOBOT_DIR = r"C:\Projects\enzobot"
ALPACA_DIR = r"C:\Projects\alpacabot"
SFMBOT_DIR = r"C:\Projects\sfmbot"

# Input files we read (authoritative state, never cmd files for truth)
KERNEL_AUDIT_FILE = os.path.join(BASE_DIR, "kernel_audit.jsonl")
CMD_KRAKEN = os.path.join(BASE_DIR, "commands", "kraken_cmd.json")
CMD_SFM = os.path.join(BASE_DIR, "commands", "sfm_cmd.json")
CMD_ALPACA = os.path.join(BASE_DIR, "commands", "alpaca_cmd.json")
ENZOBOT_BRAIN_DECISIONS = os.path.join(ENZOBOT_DIR, "brain_decisions.jsonl")
ENZOBOT_EXIT_LOG = os.path.join(ENZOBOT_DIR, "logs", "exit_counterfactuals.jsonl")
ENZOBOT_SERVICE_LOG = os.path.join(ENZOBOT_DIR, "logs", "service.log")
ENZOBOT_STATE = os.path.join(ENZOBOT_DIR, "state.json")
ENZOBOT_FEEDBACK = os.path.join(ENZOBOT_DIR, "supervisor_feedback.json")
ENZOBOT_POLICY = os.path.join(ENZOBOT_DIR, "policy.json")
ENZOBOT_SENTINEL_OVERRIDE = os.path.join(ENZOBOT_DIR, "sentinel_override.json")

# Output files
AUDIT_FILE = os.path.join(BASE_DIR, "opus_sentinel_audit.jsonl")
ISSUES_FILE = r"C:\Projects\memory\openclaw\openclaw_workspace\issues.jsonl"

# Kill switches
PAUSE_FILE = os.path.join(BASE_DIR, "OPUS_SENTINEL_PAUSE.txt")
ACTIVE_FILE = os.path.join(BASE_DIR, "OPUS_SENTINEL_ACTIVE.txt")

CHECK_INTERVAL_SEC = 120  # 2 min cycle
SERVICE_LOG_TAIL_LINES = 500  # how many recent lines to scan per cycle

# Dedup memory: trigger_key → last_fire_ts
_dedup: Dict[str, float] = {}

# Cross-cycle counters for triggers that need persistence
_regime_disagreement_count: Dict[str, int] = {"kraken": 0, "sfm": 0, "alpaca": 0}

# Dedup windows per trigger (seconds)
DEDUP_WINDOWS = {
    "B1_kernel_halt_persistent": 3600,          # 60 min
    "B2_expectancy_below_floor": 7200,          # 2 hr
    "B3_fill_failures_same_pair": 3600,         # 60 min, per-pair suffixed
    "B4_same_pair_churn": 21600,                # 6 hr, per-pair suffixed
    "B5_brain_daily_loss": 43200,               # 12 hr
    "B6_no_profit_12h": 14400,                  # 4 hr (re-alert if still no profit)
    "B7_regime_disagreement": 3600,             # 60 min, per-sleeve suffixed
    "B8_stale_cmd": 1800,                       # 30 min, per-sleeve suffixed
    "B9_orphan_position": 3600,                 # 60 min
    "B10_phantom_fill": 86400,                  # 24 hr — must always escalate
    "B11_allowlist_miss": 86400,                # 24 hr per-param suffixed
    "B12_loss_streak_universe": 7200,           # 2 hr (matches TTL of action)
}

# B12 threshold: how many consecutive losses universe-wide triggers the pause.
# Includes governor_force_flatten (force-flat-at-loss is still a real loss signal).
B12_LOSS_STREAK_THRESHOLD = 5


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


def _read_log_tail(path: str, n: int = SERVICE_LOG_TAIL_LINES) -> list:
    """Read last n lines of a text log. Returns list of strings."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.readlines()[-n:]
    except Exception:
        return []


def _parse_log_ts(line: str) -> Optional[float]:
    """Parse enzobot log line timestamp like '[2026-04-23 12:34:56,789]' or
    service.log style '[12:34:56]'. Returns epoch seconds or None."""
    # Full ISO: [YYYY-MM-DD HH:MM:SS,ms]
    if line.startswith("[20"):
        try:
            ts_str = line[1:20]  # "2026-04-23 12:34:56"
            dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
            return dt.timestamp()
        except Exception:
            pass
    # Short service.log: [HH:MM:SS]
    if line.startswith("[") and len(line) >= 11 and line[9] == "]":
        try:
            hh, mm, ss = line[1:9].split(":")
            now = datetime.now()
            dt = now.replace(hour=int(hh), minute=int(mm), second=int(ss), microsecond=0)
            return dt.timestamp()
        except Exception:
            pass
    return None


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


def check_b2_expectancy_below_floor() -> Optional[dict]:
    """B2: rolling expectancy from exit_counterfactuals.jsonl below -5.0
    for 3 consecutive sentinel checks. Uses same math as kernel INV-4
    (last 20 trading exits, recency-weighted) but different threshold
    (-5.0 vs kernel's -3.5) so sentinel fires on deeper breaches that
    would otherwise keep kernel HALTing silently."""
    import math
    lines = _read_jsonl_tail(ENZOBOT_EXIT_LOG, 60)
    trading = [e for e in lines
               if isinstance(e, dict)
               and e.get("type") == "exit"
               and e.get("exit_reason") != "governor_force_flatten"]
    if len(trading) < 10:
        return None
    recent = trading[-20:]
    decay = math.log(2) / 10
    tw = 0.0
    wpnl = 0.0
    for i, e in enumerate(recent):
        age = len(recent) - 1 - i
        w = math.exp(-decay * age)
        wpnl += float(e.get("pnl_usd", 0) or 0) * w
        tw += w
    expectancy = wpnl / tw if tw > 0 else 0.0
    if expectancy > -5.0:
        _regime_disagreement_count["_b2"] = 0
        return None
    _regime_disagreement_count["_b2"] = _regime_disagreement_count.get("_b2", 0) + 1
    if _regime_disagreement_count["_b2"] < 3:
        return None
    if not _should_fire("B2_expectancy_below_floor"):
        return None
    return {
        "trigger": "B2_expectancy_below_floor",
        "detail": {"expectancy": round(expectancy, 3), "threshold": -5.0, "n_exits": len(recent)},
        "proposed_action": "escalate_to_operator_at_next_window",
        "rationale": (
            f"Rolling expectancy ({expectancy:.2f}) has been below -5.0 for 3+ "
            "sentinel cycles. Strategy is structurally losing beyond what kernel "
            "INV-4's -3.5 floor catches. Operator should review exit-quality "
            "patterns and consider tightening entry score or pulling affected pairs."
        ),
    }


def check_b3_fill_failures_same_pair() -> Optional[dict]:
    """B3: same pair has 3+ 'all N attempts failed' errors in last 60 min."""
    lines = _read_log_tail(ENZOBOT_SERVICE_LOG, 2000)
    import re
    pattern = re.compile(r"all \d+ attempts failed for (BUY|SELL) ([A-Z]+/[A-Z]+)")
    now = time.time()
    cutoff = now - 3600
    counts: Dict[str, int] = {}
    for ln in lines:
        ts = _parse_log_ts(ln)
        if ts is None or ts < cutoff:
            continue
        m = pattern.search(ln)
        if m:
            pair = m.group(2)
            counts[pair] = counts.get(pair, 0) + 1
    bad = [(p, c) for p, c in counts.items() if c >= 3]
    if not bad:
        return None
    pair, count = max(bad, key=lambda x: x[1])
    key = f"B3_fill_failures_same_pair_{pair}"
    DEDUP_WINDOWS[key] = 3600
    if not _should_fire(key):
        return None
    return {
        "trigger": "B3_fill_failures_same_pair",
        "detail": {"pair": pair, "failures_1h": count, "all_counts": counts},
        "proposed_action": "escalate_for_per_pair_offset_tuning_or_disable",
        "rationale": (
            f"{pair} has {count} 'all attempts failed' errors in the last hour. "
            "Likely pair-specific liquidity/offset mismatch (ISSUE-009 pattern). "
            "Operator should consider widening live_order_offset_pct for this "
            "pair OR enabling market fallback for its BUY side OR temporarily "
            "disabling the pair."
        ),
    }


def check_b4_same_pair_churn() -> Optional[dict]:
    """B4: same pair has 8+ FILL events (≥4 round-trips) in last 6h."""
    lines = _read_log_tail(ENZOBOT_SERVICE_LOG, 5000)
    import re
    pattern = re.compile(r"\[FILL\]\[(BUY|SELL)\] ([A-Z]+/[A-Z]+)")
    now = time.time()
    cutoff = now - 21600
    counts: Dict[str, int] = {}
    for ln in lines:
        ts = _parse_log_ts(ln)
        if ts is None or ts < cutoff:
            continue
        m = pattern.search(ln)
        if m:
            pair = m.group(2)
            counts[pair] = counts.get(pair, 0) + 1
    bad = [(p, c) for p, c in counts.items() if c >= 8]
    if not bad:
        return None
    pair, fills = max(bad, key=lambda x: x[1])
    key = f"B4_same_pair_churn_{pair}"
    DEDUP_WINDOWS[key] = 21600
    if not _should_fire(key):
        return None
    return {
        "trigger": "B4_same_pair_churn",
        "detail": {"pair": pair, "fills_6h": fills, "round_trips_approx": fills // 2,
                   "all_counts": counts},
        "proposed_action": "escalate_for_cooldown_increase_or_pair_cooldown",
        "rationale": (
            f"{pair} has {fills} FILL events ({fills // 2} round-trips) in last 6h. "
            "Classic chop-churn pattern. COOLDOWN=3600 already applied globally; "
            "this pair may need per-pair cooldown or temporary disable. "
            "Check if strategy is re-triggering on same noise pattern."
        ),
    }


def check_b6_no_profit_12h() -> Optional[dict]:
    """B6: zero profitable exits in last 12h despite activity (≥3 exits)."""
    lines = _read_jsonl_tail(ENZOBOT_EXIT_LOG, 100)
    trading = [e for e in lines
               if isinstance(e, dict)
               and e.get("type") == "exit"
               and e.get("exit_reason") != "governor_force_flatten"]
    cutoff = time.time() - 43200  # 12h
    recent = [e for e in trading if float(e.get("ts", 0) or 0) >= cutoff]
    if len(recent) < 3:
        return None
    wins = [e for e in recent if float(e.get("pnl_usd", 0) or 0) > 0]
    if wins:
        return None
    if not _should_fire("B6_no_profit_12h"):
        return None
    return {
        "trigger": "B6_no_profit_12h",
        "detail": {"exits_12h": len(recent), "wins_12h": 0,
                   "last_3_reasons": [e.get("exit_reason") for e in recent[-3:]]},
        "proposed_action": "escalate_strategy_review",
        "rationale": (
            f"Zero profitable exits across {len(recent)} trades in last 12h. "
            "Strategy is not producing wins. Either regime hostile to current "
            "entry signal, or exit logic is firing too early. Operator should "
            "review entry score quality and exit thresholds."
        ),
    }


def check_b7_regime_disagreement() -> Optional[dict]:
    """B7: brain mode != governor mode for 3 consecutive sentinel cycles, per sleeve."""
    decisions = _read_jsonl_tail(ENZOBOT_BRAIN_DECISIONS, 3)
    if not decisions:
        return None
    brain_mode = str(decisions[-1].get("final_mode", "")).upper()
    gov = _read_json(CMD_KRAKEN)
    gov_mode = str(gov.get("mode", "")).upper()
    # Collapse modes to a coarse "defensive vs trading"
    def _posture(m: str) -> str:
        if m in ("DEFEND", "DEFENSE", "FLAT"): return "DEFENSIVE"
        if m in ("ATTACK", "NORMAL", "TRADE", "TRADE_ACTIVE"): return "ACTIVE"
        return "NEUTRAL"
    brain_p = _posture(brain_mode)
    gov_p = _posture(gov_mode)
    if brain_p == gov_p or "NEUTRAL" in (brain_p, gov_p):
        _regime_disagreement_count["kraken"] = 0
        return None
    _regime_disagreement_count["kraken"] += 1
    if _regime_disagreement_count["kraken"] < 3:
        return None
    key = "B7_regime_disagreement_kraken"
    DEDUP_WINDOWS[key] = 3600
    if not _should_fire(key):
        return None
    return {
        "trigger": "B7_regime_disagreement",
        "detail": {"sleeve": "kraken", "brain_mode": brain_mode, "governor_mode": gov_mode,
                   "consecutive_cycles": _regime_disagreement_count["kraken"]},
        "proposed_action": "escalate_regime_source_audit",
        "rationale": (
            f"Kraken brain={brain_mode} vs governor={gov_mode} for 3+ cycles. "
            "Disagreement indicates either brain is ignoring fresh governor state "
            "or governor/brain are computing regime from different signals. "
            "Operator should reconcile brain vs governor regime inputs."
        ),
    }


def check_b9_orphan_position() -> Optional[dict]:
    """B9: reconcile detected position drift between state and exchange.
    Grep the run log for [RECONCILE] POSITION MISMATCH lines in last 60 min."""
    lines = _read_log_tail(ENZOBOT_SERVICE_LOG, 2000)
    now = time.time()
    cutoff = now - 3600
    mismatches = []
    for ln in lines:
        if "POSITION MISMATCH" not in ln and "DUST detected" not in ln:
            continue
        ts = _parse_log_ts(ln)
        if ts is None or ts < cutoff:
            continue
        mismatches.append(ln.strip())
    if not mismatches:
        return None
    if not _should_fire("B9_orphan_position"):
        return None
    return {
        "trigger": "B9_orphan_position",
        "detail": {"mismatch_count_1h": len(mismatches), "sample": mismatches[:3]},
        "proposed_action": "escalate_reconcile_audit",
        "rationale": (
            f"Reconcile detected {len(mismatches)} position mismatches in last hour. "
            "Either bot state is out of sync with Kraken (partial fills, manual "
            "operator trades, exchange settlement lag) OR dust accumulating. "
            "Operator should verify Kraken account vs bot state directly."
        ),
    }


def check_b10_phantom_fill() -> Optional[dict]:
    """B10: any FILL log line with px=0.00. Must always escalate -- this was
    the 2026-04-22 $176 phantom DOGE loss. ISSUE-011 fixed the root cause
    but sentinel provides belt-and-suspenders detection for any regression."""
    lines = _read_log_tail(ENZOBOT_SERVICE_LOG, 2000)
    now = time.time()
    cutoff = now - 86400  # 24h
    hits = []
    for ln in lines:
        if "[FILL]" not in ln:
            continue
        if "px=0.0" not in ln and "px=$0.0" not in ln:
            continue
        ts = _parse_log_ts(ln)
        if ts is None or ts < cutoff:
            continue
        hits.append(ln.strip())
    if not hits:
        return None
    if not _should_fire("B10_phantom_fill"):
        return None
    return {
        "trigger": "B10_phantom_fill",
        "detail": {"count_24h": len(hits), "sample": hits[:3]},
        "proposed_action": "escalate_immediately_phantom_regression",
        "rationale": (
            f"Detected {len(hits)} FILL lines with px=0.00 in last 24h. "
            "ISSUE-011 (_market_order polling fix) should prevent this -- "
            "recurrence indicates regression or new code path producing "
            "phantom fills. Operator should verify commit e78ea95 is live "
            "and investigate the specific fill context immediately."
        ),
    }


def check_b11_allowlist_miss() -> Optional[dict]:
    """B11: Opus recommended a param that isn't in brain's hard_bounds.
    After ISSUE-allowlist-expansion (commit 3c03aae) this should be near zero.
    Any recurrence means Opus has started recommending a NEW param class."""
    lines = _read_log_tail(ENZOBOT_SERVICE_LOG, 2000)
    import re
    pattern = re.compile(r"Opus recommended unknown param (\w+)")
    now = time.time()
    cutoff = now - 86400  # 24h
    unknown: Dict[str, int] = {}
    for ln in lines:
        ts = _parse_log_ts(ln)
        if ts is None or ts < cutoff:
            continue
        m = pattern.search(ln)
        if m:
            p = m.group(1)
            unknown[p] = unknown.get(p, 0) + 1
    if not unknown:
        return None
    # Dedup per-param so new miss classes surface individually
    fired_any = False
    detail = {"params": unknown}
    for param in unknown:
        key = f"B11_allowlist_miss_{param}"
        DEDUP_WINDOWS[key] = 86400
        if _should_fire(key):
            fired_any = True
    if not fired_any:
        return None
    return {
        "trigger": "B11_allowlist_miss",
        "detail": detail,
        "proposed_action": "escalate_for_hard_bounds_expansion",
        "rationale": (
            f"Opus recommending unknown param(s): {list(unknown.keys())}. "
            "Brain's validate() silently drops these because they're not in "
            "policy.json hard_bounds. Operator should evaluate whether to add "
            "the new param(s) to hard_bounds (extending autonomous tuning reach) "
            "or reject the class (Opus recommending out-of-scope params)."
        ),
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


def check_b12_loss_streak_universe() -> Optional[Dict[str, Any]]:
    """B12: N consecutive losses across any pair universe-wide.

    Catches the structural blind spot B6 misses: chronic bleed with low
    exit frequency (B6 requires >=3 exits in 12h) and B6's exclusion of
    governor_force_flatten. A force-flatten at a loss is still a real
    losing decision about the pair. We include it here by design.

    Fires on the transition FROM streak=N-1 TO streak=N. 2h TTL matches
    the override's TTL so we re-fire if the streak persists past the
    defensive window.
    """
    lines = _read_jsonl_tail(ENZOBOT_EXIT_LOG, 50)
    exits = [e for e in lines if isinstance(e, dict) and e.get("type") == "exit"]
    if len(exits) < B12_LOSS_STREAK_THRESHOLD:
        return None

    # Sort ascending by ts to find the latest consecutive-loss run.
    exits.sort(key=lambda e: float(e.get("ts", 0) or 0))

    # Walk from newest backward, counting consecutive negative-pnl exits.
    streak = 0
    streak_pairs = []
    for e in reversed(exits):
        pnl = float(e.get("pnl_usd", 0) or 0)
        if pnl < 0:
            streak += 1
            streak_pairs.append(e.get("pair", "?"))
        else:
            break  # streak broken by a win

    if streak < B12_LOSS_STREAK_THRESHOLD:
        return None

    if not _should_fire("B12_loss_streak_universe"):
        return None

    last_loss = list(reversed(exits))[0]
    last_pair = last_loss.get("pair", "")
    total_loss_usd = sum(
        float(e.get("pnl_usd", 0) or 0)
        for e in list(reversed(exits))[:streak]
    )

    return {
        "trigger": "B12_loss_streak_universe",
        "detail": {
            "streak": streak,
            "threshold": B12_LOSS_STREAK_THRESHOLD,
            "pairs_in_streak": streak_pairs[:10],
            "total_streak_pnl_usd": round(total_loss_usd, 2),
            "last_losing_pair": last_pair,
        },
        "proposed_action": "tighten_deploy_and_score_cooldown_last_pair",
        "rationale": (
            f"{streak} consecutive losing exits universe-wide "
            f"(threshold {B12_LOSS_STREAK_THRESHOLD}). Total streak PnL "
            f"${total_loss_usd:+.2f}. Current entry logic is not producing "
            f"wins — strategy misaligned with regime. Autonomous response: "
            f"reduce deployment to 0.25, raise MIN_SCORE_TO_TRADE to 88, "
            f"cooldown the last losing pair ({last_pair}) for 4h. 2h TTL "
            f"on the global override — auto-revert if streak breaks."
        ),
    }


TRIGGERS = [
    check_b1_kernel_halt_persistent,
    check_b2_expectancy_below_floor,
    check_b3_fill_failures_same_pair,
    check_b4_same_pair_churn,
    check_b5_brain_daily_loss,
    check_b6_no_profit_12h,
    check_b7_regime_disagreement,
    check_b8_stale_cmd,
    check_b9_orphan_position,
    check_b10_phantom_fill,
    check_b11_allowlist_miss,
    check_b12_loss_streak_universe,
]


# ──────────────────────────────────────────────────────────────────────
# Main cycle
# ──────────────────────────────────────────────────────────────────────

def _next_issue_id() -> str:
    """Generate next ISSUE-NNN id by reading existing issues.jsonl."""
    try:
        with open(ISSUES_FILE, encoding="utf-8") as f:
            lines = [ln for ln in f if ln.strip()]
        max_n = 0
        for ln in lines:
            try:
                iid = json.loads(ln).get("issue_id", "")
                if iid.startswith("ISSUE-"):
                    n = int(iid.split("-")[1])
                    if n > max_n:
                        max_n = n
            except Exception:
                continue
        return f"ISSUE-{max_n + 1:03d}"
    except Exception:
        return f"ISSUE-SENTINEL-{int(time.time())}"


# Trigger → issue template. Each trigger has a severity and reopen criteria
# so issues.jsonl records are consistent and auditable.
ISSUE_TEMPLATES = {
    "B1_kernel_halt_persistent": {
        "anomaly_type": "KERNEL_HALT_PERSISTENT",
        "severity": "HIGH",
        "reopen_criteria": [
            "Kernel HALT for 3+ consecutive cycles on the same invariant "
            "violation (indicates root cause not resolved by kernel skip alone)"
        ],
    },
    "B2_expectancy_below_floor": {
        "anomaly_type": "EXPECTANCY_STRUCTURAL_NEGATIVE",
        "severity": "HIGH",
        "reopen_criteria": [
            "Rolling 20-exit recency-weighted expectancy below -5.0 for 3+ sentinel cycles"
        ],
    },
    "B3_fill_failures_same_pair": {
        "anomaly_type": "FILL_RELIABILITY_PAIR_SPECIFIC",
        "severity": "MEDIUM",
        "reopen_criteria": [
            "3+ 'all attempts failed' errors for the same pair within 60 min"
        ],
    },
    "B4_same_pair_churn": {
        "anomaly_type": "SAME_PAIR_CHURN_EXCESSIVE",
        "severity": "MEDIUM",
        "reopen_criteria": [
            "8+ FILL events on same pair within 6h (≥4 round-trips despite COOLDOWN)"
        ],
    },
    "B5_brain_daily_loss": {
        "anomaly_type": "BRAIN_DAILY_LOSS_DEFEND",
        "severity": "MEDIUM",
        "reopen_criteria": [
            "Brain triggers daily_loss DEFEND more than 2x in same calendar day"
        ],
    },
    "B6_no_profit_12h": {
        "anomaly_type": "ZERO_PROFITABLE_EXITS_12H",
        "severity": "MEDIUM",
        "reopen_criteria": [
            "Zero winning exits across 3+ closed trades in any rolling 12h window"
        ],
    },
    "B7_regime_disagreement": {
        "anomaly_type": "BRAIN_GOVERNOR_REGIME_DISAGREEMENT",
        "severity": "MEDIUM",
        "reopen_criteria": [
            "Brain posture ≠ Governor posture on same sleeve for 3+ consecutive sentinel cycles"
        ],
    },
    "B8_stale_cmd": {
        "anomaly_type": "SUPERVISOR_CMD_STALE",
        "severity": "HIGH",
        "reopen_criteria": [
            "Any sleeve cmd file >10 min without refresh (governor skipped "
            "or supervisor process issue)"
        ],
    },
    "B9_orphan_position": {
        "anomaly_type": "RECONCILE_POSITION_MISMATCH",
        "severity": "HIGH",
        "reopen_criteria": [
            "Reconcile detects POSITION MISMATCH warning during periodic sync"
        ],
    },
    "B10_phantom_fill": {
        "anomaly_type": "PHANTOM_FILL_PX_ZERO",
        "severity": "CRITICAL",
        "reopen_criteria": [
            "Any FILL log line shows px=0.00 or equivalent (ISSUE-011 regression)"
        ],
    },
    "B11_allowlist_miss": {
        "anomaly_type": "OPUS_RECOMMENDATION_ALLOWLIST_MISS",
        "severity": "LOW",
        "reopen_criteria": [
            "Opus recommends a parameter not in policy.json hard_bounds "
            "(indicates new class of recommendation operator should evaluate)"
        ],
    },
    "B12_loss_streak_universe": {
        "anomaly_type": "LOSS_STREAK_UNIVERSE_WIDE",
        "severity": "MEDIUM",
        "reopen_criteria": [
            f"{B12_LOSS_STREAK_THRESHOLD}+ consecutive losing exits across "
            "any pairs (includes governor_force_flatten). Fires every 2h "
            "while streak persists; auto-closes when a winning exit breaks "
            "the streak."
        ],
    },
}


def _write_sentinel_override(changes: dict, reason: str, ttl_sec: int = 7200,
                              blocked_pairs: Optional[list] = None,
                              trigger: str = "",
                              bot: str = "kraken") -> bool:
    """Write sentinel_override.json at enzobot side. Engine layers this on
    top of Brain's supervisor_override.json (sentinel wins when both fire).
    TTL ensures the override self-expires if sentinel stops writing.

    All writes go through autonomy_guard.pre_write_check — rate-limit,
    oscillation, regime stability, attribution, circuit-breaker freezes.
    """
    # Load policy bounds for validation — same bounds brain uses
    policy = _read_json(ENZOBOT_POLICY)
    bounds = policy.get("hard_bounds", {})

    validated = {}
    before_values = {}
    for k, v in (changes or {}).items():
        if k not in bounds:
            log.warning("sentinel override skipped %s=%s (not in hard_bounds)", k, v)
            continue
        try:
            lo, hi = bounds[k]
            clamped = max(lo, min(hi, v))
            validated[k] = clamped
            if clamped != v:
                log.info("sentinel override clamped %s: %s -> %s (bounds %s)",
                         k, v, clamped, bounds[k])
        except Exception as exc:
            log.warning("sentinel override skipped %s: bounds err %s", k, exc)

    if not validated and not blocked_pairs:
        return False

    # Read current live values (for before-state attribution)
    # state.json field names across sleeves:
    #   enzobot: cash, equity_peak, realized_pnl (no direct equity_usd)
    #   derived equity ≈ cash + open position value (approximate via equity_peak)
    try:
        _state = _read_json(ENZOBOT_STATE) or {}
        _equity = float(
            _state.get("equity_usd")
            or _state.get("portfolio_equity_usd")
            or _state.get("equity_peak")
            or _state.get("cash")
            or 0.0
        )
        _realized_pnl = float(
            _state.get("realized_pnl_usd")
            or _state.get("realized_pnl")
            or 0.0
        )
        _regime = None
        _feedback = _read_json(ENZOBOT_FEEDBACK) or {}
        _regime = _feedback.get("regime") or _feedback.get("dominant_regime")
    except Exception:
        _equity, _realized_pnl, _regime = 0.0, 0.0, None

    # For attribution in autonomy_guard: treat sentinel emergency triggers
    # (B2/B4/B6/B12) as attribution-bypass — they must be allowed to co-fire.
    # B12 writes pair_status + 2 sentinel_override params as one unit; without
    # bypass, attribution_clear blocks params 2 and 3 after pair_status lands.
    _bypass_attr = trigger in ("B2_expectancy_below_floor", "B4_same_pair_churn",
                               "B6_no_profit_12h", "B12_loss_streak_universe")

    # Pre-write check (rate limit, freeze, oscillation, etc.) — run per param
    allowed = {}
    for k, new_v in validated.items():
        before_values[k] = None  # not cheap to resolve from state.json; best-effort
        if _ag_pre_write_check is not None:
            try:
                ok, why = _ag_pre_write_check(
                    bot=bot, param=k, before=0.0, after=float(new_v),
                    hypothesis=f"{trigger}: {reason}",
                    expected_impact_usd=abs(_equity) * 0.001,  # ~10bps of equity
                    equity_usd=_equity,
                    regime=_regime,
                    trigger=trigger,
                    bypass_attribution=_bypass_attr,
                )
            except Exception as exc:
                log.warning("autonomy_guard pre_write_check raised: %s — allowing", exc)
                ok, why = True, "guard_err"
            if not ok:
                log.warning("SENTINEL_OVERRIDE BLOCKED param=%s: %s", k, why)
                continue
        allowed[k] = new_v

    if not allowed and not blocked_pairs:
        log.warning("sentinel override: all params blocked by autonomy_guard; no write")
        return False

    payload = {
        "ts": _now_iso(),
        "ttl_expiry": datetime.fromtimestamp(time.time() + ttl_sec, timezone.utc).isoformat(),
        "reason": reason,
        "source": "opus_sentinel",
        "trigger": trigger,
        "changes": allowed,
        "blocked_pairs": sorted(set(blocked_pairs or [])),
    }
    try:
        tmp = ENZOBOT_SENTINEL_OVERRIDE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, ENZOBOT_SENTINEL_OVERRIDE)
        log.warning("SENTINEL_OVERRIDE WRITTEN: %s (ttl %ds)", allowed or blocked_pairs, ttl_sec)
    except Exception as exc:
        log.error("sentinel override write failed: %s", exc)
        return False

    # Post-write record per changed param (for outcome attribution)
    if _ag_record_write is not None:
        for k, new_v in allowed.items():
            try:
                _ag_record_write(
                    bot=bot, param=k, before=0.0, after=float(new_v),
                    hypothesis=f"{trigger}: {reason}",
                    expected_impact_usd=abs(_equity) * 0.001,
                    equity_usd=_equity,
                    regime=_regime,
                    trigger=trigger,
                    realized_pnl_t0=_realized_pnl,
                    ttl_sec=ttl_sec,
                )
            except Exception as exc:
                log.warning("autonomy_guard record_write failed: %s", exc)

    return True


ENZOBOT_PAIR_STATUS = os.path.join(ENZOBOT_DIR, "pair_status.json")


def _write_pair_status(pair: str, status: str, ttl_sec: int,
                       reason: str, size_multiplier: float = 0.0,
                       trigger: str = "") -> bool:
    """Write/update a single pair in pair_status.json. TTL-bounded; engine
    auto-reverts expired rows by ignoring them.
    """
    current = _read_json(ENZOBOT_PAIR_STATUS) or {}
    meta = current.pop("_meta", {})
    ttl_ts = datetime.fromtimestamp(time.time() + ttl_sec, timezone.utc).isoformat()
    current[pair] = {
        "status": status,
        "size_multiplier": float(size_multiplier),
        "ttl_ts": ttl_ts,
        "reason": reason,
        "trigger": trigger,
        "set_at": _now_iso(),
    }
    meta["last_update"] = _now_iso()
    current["_meta"] = meta
    try:
        tmp = ENZOBOT_PAIR_STATUS + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2, default=str)
        os.replace(tmp, ENZOBOT_PAIR_STATUS)
        log.warning("PAIR_STATUS WRITTEN: %s=%s (ttl %dh) reason=%s",
                    pair, status, ttl_sec // 3600, reason)
        if _ag_record_write is not None:
            try:
                _ag_record_write(
                    bot="kraken", param=f"pair_status:{pair}",
                    before=1.0, after=float(size_multiplier),
                    hypothesis=f"{trigger}: {reason}",
                    expected_impact_usd=20.0,  # bleed-stopper, conservative estimate
                    equity_usd=0.0,
                    regime=None,
                    trigger=trigger,
                    realized_pnl_t0=None,
                    ttl_sec=ttl_sec,
                )
            except Exception:
                pass
        return True
    except Exception as exc:
        log.error("pair_status write failed: %s", exc)
        return False


def _file_issue(trigger_key: str, trigger_result: dict) -> Optional[str]:
    """Append a structured issue to issues.jsonl. Returns issue_id or None."""
    template = ISSUE_TEMPLATES.get(trigger_key, {})
    iid = _next_issue_id()
    issue = {
        "issue_id": iid,
        "anomaly_type": template.get("anomaly_type", "SENTINEL_UNCLASSIFIED"),
        "opened_at": _now_iso(),
        "classification": "open",
        "issue_state": "auto_detected",
        "owner": "opus_sentinel",
        "source": "opus_sentinel",
        "auto_filed": True,
        "severity": template.get("severity", "MEDIUM"),
        "trigger": trigger_key,
        "evidence_summary": trigger_result.get("rationale", ""),
        "evidence_detail": trigger_result.get("detail", {}),
        "proposed_action": trigger_result.get("proposed_action", ""),
        "reopen_criteria": template.get("reopen_criteria", []),
        "reopen_criteria_matched": [],
        "validation_status": "pending_operator_review",
        "closed_at": None,
    }
    try:
        with open(ISSUES_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(issue) + "\n")
        log.info("ISSUE FILED: %s (%s)", iid, trigger_key)
        return iid
    except Exception as exc:
        log.error("issue file failed: %s", exc)
        return None


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
            "action_taken": None,
            "issue_id": None,
        }
        if not active:
            entry["action_taken"] = "NONE (shadow mode)"
            log.info("TRIGGER [SHADOW] %s: %s",
                     result["trigger"], result["rationale"])
        else:
            # Active mode: file an issue (escalation trail), AND for a
            # narrow set of triggers where the remediation is safe and
            # within policy.json hard_bounds, write a sentinel_override
            # that engine layers on top of brain's override. 2h TTL.
            # All other triggers stay escalation-only.
            iid = _file_issue(result["trigger"], result)
            entry["issue_id"] = iid
            override_applied = False

            trigger_key = result["trigger"]
            if trigger_key == "B2_expectancy_below_floor":
                # Reduce deployment to cap blast radius while expectancy is bad
                override_applied = _write_sentinel_override(
                    changes={"TARGET_DEPLOY_PCT": 0.25},
                    reason=f"B2 autonomous: expectancy {result['detail'].get('expectancy')} below floor",
                    ttl_sec=7200,
                    trigger=trigger_key,
                )
            elif trigger_key == "B4_same_pair_churn":
                # Pair-level COOLDOWN via pair_status.json, plus global cooldown bump.
                bad_pair = result["detail"].get("pair")
                if bad_pair:
                    _write_pair_status(
                        pair=bad_pair, status="COOLDOWN",
                        ttl_sec=14400,  # 4h
                        reason="B4: same-pair churn / consecutive losses",
                        size_multiplier=0.0,
                        trigger=trigger_key,
                    )
                override_applied = _write_sentinel_override(
                    changes={"COOLDOWN_SEC": 5400},  # within [300, 7200]
                    reason=f"B4 autonomous: {bad_pair} COOLDOWN 4h + global cooldown up",
                    ttl_sec=21600,
                    blocked_pairs=[bad_pair] if bad_pair else None,
                    trigger=trigger_key,
                )
            elif trigger_key == "B6_no_profit_12h":
                # Tighten entry gate to only high-conviction signals
                override_applied = _write_sentinel_override(
                    changes={"MIN_SCORE_TO_TRADE": 88.0},
                    reason="B6 autonomous: no wins 12h, require higher score",
                    ttl_sec=14400,
                    trigger=trigger_key,
                )
            elif trigger_key == "B12_loss_streak_universe":
                # Loss-streak pause: tighten deploy, raise entry bar, pair cooldown
                detail = result.get("detail", {}) or {}
                last_pair = detail.get("last_losing_pair", "")
                streak = detail.get("streak", 0)
                if last_pair:
                    _write_pair_status(
                        pair=last_pair, status="COOLDOWN",
                        ttl_sec=14400,  # 4h
                        reason=f"B12: {streak}-loss streak, last losing pair",
                        size_multiplier=0.0,
                        trigger=trigger_key,
                    )
                override_applied = _write_sentinel_override(
                    changes={
                        "TARGET_DEPLOY_PCT": 0.25,
                        "MIN_SCORE_TO_TRADE": 88.0,
                    },
                    reason=(
                        f"B12 autonomous: {streak}-loss streak "
                        f"(total ${detail.get('total_streak_pnl_usd', 0):+.2f}) "
                        f"→ deploy=0.25, score>=88, {last_pair} COOLDOWN 4h"
                    ),
                    ttl_sec=7200,  # 2h
                    trigger=trigger_key,
                )

            actions = []
            if iid:
                actions.append(f"ISSUE_FILED:{iid}")
            if override_applied:
                actions.append("PARAM_APPLIED")
            entry["action_taken"] = " + ".join(actions) if actions else "NONE"
            log.warning("TRIGGER [ACTIVE] %s → %s: %s",
                        result["trigger"], entry["action_taken"], result["rationale"])
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

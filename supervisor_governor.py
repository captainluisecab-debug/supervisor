"""
supervisor_governor.py — Local deterministic governor for the bot universe.

Runs every supervisor cycle. Reads bot states, computes 6 core metrics,
takes automatic tightening actions (or logs shadow decisions), and triggers
Opus escalation only at defined gates.

PHASE 1: Shadow mode. All decisions logged to governor_decisions.jsonl.
No live command file writes. Set SHADOW_MODE = False to enable live authority.

Metrics:
  1. Rolling 20-exit expectancy (per sleeve)
  2. DD rate (change per hour)
  3. Exits in last hour
  4. Time since last profitable exit
  5. Regime consistency (flip count in last 4h)
  6. Cash deployment %
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import List, Optional, Dict

log = logging.getLogger("governor")

# ── Config ────────────────────────────────────────────────────────────
SHADOW_MODE = True  # True = log only, False = live authority

BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
DECISIONS_FILE = os.path.join(BASE_DIR, "governor_decisions.jsonl")

# Bot directories
ENZOBOT_DIR = r"C:\Projects\enzobot"
SFMBOT_DIR  = r"C:\Projects\sfmbot"
ALPACA_DIR  = r"C:\Projects\alpacabot"

# Thresholds
EXPECTANCY_FREEZE_THRESHOLD  = -1.0   # freeze entries if rolling expectancy < this
DD_ACCEL_THRESHOLD_PER_HOUR  = 0.5    # force DEFENSE if DD worsens > 0.5%/hour
CHURN_EXIT_LIMIT_PER_HOUR    = 3      # churn detected if > 3 exits in 1 hour
PAIR_CONSEC_LOSS_LIMIT       = 3      # block pair after 3 consecutive losses
PROFIT_PROTECT_THRESHOLD_PCT = 2.0    # tighten trails when unrealized > 2%
NO_WIN_ALERT_HOURS           = 24     # alert if no profitable exit in 24h

# ── State ─────────────────────────────────────────────────────────────
_equity_history: List[tuple] = []  # [(ts, equity), ...]
_exit_history: List[dict] = []     # recent exits from fills
_last_governor_ts: float = 0


# ── Data readers ──────────────────────────────────────────────────────

def _read_json(path: str) -> dict:
    try:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _read_jsonl_tail(path: str, n: int = 50) -> List[dict]:
    """Read last N lines of a JSONL file."""
    results = []
    try:
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines[-n:]:
            line = line.strip()
            if line:
                try:
                    results.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        pass
    return results


def _read_enzobot_state() -> dict:
    """Read Enzobot portfolio and feedback state."""
    feedback = _read_json(os.path.join(ENZOBOT_DIR, "supervisor_feedback.json"))
    state = _read_json(os.path.join(ENZOBOT_DIR, "state.json"))
    brain = _read_json(os.path.join(ENZOBOT_DIR, "brain_state.json"))
    return {
        "sleeve": "kraken",
        "equity": feedback.get("portfolio", {}).get("equity", 0),
        "dd_pct": feedback.get("portfolio", {}).get("dd_pct", 0),
        "cash": feedback.get("portfolio", {}).get("cash", 0),
        "open_positions": feedback.get("portfolio", {}).get("open_positions", 0),
        "pair_regime": feedback.get("pair_regime", {}),
        "mode": brain.get("active_mode", "UNKNOWN"),
    }


def _read_sfm_state() -> dict:
    feedback = _read_json(os.path.join(SFMBOT_DIR, "sfm_supervisor_feedback.json"))
    state = _read_json(os.path.join(SFMBOT_DIR, "sfm_state.json"))
    return {
        "sleeve": "sfm",
        "equity": feedback.get("equity", 0),
        "dd_pct": feedback.get("dd_pct", 0),
        "usdc": feedback.get("usdc_balance", 0),
        "open_position": feedback.get("open_position", False),
        "realized_pnl": state.get("realized_pnl_usd", 0),
    }


def _read_alpaca_state() -> dict:
    state = _read_json(os.path.join(ALPACA_DIR, "alpaca_state.json"))
    positions = state.get("positions", {})
    return {
        "sleeve": "alpaca",
        "equity": 500 + state.get("realized_pnl_usd", 0),  # baseline + realized
        "realized_pnl": state.get("realized_pnl_usd", 0),
        "total_trades": state.get("total_trades", 0),
        "winning_trades": state.get("winning_trades", 0),
        "losing_trades": state.get("losing_trades", 0),
        "open_positions": len(positions),
        "breakeven_armed": list(state.get("breakeven_armed", [])),
    }


def _read_recent_exits(sleeve: str) -> List[dict]:
    """Read recent exit records from exit_counterfactuals.jsonl (Kraken) or service logs."""
    if sleeve == "kraken":
        path = os.path.join(ENZOBOT_DIR, "logs", "exit_counterfactuals.jsonl")
        records = _read_jsonl_tail(path, 100)
        return [r for r in records if r.get("type") == "exit"]
    return []


# ── Metric computation ────────────────────────────────────────────────

def compute_rolling_expectancy(exits: List[dict], n: int = 20) -> float:
    """Compute rolling expectancy from last N exits."""
    recent = exits[-n:] if len(exits) >= n else exits
    if not recent:
        return 0.0
    wins = [e["pnl_usd"] for e in recent if e.get("pnl_usd", 0) > 0]
    losses = [e["pnl_usd"] for e in recent if e.get("pnl_usd", 0) < 0]
    if not wins and not losses:
        return 0.0
    win_rate = len(wins) / len(recent)
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 0
    return (win_rate * avg_win) + ((1 - win_rate) * avg_loss)


def compute_dd_rate(equity_history: List[tuple]) -> float:
    """Compute DD change rate in %/hour from equity history."""
    if len(equity_history) < 2:
        return 0.0
    # Look at last hour of data
    now = time.time()
    hour_ago = now - 3600
    recent = [(ts, eq) for ts, eq in equity_history if ts >= hour_ago]
    if len(recent) < 2:
        return 0.0
    first_eq = recent[0][1]
    last_eq = recent[-1][1]
    if first_eq <= 0:
        return 0.0
    return ((last_eq - first_eq) / first_eq) * 100


def count_exits_last_hour(exits: List[dict]) -> int:
    """Count exits in the last hour."""
    cutoff = time.time() - 3600
    return sum(1 for e in exits if e.get("ts", 0) > cutoff)


def time_since_last_win(exits: List[dict]) -> float:
    """Hours since last profitable exit. Returns 999 if no wins."""
    wins = [e for e in exits if e.get("pnl_usd", 0) > 0]
    if not wins:
        return 999.0
    last_win_ts = max(e.get("ts", 0) for e in wins)
    return (time.time() - last_win_ts) / 3600


def count_regime_flips(pair_regime_history: List[dict], hours: int = 4) -> int:
    """Count regime changes in the last N hours. Placeholder — needs history accumulation."""
    # For Phase 1, this will be computed from blocked_candidates regime field changes
    return 0  # TODO: implement with accumulated regime history


def compute_deployment_pct(cash: float, equity: float) -> float:
    """Cash deployment percentage."""
    if equity <= 0:
        return 0.0
    return ((equity - cash) / equity) * 100


# ── Decision engine ───────────────────────────────────────────────────

@dataclass
class GovernorDecision:
    ts: str
    cycle: int
    action: str          # FREEZE_ENTRIES, FORCE_DEFENSE, EXTEND_COOLDOWN, TIGHTEN_TRAILS, HOLD, ALERT
    sleeve: str
    reason: str
    shadow: bool         # True = logged only, False = executed live
    metrics: dict = field(default_factory=dict)


def _log_decision(decision: GovernorDecision) -> None:
    """Append decision to governor_decisions.jsonl."""
    try:
        with open(DECISIONS_FILE, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(asdict(decision)) + "\n")
    except Exception as exc:
        log.error("[GOVERNOR] Failed to log decision: %s", exc)


def evaluate_kraken(enzo_state: dict, exits: List[dict], cycle: int) -> List[GovernorDecision]:
    """Evaluate Kraken sleeve and produce decisions."""
    decisions = []
    now_iso = datetime.now(timezone.utc).isoformat()
    equity = enzo_state.get("equity", 0)
    dd = enzo_state.get("dd_pct", 0)

    # Track equity for DD rate
    _equity_history.append((time.time(), equity))
    # Keep last 2 hours
    cutoff = time.time() - 7200
    while _equity_history and _equity_history[0][0] < cutoff:
        _equity_history.pop(0)

    # Metric 1: Rolling expectancy
    expectancy = compute_rolling_expectancy(exits)

    # Metric 2: DD rate
    dd_rate = compute_dd_rate(_equity_history)

    # Metric 3: Exits per hour
    exits_last_hour = count_exits_last_hour(exits)

    # Metric 4: Time since last win
    hours_since_win = time_since_last_win(exits)

    # Metric 5: Deployment %
    cash = enzo_state.get("cash", 0)
    deploy_pct = compute_deployment_pct(cash, equity)

    metrics = {
        "expectancy_20": round(expectancy, 2),
        "dd_rate_pct_hour": round(dd_rate, 3),
        "exits_last_hour": exits_last_hour,
        "hours_since_win": round(hours_since_win, 1),
        "deploy_pct": round(deploy_pct, 1),
        "dd_pct": round(dd, 2),
        "equity": round(equity, 2),
        "mode": enzo_state.get("mode", "?"),
    }

    # Decision rules (tighten-only)
    if expectancy < EXPECTANCY_FREEZE_THRESHOLD:
        decisions.append(GovernorDecision(
            ts=now_iso, cycle=cycle, action="FREEZE_ENTRIES", sleeve="kraken",
            reason=f"Rolling 20-exit expectancy={expectancy:.2f} < {EXPECTANCY_FREEZE_THRESHOLD}",
            shadow=SHADOW_MODE, metrics=metrics,
        ))

    if dd_rate < -DD_ACCEL_THRESHOLD_PER_HOUR:
        decisions.append(GovernorDecision(
            ts=now_iso, cycle=cycle, action="FORCE_DEFENSE", sleeve="kraken",
            reason=f"DD accelerating at {dd_rate:.2f}%/hour (threshold {DD_ACCEL_THRESHOLD_PER_HOUR}%)",
            shadow=SHADOW_MODE, metrics=metrics,
        ))

    if exits_last_hour > CHURN_EXIT_LIMIT_PER_HOUR:
        decisions.append(GovernorDecision(
            ts=now_iso, cycle=cycle, action="EXTEND_COOLDOWN", sleeve="kraken",
            reason=f"{exits_last_hour} exits in last hour > limit {CHURN_EXIT_LIMIT_PER_HOUR}",
            shadow=SHADOW_MODE, metrics=metrics,
        ))

    if hours_since_win > NO_WIN_ALERT_HOURS and exits:
        decisions.append(GovernorDecision(
            ts=now_iso, cycle=cycle, action="ALERT", sleeve="kraken",
            reason=f"No profitable exit in {hours_since_win:.0f} hours",
            shadow=SHADOW_MODE, metrics=metrics,
        ))

    # If no action triggered, log HOLD
    if not decisions:
        decisions.append(GovernorDecision(
            ts=now_iso, cycle=cycle, action="HOLD", sleeve="kraken",
            reason="No threshold crossed", shadow=SHADOW_MODE, metrics=metrics,
        ))

    return decisions


def evaluate_sfm(sfm_state: dict, cycle: int) -> List[GovernorDecision]:
    """Evaluate SFM sleeve."""
    now_iso = datetime.now(timezone.utc).isoformat()
    metrics = {
        "equity": sfm_state.get("equity", 0),
        "dd_pct": sfm_state.get("dd_pct", 0),
        "open_position": sfm_state.get("open_position", False),
        "realized_pnl": sfm_state.get("realized_pnl", 0),
    }

    # SFM is simpler — monitor only in Phase 1
    return [GovernorDecision(
        ts=now_iso, cycle=cycle, action="HOLD", sleeve="sfm",
        reason="Monitor only", shadow=SHADOW_MODE, metrics=metrics,
    )]


def evaluate_alpaca(alpaca_state: dict, cycle: int) -> List[GovernorDecision]:
    """Evaluate Alpaca sleeve."""
    now_iso = datetime.now(timezone.utc).isoformat()
    total = alpaca_state.get("total_trades", 0)
    wins = alpaca_state.get("winning_trades", 0)
    win_rate = (wins / total * 100) if total > 0 else 0

    metrics = {
        "equity": round(alpaca_state.get("equity", 0), 2),
        "realized_pnl": round(alpaca_state.get("realized_pnl", 0), 2),
        "win_rate": round(win_rate, 1),
        "total_trades": total,
        "open_positions": alpaca_state.get("open_positions", 0),
        "breakeven_armed": alpaca_state.get("breakeven_armed", []),
    }

    decisions = []

    # Alpaca-specific: if win rate is 0% after 10+ trades, alert
    if total >= 10 and wins == 0:
        decisions.append(GovernorDecision(
            ts=now_iso, cycle=cycle, action="ALERT", sleeve="alpaca",
            reason=f"0% win rate after {total} trades",
            shadow=SHADOW_MODE, metrics=metrics,
        ))

    if not decisions:
        decisions.append(GovernorDecision(
            ts=now_iso, cycle=cycle, action="HOLD", sleeve="alpaca",
            reason="Monitor only", shadow=SHADOW_MODE, metrics=metrics,
        ))

    return decisions


# ── Main entry point ──────────────────────────────────────────────────

def run_governor(cycle: int) -> List[GovernorDecision]:
    """
    Main governor loop. Called once per supervisor cycle.
    Returns list of decisions taken (or shadow-logged).
    """
    global _last_governor_ts

    all_decisions = []

    # Read states
    enzo = _read_enzobot_state()
    sfm = _read_sfm_state()
    alpaca = _read_alpaca_state()

    # Read recent exits for Kraken
    kraken_exits = _read_recent_exits("kraken")

    # Evaluate each sleeve
    all_decisions.extend(evaluate_kraken(enzo, kraken_exits, cycle))
    all_decisions.extend(evaluate_sfm(sfm, cycle))
    all_decisions.extend(evaluate_alpaca(alpaca, cycle))

    # Log all decisions
    for d in all_decisions:
        _log_decision(d)
        if d.action != "HOLD":
            prefix = "[SHADOW]" if d.shadow else "[LIVE]"
            log.info("[GOVERNOR] %s %s on %s: %s", prefix, d.action, d.sleeve, d.reason)

    _last_governor_ts = time.time()
    return all_decisions

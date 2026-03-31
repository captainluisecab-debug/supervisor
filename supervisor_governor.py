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
SHADOW_MODE = False  # True = log only, False = live authority (enabled 2026-03-30)

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

# ── Regime Behavior Matrix ────────────────────────────────────────────
# One source of truth for what the system does in each regime.
# The governor reads the dominant regime and applies these constraints.
# This replaces scattered score caps, threshold gates, and parameter tightening.
REGIME_BEHAVIOR = {
    "TRENDING_UP": {
        "mode": "TRADE",
        "entries_allowed": True,
        "size_mult": 1.0,
        "max_positions": 4,
        "reduce_positions": False,
        "description": "Trade actively. Full conviction on sustained uptrends.",
    },
    "RANGING": {
        "mode": "REDUCE",
        "entries_allowed": False,
        "size_mult": 0.0,
        "max_positions": 2,
        "reduce_positions": True,   # actively close breakeven/small-loss positions
        "description": "No new entries. Reduce toward flat. Chop kills trend-followers.",
    },
    "TRENDING_DOWN": {
        "mode": "FLAT",
        "entries_allowed": False,
        "size_mult": 0.0,
        "max_positions": 0,
        "reduce_positions": True,   # actively close everything near breakeven
        "description": "Go flat. Hold cash. Wait for regime change.",
    },
    "VOLATILE": {
        "mode": "REDUCE",
        "entries_allowed": False,
        "size_mult": 0.0,
        "max_positions": 2,
        "reduce_positions": True,
        "description": "No new entries. Reduce exposure. Volatility without trend = churn.",
    },
}
DEFAULT_BEHAVIOR = REGIME_BEHAVIOR["RANGING"]  # conservative default

# Command file paths (for live authority mode)
CMD_KRAKEN  = os.path.join(BASE_DIR, "commands", "kraken_cmd.json")
CMD_SFM     = os.path.join(BASE_DIR, "commands", "sfm_cmd.json")
CMD_ALPACA  = os.path.join(BASE_DIR, "commands", "alpaca_cmd.json")
CMD_ENZO    = os.path.join(ENZOBOT_DIR, "supervisor_command.json")

# ── State ─────────────────────────────────────────────────────────────
_equity_history: List[tuple] = []  # [(ts, equity), ...]
_exit_history: List[dict] = []     # recent exits from fills
_last_governor_ts: float = 0
_regime_history: List[tuple] = []  # [(ts, dominant_regime)]


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


# ── Regime classification ─────────────────────────────────────────────

def classify_dominant_regime(pair_regime: dict) -> str:
    """Determine the dominant regime from per-pair classifications."""
    if not pair_regime:
        return "RANGING"
    counts = {}
    for regime in pair_regime.values():
        r = regime.upper() if isinstance(regime, str) else "RANGING"
        # Normalize: "UP" -> "TRENDING_UP", "DOWN" -> "TRENDING_DOWN"
        if r == "UP":
            r = "TRENDING_UP"
        elif r == "DOWN":
            r = "TRENDING_DOWN"
        counts[r] = counts.get(r, 0) + 1
    total = sum(counts.values())
    # Majority rule: if 60%+ of pairs are in one regime, that's dominant
    for regime, count in sorted(counts.items(), key=lambda x: -x[1]):
        if count / total >= 0.6:
            return regime
    # No clear majority -> RANGING (the conservative default)
    return "RANGING"


def get_regime_behavior(dominant_regime: str) -> dict:
    """Look up the behavioral constraints for the dominant regime."""
    return REGIME_BEHAVIOR.get(dominant_regime, DEFAULT_BEHAVIOR)


def _write_command_file(path: str, mode: str, size_mult: float,
                        entry_allowed: bool, reasoning: str, bot: str,
                        force_flatten: bool = False) -> None:
    """Write a command file for a bot sleeve. Only used when SHADOW_MODE=False."""
    if SHADOW_MODE:
        return
    cmd = {
        "mode": mode,
        "size_mult": round(size_mult, 2),
        "entry_allowed": entry_allowed,
        "force_flatten": force_flatten,
        "reasoning": reasoning,
        "bot": bot,
        "ts": datetime.now(timezone.utc).isoformat(),
        "source": "governor",
    }
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cmd, f, indent=2)
        os.replace(tmp, path)
    except Exception as exc:
        log.error("[GOVERNOR] Failed to write command %s: %s", path, exc)


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
    """Evaluate Kraken sleeve using regime behavior matrix + metrics."""
    decisions = []
    now_iso = datetime.now(timezone.utc).isoformat()
    equity = enzo_state.get("equity", 0)
    dd = enzo_state.get("dd_pct", 0)
    pair_regime = enzo_state.get("pair_regime", {})

    # Classify dominant regime
    dominant = classify_dominant_regime(pair_regime)
    behavior = get_regime_behavior(dominant)
    regime_mode = behavior["mode"]  # TRADE / REDUCE / FLAT

    # Track regime history
    if not _regime_history or _regime_history[-1][1] != dominant:
        _regime_history.append((time.time(), dominant))

    # Track equity for DD rate
    _equity_history.append((time.time(), equity))
    cutoff = time.time() - 7200
    while _equity_history and _equity_history[0][0] < cutoff:
        _equity_history.pop(0)

    # Compute metrics
    expectancy = compute_rolling_expectancy(exits)
    dd_rate = compute_dd_rate(_equity_history)
    exits_last_hour = count_exits_last_hour(exits)
    hours_since_win = time_since_last_win(exits)
    cash = enzo_state.get("cash", 0)
    deploy_pct = compute_deployment_pct(cash, equity)
    open_pos = enzo_state.get("open_positions", 0)

    metrics = {
        "dominant_regime": dominant,
        "regime_mode": regime_mode,
        "expectancy_20": round(expectancy, 2),
        "dd_rate_pct_hour": round(dd_rate, 3),
        "exits_last_hour": exits_last_hour,
        "hours_since_win": round(hours_since_win, 1),
        "deploy_pct": round(deploy_pct, 1),
        "dd_pct": round(dd, 2),
        "equity": round(equity, 2),
        "open_positions": open_pos,
        "brain_mode": enzo_state.get("mode", "?"),
    }

    # ── Regime-driven decisions ───────────────────────────────────────
    if regime_mode == "FLAT":
        # TRENDING_DOWN: go to cash. Close positions near breakeven.
        decisions.append(GovernorDecision(
            ts=now_iso, cycle=cycle, action="FORCE_FLAT", sleeve="kraken",
            reason=f"Regime={dominant} -> FLAT mode. No entries. Reduce all positions toward cash.",
            shadow=SHADOW_MODE, metrics=metrics,
        ))
        # Write DEFENSE command with force_flatten=True — close all positions
        _write_command_file(CMD_KRAKEN, "DEFENSE", 0.0, False,
                            f"Governor FLAT: {dominant}", "kraken", force_flatten=True)
        _write_command_file(CMD_ENZO, "DEFENSE", 0.0, False,
                            f"Governor FLAT: {dominant}", "kraken", force_flatten=True)

    elif regime_mode == "REDUCE":
        # RANGING/VOLATILE: no new entries, actively reduce exposure
        decisions.append(GovernorDecision(
            ts=now_iso, cycle=cycle, action="REDUCE_EXPOSURE", sleeve="kraken",
            reason=f"Regime={dominant} -> REDUCE mode. No entries. Tighten exits on held positions.",
            shadow=SHADOW_MODE, metrics=metrics,
        ))
        _write_command_file(CMD_KRAKEN, "SCOUT", 0.0, False,
                            f"Governor REDUCE: {dominant}", "kraken")
        _write_command_file(CMD_ENZO, "SCOUT", 0.0, False,
                            f"Governor REDUCE: {dominant}", "kraken")

    elif regime_mode == "TRADE":
        # TRENDING_UP: allow entries at full size
        decisions.append(GovernorDecision(
            ts=now_iso, cycle=cycle, action="TRADE_ACTIVE", sleeve="kraken",
            reason=f"Regime={dominant} -> TRADE mode. Entries allowed.",
            shadow=SHADOW_MODE, metrics=metrics,
        ))
        _write_command_file(CMD_KRAKEN, "NORMAL", behavior["size_mult"], True,
                            f"Governor TRADE: {dominant}", "kraken")
        _write_command_file(CMD_ENZO, "NORMAL", behavior["size_mult"], True,
                            f"Governor TRADE: {dominant}", "kraken")

    # ── Metric-driven overrides (tighten-only, override regime if worse) ──
    if expectancy < EXPECTANCY_FREEZE_THRESHOLD:
        decisions.append(GovernorDecision(
            ts=now_iso, cycle=cycle, action="FREEZE_ENTRIES", sleeve="kraken",
            reason=f"Expectancy={expectancy:.2f} < {EXPECTANCY_FREEZE_THRESHOLD} — overrides regime",
            shadow=SHADOW_MODE, metrics=metrics,
        ))
        # Expectancy override: freeze entries, preserve force_flatten from regime decision
        _exp_flatten = (regime_mode == "FLAT")
        _write_command_file(CMD_KRAKEN, "DEFENSE", 0.0, False,
                            f"Governor: negative expectancy override", "kraken",
                            force_flatten=_exp_flatten)
        _write_command_file(CMD_ENZO, "DEFENSE", 0.0, False,
                            f"Governor: negative expectancy override", "kraken",
                            force_flatten=_exp_flatten)

    if dd_rate < -DD_ACCEL_THRESHOLD_PER_HOUR:
        decisions.append(GovernorDecision(
            ts=now_iso, cycle=cycle, action="FORCE_DEFENSE", sleeve="kraken",
            reason=f"DD accelerating at {dd_rate:.2f}%/hour",
            shadow=SHADOW_MODE, metrics=metrics,
        ))

    if exits_last_hour > CHURN_EXIT_LIMIT_PER_HOUR:
        decisions.append(GovernorDecision(
            ts=now_iso, cycle=cycle, action="EXTEND_COOLDOWN", sleeve="kraken",
            reason=f"{exits_last_hour} exits in last hour > {CHURN_EXIT_LIMIT_PER_HOUR}",
            shadow=SHADOW_MODE, metrics=metrics,
        ))

    if hours_since_win > NO_WIN_ALERT_HOURS and exits:
        decisions.append(GovernorDecision(
            ts=now_iso, cycle=cycle, action="ALERT", sleeve="kraken",
            reason=f"No profitable exit in {hours_since_win:.0f} hours",
            shadow=SHADOW_MODE, metrics=metrics,
        ))

    return decisions


def evaluate_sfm(sfm_state: dict, cycle: int, supervisor_regime: str) -> List[GovernorDecision]:
    """Evaluate SFM sleeve with regime awareness."""
    now_iso = datetime.now(timezone.utc).isoformat()
    equity = sfm_state.get("equity", 0)
    has_position = sfm_state.get("open_position", False)

    # SFM uses supervisor regime (single asset, global regime is sufficient)
    behavior = get_regime_behavior(supervisor_regime)
    regime_mode = behavior["mode"]

    metrics = {
        "equity": round(equity, 2),
        "dd_pct": sfm_state.get("dd_pct", 0),
        "open_position": has_position,
        "realized_pnl": round(sfm_state.get("realized_pnl", 0), 2),
        "regime": supervisor_regime,
        "regime_mode": regime_mode,
    }

    decisions = []

    if regime_mode == "FLAT":
        if has_position:
            decisions.append(GovernorDecision(
                ts=now_iso, cycle=cycle, action="FORCE_FLAT", sleeve="sfm",
                reason=f"Regime={supervisor_regime} -> FLAT. Position should be closed.",
                shadow=SHADOW_MODE, metrics=metrics,
            ))
        else:
            decisions.append(GovernorDecision(
                ts=now_iso, cycle=cycle, action="HOLD_FLAT", sleeve="sfm",
                reason=f"Regime={supervisor_regime} -> FLAT. Already flat. Holding cash.",
                shadow=SHADOW_MODE, metrics=metrics,
            ))
        _write_command_file(CMD_SFM, "DEFENSE", 0.0, False,
                            f"Governor FLAT: {supervisor_regime}", "sfm", force_flatten=has_position)
    elif regime_mode == "REDUCE":
        decisions.append(GovernorDecision(
            ts=now_iso, cycle=cycle, action="REDUCE_EXPOSURE", sleeve="sfm",
            reason=f"Regime={supervisor_regime} -> REDUCE. No new entries.",
            shadow=SHADOW_MODE, metrics=metrics,
        ))
        _write_command_file(CMD_SFM, "SCOUT", 0.3, False,
                            f"Governor REDUCE: {supervisor_regime}", "sfm")
    elif regime_mode == "TRADE":
        decisions.append(GovernorDecision(
            ts=now_iso, cycle=cycle, action="TRADE_ACTIVE", sleeve="sfm",
            reason=f"Regime={supervisor_regime} -> TRADE.",
            shadow=SHADOW_MODE, metrics=metrics,
        ))
        _write_command_file(CMD_SFM, "NORMAL", 0.8, True,
                            f"Governor TRADE: {supervisor_regime}", "sfm")
    else:
        decisions.append(GovernorDecision(
            ts=now_iso, cycle=cycle, action="HOLD", sleeve="sfm",
            reason="Monitor only", shadow=SHADOW_MODE, metrics=metrics,
        ))
        _write_command_file(CMD_SFM, "SCOUT", 0.5, False,
                            f"Governor HOLD: default cautious", "sfm")

    return decisions


def evaluate_alpaca(alpaca_state: dict, cycle: int, supervisor_regime: str) -> List[GovernorDecision]:
    """Evaluate Alpaca sleeve with regime awareness."""
    now_iso = datetime.now(timezone.utc).isoformat()
    total = alpaca_state.get("total_trades", 0)
    wins = alpaca_state.get("winning_trades", 0)
    win_rate = (wins / total * 100) if total > 0 else 0

    behavior = get_regime_behavior(supervisor_regime)
    regime_mode = behavior["mode"]

    metrics = {
        "equity": round(alpaca_state.get("equity", 0), 2),
        "realized_pnl": round(alpaca_state.get("realized_pnl", 0), 2),
        "win_rate": round(win_rate, 1),
        "total_trades": total,
        "open_positions": alpaca_state.get("open_positions", 0),
        "breakeven_armed": alpaca_state.get("breakeven_armed", []),
        "regime": supervisor_regime,
        "regime_mode": regime_mode,
    }

    decisions = []

    # Regime-driven
    if regime_mode == "FLAT":
        decisions.append(GovernorDecision(
            ts=now_iso, cycle=cycle, action="FORCE_FLAT", sleeve="alpaca",
            reason=f"Regime={supervisor_regime} -> FLAT. Reduce all positions.",
            shadow=SHADOW_MODE, metrics=metrics,
        ))
        _write_command_file(CMD_ALPACA, "DEFENSE", 0.0, False,
                            f"Governor FLAT: {supervisor_regime}", "alpaca", force_flatten=True)
    elif regime_mode == "REDUCE":
        decisions.append(GovernorDecision(
            ts=now_iso, cycle=cycle, action="REDUCE_EXPOSURE", sleeve="alpaca",
            reason=f"Regime={supervisor_regime} -> REDUCE. No new entries.",
            shadow=SHADOW_MODE, metrics=metrics,
        ))
        _write_command_file(CMD_ALPACA, "SCOUT", 0.3, False,
                            f"Governor REDUCE: {supervisor_regime}", "alpaca")
    elif regime_mode == "TRADE":
        decisions.append(GovernorDecision(
            ts=now_iso, cycle=cycle, action="TRADE_ACTIVE", sleeve="alpaca",
            reason=f"Regime={supervisor_regime} -> TRADE.",
            shadow=SHADOW_MODE, metrics=metrics,
        ))
        _write_command_file(CMD_ALPACA, "NORMAL", 0.7, True,
                            f"Governor TRADE: {supervisor_regime}", "alpaca")

    # Win rate alert
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
        _write_command_file(CMD_ALPACA, "SCOUT", 0.5, False,
                            f"Governor HOLD: default cautious", "alpaca")

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

    # Determine dominant regime from Kraken pair data (most granular source)
    kraken_pair_regime = enzo.get("pair_regime", {})
    dominant_regime = classify_dominant_regime(kraken_pair_regime)

    # Read recent exits for Kraken
    kraken_exits = _read_recent_exits("kraken")

    # Evaluate each sleeve with regime context
    all_decisions.extend(evaluate_kraken(enzo, kraken_exits, cycle))
    all_decisions.extend(evaluate_sfm(sfm, cycle, dominant_regime))
    all_decisions.extend(evaluate_alpaca(alpaca, cycle, dominant_regime))

    # Log all decisions
    for d in all_decisions:
        _log_decision(d)
        if d.action != "HOLD":
            prefix = "[SHADOW]" if d.shadow else "[LIVE]"
            log.info("[GOVERNOR] %s %s on %s: %s", prefix, d.action, d.sleeve, d.reason)

    _last_governor_ts = time.time()
    return all_decisions

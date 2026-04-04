"""
supervisor_governor.py — GOVERNOR: Live Execution Authority.

ROLE: Only live writer of command files. Drives posture, enforces regime,
protects capital. No other component may write commands or override.
GOAL: Increase positive PnL. Protect capital. Reduce stupid losses.

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
# Kraken single source of truth — governor consolidates all inputs every cycle
KRAKEN_TRUTH_FILE = os.path.join(BASE_DIR, "kraken_state_truth.json")

# ── State ─────────────────────────────────────────────────────────────
_equity_history: List[tuple] = []  # [(ts, equity), ...]
_exit_history: List[dict] = []     # recent exits from fills
_last_governor_ts: float = 0
_regime_history: List[tuple] = []  # [(ts, dominant_regime)]
_posture_outcomes: List[dict] = [] # [{posture, equity_start, equity_end, duration, correct}]

# Feedback loop file — persists posture outcomes across restarts
POSTURE_OUTCOMES_FILE = os.path.join(BASE_DIR, "governor_posture_outcomes.jsonl")

# Opus 12h brief
UNIVERSE_BRIEF_FILE = os.path.join(BASE_DIR, "governor_universe_brief.json")
OPUS_REPORT_FILE    = os.path.join(BASE_DIR, "opus_12h_report.md")


def _write_universe_brief(decisions, enzo, sfm, alpaca, regime, brain_note):
    """Write a structured universe brief for Opus 12h review."""
    effective = {}
    for d in decisions:
        if d.sleeve not in effective or d.action not in ("HOLD", "HOLD_FLAT"):
            effective[d.sleeve] = d.action

    brief = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "dominant_regime": regime,
        "effective_posture": effective,
        "kraken": {
            "equity": enzo.get("equity", 0),
            "dd_pct": enzo.get("dd_pct", 0),
            "mode": enzo.get("mode", "?"),
            "open_positions": enzo.get("open_positions", 0),
            "cash": enzo.get("cash", 0),
        },
        "sfm": {
            "equity": sfm.get("equity", 0),
            "dd_pct": sfm.get("dd_pct", 0),
            "open_position": sfm.get("open_position", False),
        },
        "alpaca": {
            "equity": alpaca.get("equity", 0),
            "realized_pnl": alpaca.get("realized_pnl", 0),
            "win_rate": alpaca.get("winning_trades", 0) / max(alpaca.get("total_trades", 1), 1) * 100,
            "open_positions": alpaca.get("open_positions", 0),
        },
        "brain_advisory": brain_note[:200] if brain_note else "",
        "governor_decisions": [
            {"sleeve": d.sleeve, "action": d.action, "reason": d.reason[:100]}
            for d in decisions if d.action not in ("HOLD", "HOLD_FLAT")
        ],
        "feedback": {
            "equity_1h_ago": _equity_history[0][1] if _equity_history else 0,
            "equity_now": enzo.get("equity", 0) + sfm.get("equity", 0) + alpaca.get("equity", 0),
            "equity_direction": "improving" if (_equity_history and
                (enzo.get("equity", 0) + sfm.get("equity", 0) + alpaca.get("equity", 0)) > _equity_history[0][1])
                else "declining" if _equity_history else "unknown",
        },
    }
    try:
        with open(UNIVERSE_BRIEF_FILE, "w", encoding="utf-8") as f:
            json.dump(brief, f, indent=2)
    except Exception as exc:
        log.error("[GOVERNOR] Failed to write universe brief: %s", exc)


# ── Kraken state truth ────────────────────────────────────────────────

def _write_kraken_truth(enzo_state: dict, decisions: list, dominant_regime: str):
    """Write the single authoritative Kraken state file every cycle.
    Consolidates: portfolio, brain mode, positions, regime, governor command.
    Any component that needs to know Kraken's full state reads this file."""
    kraken_decisions = [d for d in decisions if d.sleeve == "kraken"]
    effective_action = "HOLD"
    # ALERT is informational (no command-file change), skip it for posture
    _INFORMATIONAL_ACTIONS = {"ALERT", "EXTEND_COOLDOWN"}
    for d in kraken_decisions:
        if d.action not in ("HOLD", "HOLD_FLAT") and d.action not in _INFORMATIONAL_ACTIONS:
            effective_action = d.action

    # Read current command file for completeness
    cmd = _read_json(CMD_KRAKEN)

    truth = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "source": "governor",
        "effective_posture": effective_action,
        "force_flatten": cmd.get("force_flatten", False),
        "portfolio": {
            "equity": enzo_state.get("equity", 0),
            "cash": enzo_state.get("cash", 0),
            "dd_pct": enzo_state.get("dd_pct", 0),
            "open_positions": enzo_state.get("open_positions", 0),
        },
        "brain_mode": enzo_state.get("mode", "?"),
        "regime": {
            "dominant": dominant_regime,
            "pair_regime": enzo_state.get("pair_regime", {}),
        },
        "governor_decisions": [
            {"action": d.action, "reason": d.reason[:80]} for d in kraken_decisions
        ],
        "command": {
            "mode": cmd.get("mode", "?"),
            "size_mult": cmd.get("size_mult", 0),
            "entry_allowed": cmd.get("entry_allowed", False),
        },
    }
    try:
        tmp = KRAKEN_TRUTH_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(truth, f, indent=2)
        os.replace(tmp, KRAKEN_TRUTH_FILE)
    except Exception as exc:
        log.error("[GOVERNOR] Failed to write Kraken truth: %s", exc)


# ── Feedback loop ─────────────────────────────────────────────────────

_last_posture_snapshot: Optional[dict] = None


def _score_posture_outcome(current_equity: float, current_posture: str) -> Optional[dict]:
    """Score the previous posture period by comparing equity change with posture.
    Returns an outcome record or None if not enough data."""
    global _last_posture_snapshot
    now = time.time()

    if _last_posture_snapshot is None:
        _last_posture_snapshot = {
            "posture": current_posture, "equity": current_equity, "ts": now
        }
        return None

    prev = _last_posture_snapshot
    duration_min = (now - prev["ts"]) / 60

    # Only score if posture changed or 60+ minutes elapsed
    if current_posture == prev["posture"] and duration_min < 60:
        return None

    equity_delta = current_equity - prev["equity"]
    prev_posture = prev["posture"]

    # Score: was the posture correct given the outcome?
    if prev_posture == "FLAT" and equity_delta < -5:
        verdict = "CORRECT"  # Flat and market went down — good call
    elif prev_posture == "FLAT" and equity_delta > 5:
        verdict = "WRONG"    # Flat but market went up — missed gains
    elif prev_posture == "TRADE" and equity_delta > 0:
        verdict = "CORRECT"  # Trading and made money
    elif prev_posture == "TRADE" and equity_delta < -5:
        verdict = "WRONG"    # Trading and lost money
    else:
        verdict = "NEUTRAL"  # Small moves, inconclusive

    outcome = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "posture": prev_posture,
        "duration_min": round(duration_min, 1),
        "equity_start": round(prev["equity"], 2),
        "equity_end": round(current_equity, 2),
        "equity_delta": round(equity_delta, 2),
        "verdict": verdict,
    }

    # Log to persistent file
    try:
        with open(POSTURE_OUTCOMES_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(outcome) + "\n")
    except Exception:
        pass

    # Update snapshot
    _last_posture_snapshot = {
        "posture": current_posture, "equity": current_equity, "ts": now
    }

    return outcome


# Adaptive regime threshold bounds (governor may adjust within these)
_REGIME_THRESH_MIN = 1800   # 30 min floor
_REGIME_THRESH_MAX = 14400  # 4 hour ceiling
_REGIME_THRESH_STEP = 900   # 15 min adjustment per feedback cycle


def _adjust_regime_threshold():
    """Adjust the Kraken regime duration threshold based on posture outcomes.
    If recent TRADE outcomes were WRONG, tighten (require longer regime stability).
    If recent TRADE outcomes were CORRECT, loosen (allow shorter regime stability).
    Bounded between 30 min and 4 hours."""
    try:
        if not os.path.exists(POSTURE_OUTCOMES_FILE):
            return
        with open(POSTURE_OUTCOMES_FILE, encoding="utf-8") as f:
            outcomes = [json.loads(l.strip()) for l in f.readlines()[-10:] if l.strip()]
        trade_outcomes = [o for o in outcomes if o.get("posture") in ("TRADE_ACTIVE", "TRADE")]
        if len(trade_outcomes) < 3:
            return  # not enough data to adjust

        recent_5 = trade_outcomes[-5:]
        wrong_count = sum(1 for o in recent_5 if o.get("verdict") == "WRONG")
        correct_count = sum(1 for o in recent_5 if o.get("verdict") == "CORRECT")

        # Read current threshold from enzobot engine config
        # We can't write to .env directly, but we can write an advisory that the
        # 12h Opus review or operator can act on
        # Read current threshold
        current_cmd = _read_json(CMD_KRAKEN)
        current_thresh = current_cmd.get("regime_min_stable_sec", 3600)

        new_thresh = current_thresh
        if wrong_count >= 3 and current_thresh < _REGIME_THRESH_MAX:
            new_thresh = min(current_thresh + _REGIME_THRESH_STEP, _REGIME_THRESH_MAX)
            log.info("[FEEDBACK] %d/5 TRADE outcomes WRONG — regime threshold %ds -> %ds",
                     wrong_count, current_thresh, new_thresh)
        elif correct_count >= 3 and current_thresh > _REGIME_THRESH_MIN:
            new_thresh = max(current_thresh - _REGIME_THRESH_STEP, _REGIME_THRESH_MIN)
            log.info("[FEEDBACK] %d/5 TRADE outcomes CORRECT — regime threshold %ds -> %ds",
                     correct_count, current_thresh, new_thresh)

        if new_thresh != current_thresh:
            # Write updated threshold to command file — engine reads it next cycle
            current_cmd["regime_min_stable_sec"] = new_thresh
            try:
                tmp = CMD_KRAKEN + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(current_cmd, f, indent=2)
                os.replace(tmp, CMD_KRAKEN)
            except Exception:
                pass
    except Exception as exc:
        log.debug("[FEEDBACK] Threshold adjustment error: %s", exc)


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
    equity = 500 + state.get("realized_pnl_usd", 0)  # baseline + realized
    dd_pct = (equity - 500) / 500 * 100 if equity < 500 else 0
    return {
        "sleeve": "alpaca",
        "equity": equity,
        "dd_pct": dd_pct,
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
    """Determine the dominant regime from per-pair classifications.
    Weighted by asset tier: BTC/ETH=2x, SOL/XRP=1.5x, others=1x.
    Prevents small-cap alts from outvoting large-cap direction."""
    if not pair_regime:
        return "RANGING"
    TIER_WEIGHTS = {
        "BTC/USD": 2.0, "ETH/USD": 2.0,
        "SOL/USD": 1.5, "XRP/USD": 1.5,
    }
    counts = {}
    total = 0.0
    for pair, regime in pair_regime.items():
        r = regime.upper() if isinstance(regime, str) else "RANGING"
        if r == "UP":
            r = "TRENDING_UP"
        elif r == "DOWN":
            r = "TRENDING_DOWN"
        weight = TIER_WEIGHTS.get(pair, 1.0)
        counts[r] = counts.get(r, 0) + weight
        total += weight
    if total <= 0:
        return "RANGING"
    # Weighted majority: if 55%+ of weighted votes are in one regime
    for regime, count in sorted(counts.items(), key=lambda x: -x[1]):
        if count / total >= 0.55:
            return regime
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
    """Compute rolling expectancy from last N trading exits.
    Excludes governor_force_flatten exits — those are deliberate capital
    preservation, not trading failures."""
    # Filter out force_flatten exits
    trading_exits = [e for e in exits if e.get("exit_reason") != "governor_force_flatten"]
    recent = trading_exits[-n:] if len(trading_exits) >= n else trading_exits
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
    classification: str = ""  # ALLOW/DELAY/REDUCE/OVERRIDE/BLOCK/ESCALATE (shadow — logged only)


def _log_decision(decision: GovernorDecision) -> None:
    """Append decision to governor_decisions.jsonl."""
    try:
        with open(DECISIONS_FILE, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(asdict(decision)) + "\n")
    except Exception as exc:
        log.error("[GOVERNOR] Failed to log decision: %s", exc)


def evaluate_kraken(enzo_state: dict, exits: List[dict], cycle: int,
                    hermes_advisory: dict = None) -> List[GovernorDecision]:
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

    elif regime_mode == "REDUCE":
        # RANGING/VOLATILE: no new entries, actively reduce exposure
        decisions.append(GovernorDecision(
            ts=now_iso, cycle=cycle, action="REDUCE_EXPOSURE", sleeve="kraken",
            reason=f"Regime={dominant} -> REDUCE mode. No entries. Tighten exits on held positions.",
            shadow=SHADOW_MODE, metrics=metrics,
        ))
        _write_command_file(CMD_KRAKEN, "SCOUT", 0.0, False,
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

    # Hermes DD advisory override (tighten-only): if Hermes says no entries, block entries
    _hermes_entry = (hermes_advisory or {}).get("kraken", {}).get("entry_allowed", True)
    if not _hermes_entry:
        decisions.append(GovernorDecision(
            ts=now_iso, cycle=cycle, action="HERMES_DD_OVERRIDE", sleeve="kraken",
            reason=f"Hermes advisory: entry_allowed=false (DD={dd:.1f}%) — tighten-only override",
            shadow=SHADOW_MODE, metrics=metrics,
        ))
        _write_command_file(CMD_KRAKEN, "DEFENSE", 0.0, False,
                            f"Governor: Hermes DD override (DD={dd:.1f}%)", "kraken",
                            force_flatten=(regime_mode == "FLAT"))
        log.info("[GOVERNOR] Hermes DD override: entry_allowed=false (DD=%.1f%%)", dd)

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
            ts=now_iso, cycle=cycle, action="ALERT_FREEZE", sleeve="kraken",
            reason=f"No profitable exit in {hours_since_win:.0f} hours — entries blocked",
            shadow=SHADOW_MODE, metrics=metrics,
        ))
        # Tighten-only: block entries when the bot can't produce wins
        _write_command_file(CMD_KRAKEN, "DEFENSE", 0.0, False,
                            f"Governor: no win in {hours_since_win:.0f}h — entries frozen", "kraken",
                            force_flatten=(regime_mode == "FLAT"))

    # Shadow classification (6-level — logged only, no behavior change)
    if decisions:
        actions = {d.action for d in decisions}
        if "FORCE_DEFENSE" in actions or "FREEZE_ENTRIES" in actions:
            _cls = "BLOCK"
        elif "ALERT_FREEZE" in actions:
            _cls = "BLOCK"
        elif "HERMES_DD_OVERRIDE" in actions:
            _cls = "OVERRIDE"
        elif "REDUCE_EXPOSURE" in actions:
            _cls = "REDUCE"
        elif "TRADE_ACTIVE" in actions and expectancy < -0.5:
            _cls = "DELAY"
        elif "TRADE_ACTIVE" in actions:
            _cls = "ALLOW"
        elif hours_since_win > 48 or dd < -10:
            _cls = "ESCALATE"
        else:
            _cls = "REDUCE"
        decisions[0].classification = _cls

    return decisions


def evaluate_sfm(sfm_state: dict, cycle: int, supervisor_regime: str,
                  hermes_advisory: dict = None) -> List[GovernorDecision]:
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

    # Hermes DD advisory override (tighten-only): if Hermes says no entries, block entries
    _sfm_dd = sfm_state.get("dd_pct", 0)
    _hermes_entry = (hermes_advisory or {}).get("sfm", {}).get("entry_allowed", True)
    if not _hermes_entry:
        decisions.append(GovernorDecision(
            ts=now_iso, cycle=cycle, action="HERMES_DD_OVERRIDE", sleeve="sfm",
            reason=f"Hermes advisory: entry_allowed=false (DD={_sfm_dd:.1f}%) — tighten-only override",
            shadow=SHADOW_MODE, metrics=metrics,
        ))
        _write_command_file(CMD_SFM, "DEFENSE", 0.0, False,
                            f"Governor: Hermes DD override (DD={_sfm_dd:.1f}%)", "sfm")
        log.info("[GOVERNOR] SFM Hermes DD override: entry_allowed=false (DD=%.1f%%)", _sfm_dd)

    # Shadow classification (6-level)
    if decisions:
        actions = {d.action for d in decisions}
        if "HERMES_DD_OVERRIDE" in actions:
            _cls = "OVERRIDE"
        elif "FORCE_FLAT" in actions or "HOLD_FLAT" in actions:
            _cls = "BLOCK"
        elif "REDUCE_EXPOSURE" in actions:
            _cls = "REDUCE"
        elif "TRADE_ACTIVE" in actions:
            _cls = "ALLOW"
        else:
            _cls = "REDUCE"
        decisions[0].classification = _cls

    return decisions


def evaluate_alpaca(alpaca_state: dict, cycle: int, supervisor_regime: str,
                    hermes_advisory: dict = None) -> List[GovernorDecision]:
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

    # Hermes DD advisory override (tighten-only): if Hermes says no entries, block entries
    _alp_dd = alpaca_state.get("dd_pct", 0)
    _hermes_entry = (hermes_advisory or {}).get("alpaca", {}).get("entry_allowed", True)
    if not _hermes_entry:
        decisions.append(GovernorDecision(
            ts=now_iso, cycle=cycle, action="HERMES_DD_OVERRIDE", sleeve="alpaca",
            reason=f"Hermes advisory: entry_allowed=false (DD={_alp_dd:.1f}%) — tighten-only override",
            shadow=SHADOW_MODE, metrics=metrics,
        ))
        _write_command_file(CMD_ALPACA, "DEFENSE", 0.0, False,
                            f"Governor: Hermes DD override (DD={_alp_dd:.1f}%)", "alpaca")
        log.info("[GOVERNOR] Alpaca Hermes DD override: entry_allowed=false (DD=%.1f%%)", _alp_dd)

    # Shadow classification (6-level)
    if decisions:
        actions = {d.action for d in decisions}
        if "FORCE_FLAT" in actions:
            _cls = "BLOCK"
        elif "HERMES_DD_OVERRIDE" in actions:
            _cls = "OVERRIDE"
        elif "REDUCE_EXPOSURE" in actions:
            _cls = "REDUCE"
        elif "TRADE_ACTIVE" in actions:
            _cls = "ALLOW"
        else:
            _cls = "REDUCE"
        decisions[0].classification = _cls

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

    # Read Hermes context (advisory input — governor decides, Hermes advises)
    _hermes_ctx = _read_json(os.path.join(BASE_DIR, "hermes_context.json"))
    _hermes_advisory = _hermes_ctx.get("advisory", {})
    _brain_note = _hermes_advisory.get("note", "")

    # AUTHORITATIVE regime: Governor classifies from per-pair data (most granular).
    # Brain uses macro regime (RISK_ON/OFF) for advisory only — governor overrides.
    # No duplication conflict: governor decides, brain advises.
    kraken_pair_regime = enzo.get("pair_regime", {})
    dominant_regime = classify_dominant_regime(kraken_pair_regime)

    # Read recent exits for Kraken
    kraken_exits = _read_recent_exits("kraken")

    # Evaluate each sleeve with regime context
    all_decisions.extend(evaluate_kraken(enzo, kraken_exits, cycle, _hermes_advisory))
    all_decisions.extend(evaluate_sfm(sfm, cycle, dominant_regime, _hermes_advisory))
    all_decisions.extend(evaluate_alpaca(alpaca, cycle, dominant_regime, _hermes_advisory))

    # Log all decisions
    for d in all_decisions:
        _log_decision(d)
        if d.action not in ("HOLD", "HOLD_FLAT"):
            prefix = "[SHADOW]" if d.shadow else "[LIVE]"
            log.info("[GOVERNOR] %s %s on %s: %s", prefix, d.action, d.sleeve, d.reason)

    # Effective state summary — one clear line showing what each sleeve is actually doing
    _effective = {}
    for d in all_decisions:
        if d.sleeve not in _effective or d.action not in ("HOLD", "HOLD_FLAT"):
            _effective[d.sleeve] = d.action
    _eff_str = " | ".join(f"{s}={a}" for s, a in sorted(_effective.items()))
    log.info("[GOVERNOR] EFFECTIVE: %s", _eff_str)

    # Feedback loop: score the previous posture period
    _total_equity = enzo.get("equity", 0) + sfm.get("equity", 0) + alpaca.get("equity", 0)
    _dominant_posture = _effective.get("kraken", "UNKNOWN")
    _outcome = _score_posture_outcome(_total_equity, _dominant_posture)
    if _outcome:
        log.info("[GOVERNOR] POSTURE SCORED: %s for %dm -> %s ($%+.2f)",
                 _outcome["posture"], _outcome["duration_min"],
                 _outcome["verdict"], _outcome["equity_delta"])

    # Write universe brief for Opus 12h review
    _write_universe_brief(all_decisions, enzo, sfm, alpaca, dominant_regime, _brain_note)

    # Write Kraken single source of truth
    _write_kraken_truth(enzo, all_decisions, dominant_regime)

    # Adaptive feedback: adjust Kraken regime duration based on posture outcomes
    _adjust_regime_threshold()

    _last_governor_ts = time.time()
    return all_decisions

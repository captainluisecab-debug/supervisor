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
EXPECTANCY_FREEZE_THRESHOLD  = -3.5   # Loosened from -2.0 (2026-04-10): tight threshold caused repeated freeze cycles. Strategy needs room to recover before lock-out.
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
        "mode": "SCOUT",                # SCOUT OFFENSE: allow reduced entries in RANGING
        "entries_allowed": True,         # was False — RANGING is not hostile, allow learning
        "size_mult": 0.3,               # 30% normal size — controlled exposure
        "max_positions": 2,
        "reduce_positions": False,       # don't actively close — let positions run to stops/targets
        "description": "Scout mode. Small entries allowed. Reduced sizing. Learn from ranging conditions.",
    },
    "TRENDING_DOWN": {
        "mode": "SCOUT",
        "entries_allowed": True,
        "size_mult": 0.3,
        "max_positions": 2,
        "reduce_positions": False,
        "description": "Operator-relaxed 2026-04-29 (was FLAT). SCOUT mode — allow trader-driven counter-trend longs. Trader's classifier (8-state) gates each entry; Controllers + sentinel restrict universe to BTC/NEAR; per-pair stop+size discipline preserved. No force_flatten on existing positions.",
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
CMD_ZEROBOT = os.path.join(BASE_DIR, "commands", "zerobot_cmd.json")
ZEROBOT_DIR = r"C:\Projects\zerobot"
# CMD_DRIFTBOT / DRIFTBOT_DIR removed — driftbot RETIRED + de-wired (D-062, 2026-06-23)
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
            {"action": d.action, "reason": d.reason[:200]} for d in kraken_decisions
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


# _adjust_regime_threshold() REMOVED — enzobot retired/de-wired (D-063). Tuned the Kraken regime
# duration via kraken_cmd writes from posture-outcome feedback. 0 callers.


def _parse_ts(ts_str: str) -> float:
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return 0.0


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
    """D-063: Kraken ACCOUNT + crypto regime, sourced from kraken_account_monitor (enzobot fully
    retired/de-wired). Returns the monitor's dict (live Kraken equity + BTC pair_regime). Function
    name kept for call-site stability; this is the Kraken account monitor, no longer a trading sleeve."""
    try:
        from kraken_account_monitor import read_kraken_account
        return read_kraken_account()
    except Exception as e:
        log.warning("[KRAKEN-MONITOR] read failed (%s) — empty (regime falls back to RANGING)", e)
        return {"sleeve": "kraken", "equity": 0, "dd_pct": 0, "cash": 0, "open_positions": 0,
                "portfolio": {}, "pair_regime": {}, "pair_scores": {}, "mode": "MONITOR"}


def _read_sfm_state() -> dict:
    feedback = _read_json(os.path.join(SFMBOT_DIR, "sfm_supervisor_feedback.json"))
    state = _read_json(os.path.join(SFMBOT_DIR, "solana_state.json"))
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
    # D-051 corruption #3: source LIVE Alpaca equity (mirror supervisor_portfolio.read_alpacabot),
    # not a hardcoded "500 + realized" (understated ~$545.84 vs real ~$1060.86). ALPACA_BASELINE
    # imported (=1000) — never a numeric literal. This equity feeds the universe DD circuit breaker.
    from supervisor_settings import ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASELINE
    open_live = None
    try:
        from alpaca.trading.client import TradingClient
        _c = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=ALPACA_API_KEY.startswith("PK"))
        equity = float(_c.get_account().equity)
        open_live = len(_c.get_all_positions())
    except Exception as exc:
        log.warning("[GOVERNOR] Alpaca live read failed: %s — baseline+realized fallback", exc)
        equity = ALPACA_BASELINE + float(state.get("realized_pnl_usd", 0))
    dd_pct = (equity - ALPACA_BASELINE) / ALPACA_BASELINE * 100 if equity < ALPACA_BASELINE else 0.0
    return {
        "sleeve": "alpaca",
        "equity": equity,
        "dd_pct": dd_pct,
        "realized_pnl": state.get("realized_pnl_usd", 0),
        "total_trades": state.get("total_trades", 0),
        "winning_trades": state.get("winning_trades", 0),
        "losing_trades": state.get("losing_trades", 0),
        "open_positions": open_live if open_live is not None else len(positions),
        "breakeven_armed": list(state.get("breakeven_armed", [])),
        "pair_regime": dict(state.get("pair_regime", {}) or {}),
    }


def _read_zerobot_state() -> dict:
    """Read zerobot brain_state.json — Donchian-20 BTC paper sleeve.

    Returns governor-compatible dict. brain_state is engine's authoritative
    state snapshot per cycle. Paper sleeve, baseline $3,408. Per L-009
    (Loophole D), zerobot is guaranteed paper regardless of user env vars.
    """
    brain = _read_json(os.path.join(ZEROBOT_DIR, "brain_state.json"))
    baseline = 3408.0
    equity = float(brain.get("equity_usd", baseline))
    # dd_pct in brain_state is a fraction (0.0-1.0); convert to % for governor.
    dd_frac = float(brain.get("dd_pct", 0.0))
    dd_pct = -dd_frac * 100.0
    has_pos = bool(brain.get("has_position", False))
    return {
        "sleeve": "zerobot",
        "equity": equity,
        "dd_pct": dd_pct,
        "realized_pnl": equity - baseline,  # paper: total return is the proxy
        "total_trades": 0,                   # not tracked in brain_state
        "winning_trades": 0,
        "losing_trades": 0,
        "open_positions": 1 if has_pos else 0,
        "consecutive_losses": int(brain.get("consecutive_losses", 0)),
        "dd_brake_active": bool(brain.get("dd_brake_active", False)),
        "mode": str(brain.get("mode", "NORMAL")),
        # No pair_regime — zerobot uses its OWN SMA-50 macro filter, not regime classifier.
    }


# _read_driftbot_state() REMOVED — driftbot retired/de-wired (D-062, 2026-06-23)


def _read_recent_exits(sleeve: str) -> List[dict]:
    """Read recent exit records from exit_counterfactuals.jsonl (Kraken) or service logs.
    Deduplicates by (pair, entry_price, exit_reason) — engine logs each exit
    twice with slightly different timestamps/IDs, which contaminates rolling
    expectancy if not filtered."""
    if sleeve == "kraken":
        path = os.path.join(ENZOBOT_DIR, "logs", "exit_counterfactuals.jsonl")
        records = _read_jsonl_tail(path, 200)
        exits = [r for r in records if r.get("type") == "exit"]
        seen = set()
        deduped = []
        for e in exits:
            # Dedup key: same pair + same entry price + same exit reason = same trade
            key = (e.get("pair", ""), e.get("entry_price", 0), e.get("exit_reason", ""))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(e)
        return deduped
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


CAUTIOUS_PHASE_HOURS_DEFAULT = 6.0  # hours after regime change before trusting the trend
CAUTIOUS_PHASE_HOURS_BOUNDS = (3.0, 8.0)  # autonomous tuning lane
GOVERNOR_POLICY_FILE = os.path.join(BASE_DIR, "governor_policy.json")


def _get_cautious_phase_hours() -> float:
    """Read CAUTIOUS_PHASE_HOURS from governor_policy.json, clamped to bounds.
    Falls back to default 6.0 if file missing / malformed."""
    try:
        if os.path.exists(GOVERNOR_POLICY_FILE):
            with open(GOVERNOR_POLICY_FILE, encoding="utf-8") as _f:
                _p = json.load(_f)
            _v = float(_p.get("CAUTIOUS_PHASE_HOURS", CAUTIOUS_PHASE_HOURS_DEFAULT))
            _lo, _hi = CAUTIOUS_PHASE_HOURS_BOUNDS
            return max(_lo, min(_hi, _v))
    except Exception:
        pass
    return CAUTIOUS_PHASE_HOURS_DEFAULT


# Legacy name kept for any callers that import it; prefer _get_cautious_phase_hours().
CAUTIOUS_PHASE_HOURS = CAUTIOUS_PHASE_HOURS_DEFAULT

def _write_command_file(path: str, mode: str, size_mult: float,
                        entry_allowed: bool, reasoning: str, bot: str,
                        force_flatten: bool = False,
                        trend_phase: str = "",
                        trend_phase_hours: float = 0.0,
                        max_positions: int = 0,
                        dominant_regime_override: str = "") -> None:
    """Write a command file for a bot sleeve. Only used when SHADOW_MODE=False."""
    if SHADOW_MODE:
        return
    # Apply strategic directive size adjustment if available
    _strat_file = os.path.join(BASE_DIR, "opus_strategic_directive.json")
    try:
        if os.path.exists(_strat_file) and size_mult > 0:
            _sd = _read_json(_strat_file)
            _age = (time.time() - _parse_ts(_sd.get("_meta", {}).get("ts", ""))) / 3600
            if _age < 14:
                _sleeve_key = {"kraken": "kraken", "sfm": "sfm", "alpaca": "alpaca"}.get(bot, "")
                _dir = _sd.get(f"{_sleeve_key}_directive", {})
                _posture = _dir.get("posture", "HOLD")
                _strat_mult = {"AGGRESSIVE": 1.2, "MODERATE": 0.8, "DEFENSIVE": 0.4, "HOLD": 1.0}.get(_posture, 1.0)
                if _strat_mult != 1.0:
                    size_mult = round(size_mult * _strat_mult, 2)
    except Exception:
        pass
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
    # Include dominant regime for dynamic exit floor.
    # If caller supplied an override (e.g., stock_regime for alpaca), use
    # that. Otherwise read the kraken-truth snapshot (crypto regime) for
    # backwards compatibility with kraken/sfm commands.
    if dominant_regime_override:
        cmd["dominant_regime"] = dominant_regime_override
    else:
        try:
            _truth = _read_json(os.path.join(BASE_DIR, "kraken_state_truth.json"))
            cmd["dominant_regime"] = _truth.get("regime", {}).get("dominant", "RANGING")
        except Exception:
            pass
    if trend_phase:
        cmd["trend_phase"] = trend_phase
        cmd["trend_phase_hours"] = round(trend_phase_hours, 1)
    if max_positions > 0:
        cmd["max_positions"] = max_positions
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cmd, f, indent=2)
        os.replace(tmp, path)
    except Exception as exc:
        log.error("[GOVERNOR] Failed to write command %s: %s", path, exc)


# ── Metric computation ────────────────────────────────────────────────

EXPECTANCY_DECAY_INTERVAL_SEC = 43200  # 12 hours — decay period
EXPECTANCY_DECAY_RATE = 0.20           # 20% decay per interval toward zero

EXPECTANCY_RECENCY_HALFLIFE = 10  # exits — weight halves every 10 exits back

def compute_rolling_expectancy(exits: List[dict], n: int = 20) -> float:
    """Compute rolling expectancy from last N trading exits.
    Excludes governor_force_flatten exits — those are deliberate capital
    preservation, not trading failures.

    RECENCY WEIGHTING: recent exits count more than old ones. Half-life
    of 10 exits means exit #20 (oldest) has ~25% the weight of exit #1
    (newest). A crash 3 days ago fades out as fresh wins replace it.

    DEADLOCK PREVENTION: If the most recent exit is older than
    EXPECTANCY_DECAY_INTERVAL_SEC, the raw expectancy decays toward 0
    by EXPECTANCY_DECAY_RATE per interval."""
    # Filter out force_flatten exits
    trading_exits = [e for e in exits if e.get("exit_reason") != "governor_force_flatten"]
    recent = trading_exits[-n:] if len(trading_exits) >= n else trading_exits
    if not recent:
        return 0.0

    # Recency-weighted expectancy: newest exit = weight 1.0, oldest = ~0.25
    import math
    _decay = math.log(2) / max(1, EXPECTANCY_RECENCY_HALFLIFE)
    total_weight = 0.0
    weighted_pnl = 0.0
    for i, e in enumerate(recent):
        age = len(recent) - 1 - i  # 0 = newest, len-1 = oldest
        w = math.exp(-_decay * age)
        pnl = e.get("pnl_usd", 0)
        weighted_pnl += pnl * w
        total_weight += w

    raw = weighted_pnl / total_weight if total_weight > 0 else 0.0

    # Time-decay: if no recent exits, decay negative expectancy toward 0
    if raw < 0 and recent:
        last_ts = recent[-1].get("ts", 0)
        if last_ts:
            age_sec = time.time() - last_ts
            if age_sec > EXPECTANCY_DECAY_INTERVAL_SEC:
                intervals = age_sec / EXPECTANCY_DECAY_INTERVAL_SEC
                decay_factor = (1 - EXPECTANCY_DECAY_RATE) ** intervals
                decayed = raw * decay_factor
                log.info("[GOVERNOR] Expectancy decay: raw=%.2f age=%.1fh intervals=%.1f -> decayed=%.2f",
                         raw, age_sec / 3600, intervals, decayed)
                return decayed
    return raw


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


# evaluate_kraken() REMOVED — enzobot retired/de-wired (D-063). Was the Kraken-sleeve evaluator
# (~245 lines: soft-retire/DEFENSE/SCOUT/NORMAL posture logic + kraken_cmd writes). 0 callers.


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

    # Regime-driven. supervisor_regime for alpaca is the STOCK regime
    # (F1 decoupling); pass as dominant_regime_override so the cmd file
    # doesn't inherit Kraken's crypto regime from kraken_state_truth.json.
    if regime_mode == "FLAT":
        decisions.append(GovernorDecision(
            ts=now_iso, cycle=cycle, action="FORCE_FLAT", sleeve="alpaca",
            reason=f"Regime={supervisor_regime} -> FLAT. Reduce all positions.",
            shadow=SHADOW_MODE, metrics=metrics,
        ))
        _write_command_file(CMD_ALPACA, "DEFENSE", 0.0, False,
                            f"Governor FLAT: {supervisor_regime}", "alpaca",
                            force_flatten=True, dominant_regime_override=supervisor_regime)
    elif regime_mode == "REDUCE":
        decisions.append(GovernorDecision(
            ts=now_iso, cycle=cycle, action="REDUCE_EXPOSURE", sleeve="alpaca",
            reason=f"Regime={supervisor_regime} -> REDUCE. No new entries.",
            shadow=SHADOW_MODE, metrics=metrics,
        ))
        _write_command_file(CMD_ALPACA, "SCOUT", 0.3, False,
                            f"Governor REDUCE: {supervisor_regime}", "alpaca",
                            dominant_regime_override=supervisor_regime)
    elif regime_mode == "TRADE":
        decisions.append(GovernorDecision(
            ts=now_iso, cycle=cycle, action="TRADE_ACTIVE", sleeve="alpaca",
            reason=f"Regime={supervisor_regime} -> TRADE.",
            shadow=SHADOW_MODE, metrics=metrics,
        ))
        _write_command_file(CMD_ALPACA, "NORMAL", 1.0, True,
                            f"Governor TRADE: {supervisor_regime}", "alpaca",
                            dominant_regime_override=supervisor_regime)
    elif regime_mode == "SCOUT":
        # D-053: SCOUT (RANGING / TRENDING_DOWN) was an unhandled dispatch gap that
        # fell through to the cautious default (entry_allowed=False) below — this
        # vetoed ALL alpaca entries from 2026-06-01 onward when stocks stopped
        # trending up. REGIME_BEHAVIOR already declares entries_allowed=True for
        # these regimes. Write NORMAL (clears engine sup_mode!=NORMAL veto) at
        # reduced size 0.3; the 8-state classifier still gates every entry.
        decisions.append(GovernorDecision(
            ts=now_iso, cycle=cycle, action="TRADE_ACTIVE", sleeve="alpaca",
            reason=f"Regime={supervisor_regime} -> SCOUT. Reduced-size entries allowed (trader-gated).",
            shadow=SHADOW_MODE, metrics=metrics,
        ))
        _write_command_file(CMD_ALPACA, "NORMAL", 0.3, True,
                            f"Governor SCOUT: {supervisor_regime} (reduced-size, trader-gated)", "alpaca",
                            dominant_regime_override=supervisor_regime)

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
                            f"Governor HOLD: default cautious", "alpaca",
                            dominant_regime_override=supervisor_regime)

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
                            f"Governor: Hermes DD override (DD={_alp_dd:.1f}%)", "alpaca",
                            dominant_regime_override=supervisor_regime)
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


def evaluate_zerobot(zerobot_state: dict, cycle: int, supervisor_regime: str,
                     hermes_advisory: dict = None) -> List[GovernorDecision]:
    """Evaluate ZeroBot sleeve. Operator-locked strategy — governor's role is
    mode-gating only, NO parameter tuning per spec §7.3.

    Per L-009 (Loophole D): zerobot is GUARANTEED paper regardless of user env vars.

    Per plan §4: ZeroBot's strategy has its own SMA-50 macro filter (gates entries
    when price < SMA-50). Crypto-regime TRENDING_DOWN would block exactly the
    contrarian breakouts the Donchian-20 rule is designed to catch. So governor
    is gentle: only force DEFENSE on FLAT/REDUCE/MIXED regimes; lets the strategy
    decide on TRENDING_UP / RANGING / TRENDING_DOWN / UNKNOWN.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    behavior = get_regime_behavior(supervisor_regime)
    regime_mode = behavior["mode"]

    metrics = {
        "equity": round(zerobot_state.get("equity", 0), 2),
        "open_positions": zerobot_state.get("open_positions", 0),
        "consecutive_losses": zerobot_state.get("consecutive_losses", 0),
        "dd_brake_active": zerobot_state.get("dd_brake_active", False),
        "regime": supervisor_regime,
        "regime_mode": regime_mode,
    }

    decisions = []

    # ZeroBot decision matrix (per plan §4 + REGIME_BEHAVIOR actual mappings):
    #   regime_mode == "REDUCE" (= VOLATILE regime)  -> ZEROBOT_SCOUT (block entries)
    #   else (TRENDING_UP/RANGING/TRENDING_DOWN/etc) -> ZEROBOT_TRADE_ACTIVE
    # Rationale: zerobot's own SMA-50 macro filter blocks entries in bear markets;
    # governor doesn't need to also block on TRENDING_DOWN (double-gating loses
    # exactly the contrarian Donchian-20 breakouts the rule is designed to catch,
    # e.g., 2020-03 bottom). The Universe DD circuit breaker (below) handles the
    # cross-sleeve cascade case automatically once zerobot is in SLEEVE_CMD_MAP.
    if regime_mode == "REDUCE":
        decisions.append(GovernorDecision(
            ts=now_iso, cycle=cycle, action="ZEROBOT_SCOUT", sleeve="zerobot",
            reason=f"Regime={supervisor_regime} (mode=REDUCE) -> SCOUT (block new entries; held positions ride out).",
            shadow=SHADOW_MODE, metrics=metrics,
        ))
        _write_command_file(CMD_ZEROBOT, "SCOUT", 0.5, False,
                            f"Governor SCOUT: regime={supervisor_regime}", "zerobot",
                            dominant_regime_override=supervisor_regime)
    else:
        # TRADE: governor signals NORMAL but the strategy's own gates still apply
        decisions.append(GovernorDecision(
            ts=now_iso, cycle=cycle, action="ZEROBOT_TRADE_ACTIVE", sleeve="zerobot",
            reason=f"Regime={supervisor_regime} -> NORMAL (strategy's own gates apply).",
            shadow=SHADOW_MODE, metrics=metrics,
        ))
        _write_command_file(CMD_ZEROBOT, "NORMAL", 1.0, True,
                            f"Governor NORMAL: regime={supervisor_regime}", "zerobot",
                            dominant_regime_override=supervisor_regime)

    # Hermes DD advisory override (tighten-only): mirrors alpaca pattern.
    # Currently hermes_context.compute_advisory() doesn't include a "zerobot" key
    # (Phase-3 prereq per Bug-3); .get("zerobot", {}) returns empty so no override fires.
    _zb_dd = zerobot_state.get("dd_pct", 0)
    _hermes_entry = (hermes_advisory or {}).get("zerobot", {}).get("entry_allowed", True)
    if not _hermes_entry:
        decisions.append(GovernorDecision(
            ts=now_iso, cycle=cycle, action="HERMES_DD_OVERRIDE", sleeve="zerobot",
            reason=f"Hermes advisory: entry_allowed=false (DD={_zb_dd:.1f}%) — tighten-only override",
            shadow=SHADOW_MODE, metrics=metrics,
        ))
        _write_command_file(CMD_ZEROBOT, "DEFENSE", 0.0, False,
                            f"Governor: Hermes DD override (DD={_zb_dd:.1f}%)", "zerobot",
                            dominant_regime_override=supervisor_regime)
        log.info("[GOVERNOR] ZeroBot Hermes DD override: entry_allowed=false (DD=%.1f%%)", _zb_dd)

    if decisions:
        actions = {d.action for d in decisions}
        if "HERMES_DD_OVERRIDE" in actions:
            decisions[0].classification = "OVERRIDE"
        elif "ZEROBOT_TRADE_ACTIVE" in actions:
            decisions[0].classification = "ALLOW"
        else:
            decisions[0].classification = "REDUCE"

    return decisions


# evaluate_driftbot() REMOVED — driftbot retired/de-wired (D-062, 2026-06-23)


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
    sfm = {}  # sfm RETIRED/de-wired (D-038): empty -> all governor sums add 0, no sfm_cmd written
    alpaca = _read_alpaca_state()
    zerobot = _read_zerobot_state()
    # driftbot read REMOVED — retired/de-wired (D-062)

    # Read Hermes context (advisory input — governor decides, Hermes advises)
    _hermes_ctx = _read_json(os.path.join(BASE_DIR, "hermes_context.json"))
    _hermes_advisory = _hermes_ctx.get("advisory", {})
    _brain_note = _hermes_advisory.get("note", "")

    # Read Opus strategic directive (12h review output — influences size_mult)
    _strategic = _read_json(os.path.join(BASE_DIR, "opus_strategic_directive.json"))
    _strat_ts = _strategic.get("_meta", {}).get("ts", "")
    _strat_age_h = (time.time() - _parse_ts(_strat_ts)) / 3600 if _strat_ts else 999
    if _strategic and _strat_age_h < 14:
        _a_dir = _strategic.get("alpaca_directive", {})  # kraken_directive dropped — enzobot retired (D-063); sfm — D-038
        _posture_map = {"AGGRESSIVE": 1.2, "MODERATE": 0.8, "DEFENSIVE": 0.4, "HOLD": 1.0}
        for _sleeve_key, _dir in [("alpaca", _a_dir)]:
            _posture = _dir.get("posture", "HOLD")
            _mult = _posture_map.get(_posture, 1.0)
            _hermes_advisory.setdefault(_sleeve_key, {})["strategic_size_mult"] = _mult
        log.info("[GOVERNOR] Strategic directive loaded (age=%.1fh): A=%s",
                 _strat_age_h, _a_dir.get("posture", "?"))

    # AUTHORITATIVE regime: Governor classifies from per-pair data (most granular).
    # Brain uses macro regime (RISK_ON/OFF) for advisory only — governor overrides.
    # No duplication conflict: governor decides, brain advises.
    #
    # Crypto regime (Kraken + SFM): from Kraken's pair_regime.
    # Stock regime (Alpaca): from Alpaca's own pair_regime. Decoupled from
    # crypto so Alpaca trades on stock-market state, not on BTC trend.
    # Falls back to RANGING (SCOUT / entries_allowed=True / size_mult=0.3)
    # if Alpaca hasn't reported a pair_regime yet -- safe default.
    kraken_pair_regime = enzo.get("pair_regime", {})
    crypto_regime = classify_dominant_regime(kraken_pair_regime)

    alpaca_pair_regime = alpaca.get("pair_regime", {})
    stock_regime = classify_dominant_regime(alpaca_pair_regime) if alpaca_pair_regime else "RANGING"

    # Kept as `dominant_regime` for any downstream caller expecting the old
    # name -- this remains the crypto-universe regime.
    dominant_regime = crypto_regime

    # Evaluate each sleeve with regime context.
    # Kraken SLEEVE evaluation REMOVED — enzobot retired/de-wired (D-063). The Kraken account is now a
    # regime MONITOR only (feeds crypto_regime to zerobot + kraken_state_truth); it no longer trades.
    # evaluate_sfm REMOVED — sfm retired/de-wired (D-038)
    all_decisions.extend(evaluate_alpaca(alpaca, cycle, stock_regime, _hermes_advisory))
    # ZeroBot: paper Donchian-20 BTC sleeve. Uses crypto_regime (BTC-driven)
    # but the strategy's own SMA-50 macro filter is the primary gate (per L-009/spec §7.3).
    all_decisions.extend(evaluate_zerobot(zerobot, cycle, crypto_regime, _hermes_advisory))
    # driftbot evaluation REMOVED — retired/de-wired (D-062)

    # Cross-sleeve correlation guard REMOVED — both crypto sleeves it guarded were kraken(enzobot)+sfm,
    # both retired/de-wired (D-063/D-038). No crypto trading sleeves remain to correlate.

    # ── Universe DD circuit breaker ──────────────────────────────────
    # If total universe equity drops >5% in any 4h window, all sleeves go DEFENSE.
    # D-052: enzo (kraken_crypto) dropped — shares the SAME Kraken account as zerobot (identical
    # live balances); counting both double-counted universe equity and could fire a phantom -43%
    # DEFENSE cascade. Kraken counted ONCE via zerobot.
    _total_eq_now = sfm.get("equity", 0) + alpaca.get("equity", 0) + zerobot.get("equity", 0)
    if not hasattr(run_governor, "_equity_history"):
        run_governor._equity_history = []
    run_governor._equity_history.append((_total_eq_now, time.time()))
    run_governor._equity_history = [(e, t) for e, t in run_governor._equity_history
                                    if time.time() - t < 14400]
    if len(run_governor._equity_history) >= 2:
        _oldest_eq, _oldest_ts = run_governor._equity_history[0]
        if _oldest_eq > 0:
            _uni_dd_4h = (_total_eq_now - _oldest_eq) / _oldest_eq * 100
            if _uni_dd_4h < -5.0:
                now_iso = datetime.now(timezone.utc).isoformat()
                log.warning("[GOVERNOR] UNIVERSE CIRCUIT BREAKER: equity dropped %.1f%% "
                            "in 4h ($%.2f -> $%.2f) — ALL DEFENSE", _uni_dd_4h, _oldest_eq, _total_eq_now)
                for _sleeve, _cmd_path in [("alpaca", CMD_ALPACA), ("zerobot", CMD_ZEROBOT)]:  # kraken removed — enzobot retired (D-063); sfm — D-038
                    _write_command_file(_cmd_path, "DEFENSE", 0.0, False,
                                        f"Governor: universe circuit breaker — {_uni_dd_4h:.1f}% in 4h",
                                        _sleeve, force_flatten=False)
                all_decisions.append(GovernorDecision(
                    ts=now_iso, cycle=cycle, action="UNIVERSE_CIRCUIT_BREAKER", sleeve="ALL",
                    reason=f"Universe equity {_uni_dd_4h:.1f}% in 4h — all DEFENSE",
                    shadow=SHADOW_MODE, metrics={},
                ))

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

    # Posture-scoring feedback loop REMOVED — it scored the kraken sleeve posture and fed
    # _adjust_regime_threshold (enzobot regime tuning); both retired with enzobot (D-063).

    # Write universe brief for Opus 12h review (kraken arg = account-monitor data)
    _write_universe_brief(all_decisions, enzo, sfm, alpaca, dominant_regime, _brain_note)

    # Write Kraken single source of truth — the crypto regime that governs zerobot's kernel check.
    # Re-homed (D-063): `enzo` now holds the kraken_account_monitor's regime, not enzobot's.
    _write_kraken_truth(enzo, all_decisions, dominant_regime)
    # _adjust_regime_threshold() REMOVED — tuned enzobot via kraken_cmd; enzobot retired (D-063)

    _last_governor_ts = time.time()
    return all_decisions

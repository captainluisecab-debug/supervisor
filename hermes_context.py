"""
hermes_context.py — HERMES: Universe Observer + Context Authority + Advisory Intelligence.

ROLE: Full observation authority across the entire universe. Learns from every
action, trade, exit, entry, regime change, and PnL movement. Provides advice
to Governor and Opus that improves bot functionality and PnL. Remembers,
organizes, tracks history, detects drift, preserves continuity.
Does NOT write command files. Does NOT take live execution control.
But advisory MUST be read and considered by Governor and Opus.
GOAL: Increase positive PnL. Protect capital. Reduce stupid losses.

Runs every supervisor cycle. Reads all state files across the universe,
maintains rolling context, and writes one consolidated hermes_context.json
that Opus reads every 12 hours instead of reconstructing from scattered files.

Also replaces the Brain's deterministic advisory function.

NO MODEL CALLS. NO API COST. Pure file reads + state tracking + structured output.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

log = logging.getLogger("hermes")

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
ENZOBOT_DIR = r"C:\Projects\enzobot"
SFMBOT_DIR  = r"C:\Projects\sfmbot"
ALPACA_DIR  = r"C:\Projects\alpacabot"

CONTEXT_FILE = os.path.join(BASE_DIR, "hermes_context.json")
HISTORY_FILE = os.path.join(BASE_DIR, "hermes_history.jsonl")
ESCALATION_FILE = os.path.join(BASE_DIR, "hermes_escalations.jsonl")
STATE_PERSIST_FILE = os.path.join(BASE_DIR, "hermes_state_persist.json")
EXEC_LOG = os.path.join(BASE_DIR, "execution_log.jsonl")

# ── Truth priority (documented per AUTHORITY_CONSTITUTION.md §4a):
# 1. execution_log.jsonl = execution truth (what actually happened)
# 2. commands/*.json = authority intent (what Governor commanded)
# 3. governor_decisions.jsonl = supervisory decision log
# 4. hermes_context.json = consolidated summary
# 5. Paperclip issues = loop/ownership state
# 6. raw run logs = deep forensic source

# Bot-to-sleeve mapping
_BOT_TO_SLEEVE = {"enzo": "kraken", "sfm": "sfm", "alpaca": "alpaca"}
_SLEEVE_CMD_PATHS = {
    "kraken": os.path.join(BASE_DIR, "commands", "kraken_cmd.json"),
    "sfm": os.path.join(BASE_DIR, "commands", "sfm_cmd.json"),
    "alpaca": os.path.join(BASE_DIR, "commands", "alpaca_cmd.json"),
}

# Rolling windows
_pnl_history: List[dict] = []       # [{ts, universe_eq, kraken_eq, sfm_eq, alpaca_eq}]
_regime_history: List[dict] = []     # [{ts, regime}]
_event_log: List[dict] = []          # [{ts, type, detail}] — significant events only
_execution_cache: List[dict] = []    # recent execution records
_violation_cache: List[dict] = []    # recent authority violations
_escalated_violation_keys: set = set()  # (ts, symbol) pairs already escalated — prevents repeated CRITICAL noise
_last_context_ts: float = 0


def _save_state():
    """Persist Hermes working memory to disk for restart recovery."""
    try:
        state = {
            "pnl_history": _pnl_history[-288:],
            "regime_history": _regime_history[-288:],
            "event_log": _event_log[-100:],
            "execution_cache": _execution_cache[-50:],
            "violation_cache": _violation_cache[-50:],
            "escalated_violation_keys": list(_escalated_violation_keys)[-200:],
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        tmp = STATE_PERSIST_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.replace(tmp, STATE_PERSIST_FILE)
    except Exception as exc:
        log.error("[HERMES] Failed to persist state: %s", exc)


def _load_state():
    """Reload Hermes working memory from disk on startup.
    Also bootstraps execution cache from execution_log.jsonl if persist file
    has sparse data, ensuring meaningful context immediately after restart."""
    global _pnl_history, _regime_history, _event_log, _execution_cache, _violation_cache, _escalated_violation_keys
    try:
        if os.path.exists(STATE_PERSIST_FILE):
            with open(STATE_PERSIST_FILE, encoding="utf-8") as f:
                state = json.load(f)
            _pnl_history = state.get("pnl_history", [])[-288:]
            _regime_history = state.get("regime_history", [])[-288:]
            _event_log = state.get("event_log", [])[-100:]
            _execution_cache = state.get("execution_cache", [])[-50:]
            _violation_cache = state.get("violation_cache", [])[-50:]
            _escalated_violation_keys = set(
                tuple(k) for k in state.get("escalated_violation_keys", [])
            )
            log.info("[HERMES] Restored state: %d pnl, %d regime, %d events, %d exec, %d violations, %d escalated keys",
                     len(_pnl_history), len(_regime_history), len(_event_log),
                     len(_execution_cache), len(_violation_cache), len(_escalated_violation_keys))
    except Exception as exc:
        log.warning("[HERMES] Could not load persisted state: %s — starting fresh", exc)

    # Bootstrap execution cache from execution_log if sparse
    if len(_execution_cache) < 10:
        try:
            boot = _read_jsonl_tail(EXEC_LOG, 50)
            if boot:
                _execution_cache = boot[-50:]
                log.info("[HERMES] Bootstrapped execution cache from execution_log: %d entries", len(_execution_cache))
        except Exception:
            pass


# Load state on module import
_load_state()


def _read_json(path: str) -> dict:
    try:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _read_jsonl_tail(path: str, n: int) -> list:
    try:
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        return [json.loads(l.strip()) for l in lines[-n:] if l.strip()]
    except Exception:
        return []


# ── Execution truth reader ────────────────────────────────────────────

def _read_execution_truth() -> dict:
    """Read execution_log.jsonl and reconcile against HISTORICAL command snapshots.
    Uses timestamped command_snapshots.jsonl to match each execution against
    the command state that existed at the time, not the current live file.
    This is the primary execution truth source per AUTHORITY_CONSTITUTION §4a."""
    global _execution_cache, _violation_cache

    try:
        from command_snapshots import find_command_at_time
    except ImportError:
        find_command_at_time = None

    raw = _read_jsonl_tail(EXEC_LOG, 50)
    buys = [e for e in raw if e.get("side") == "BUY"]
    sells = [e for e in raw if e.get("side") == "SELL"]
    force_flattens = [e for e in sells if "flatten" in (e.get("reason") or "").lower()]

    # Authority violation detection: BUY while command said entry_allowed=false
    # Uses historical snapshot if available, falls back to current command file
    violations = []
    for buy in buys:
        bot = buy.get("bot", "")
        sleeve = _BOT_TO_SLEEVE.get(bot, "")
        if not sleeve:
            continue
        buy_ts = buy.get("ts", "")

        # Try historical snapshot first (accurate), fall back to current file
        cmd = None
        source = "current"
        if find_command_at_time and buy_ts:
            cmd = find_command_at_time(sleeve, buy_ts)
            if cmd:
                source = "snapshot"
        if not cmd:
            cmd_path = _SLEEVE_CMD_PATHS.get(sleeve)
            if cmd_path:
                cmd = _read_json(cmd_path)

        if cmd and cmd.get("entry_allowed") is False:
            violations.append({
                "ts": buy_ts,
                "bot": bot,
                "sleeve": sleeve,
                "symbol": buy.get("symbol"),
                "side": "BUY",
                "size_usd": buy.get("size_usd"),
                "price": buy.get("price"),
                "reason": buy.get("reason"),
                "violation_type": "BUY_while_entry_blocked",
                "cmd_entry_allowed": False,
                "cmd_mode": cmd.get("mode"),
                "cmd_source": source,
                "cmd_snapshot_ts": cmd.get("snapshot_ts") or cmd.get("ts"),
            })

    # Update caches
    _execution_cache = raw[-50:]
    _violation_cache = (_violation_cache + violations)[-50:]

    # Time-window churn analysis (1h, 6h, 24h)
    now_iso = datetime.now(timezone.utc).isoformat()
    churn_windows = {}
    for window_name, hours in [("1h", 1), ("6h", 6), ("24h", 24)]:
        cutoff = (datetime.now(timezone.utc) - __import__("datetime").timedelta(hours=hours)).isoformat()
        w_buys = [e for e in buys if (e.get("ts") or "") >= cutoff]
        w_ff = [e for e in force_flattens if (e.get("ts") or "") >= cutoff]
        w_violations = [v for v in violations if (v.get("ts") or "") >= cutoff]
        w_ff_pnl = sum(e.get("pnl_usd", 0) for e in w_ff)
        # Repeated-entry loop: count BUYs followed by force_flatten for same symbol within window
        loop_count = 0
        ff_symbols = {e.get("symbol") for e in w_ff}
        for b in w_buys:
            if b.get("symbol") in ff_symbols:
                loop_count += 1
        churn_windows[window_name] = {
            "buys": len(w_buys),
            "force_flattens": len(w_ff),
            "unauthorized_entries": len(w_violations),
            "churn_pnl_drain": round(w_ff_pnl, 2),
            "repeated_entry_loops": loop_count,
        }

    # Reconciliation summary
    summary = {
        "total_executions": len(raw),
        "buys": len(buys),
        "sells": len(sells),
        "force_flattens": len(force_flattens),
        "violations_count": len(violations),
        "last_execution_ts": raw[-1].get("ts") if raw else None,
        "last_buy_ts": buys[-1].get("ts") if buys else None,
        "last_sell_ts": sells[-1].get("ts") if sells else None,
        "churn_windows": churn_windows,
    }

    return {
        "recent_executions": raw[-20:],
        "buys": buys[-10:],
        "sells": sells[-10:],
        "force_flattens": force_flattens[-5:],
        "authority_violations": violations[-10:],
        "reconciliation_summary": summary,
    }


# ── State readers ─────────────────────────────────────────────────────

def _read_kraken() -> dict:
    # Prefer the governor's truth file (single source)
    truth = _read_json(os.path.join(BASE_DIR, "kraken_state_truth.json"))
    if truth and truth.get("source") == "governor":
        return {
            "sleeve": "kraken",
            "equity": truth.get("portfolio", {}).get("equity", 0),
            "dd_pct": truth.get("portfolio", {}).get("dd_pct", 0),
            "cash": truth.get("portfolio", {}).get("cash", 0),
            "open_positions": truth.get("portfolio", {}).get("open_positions", 0),
            "brain_mode": truth.get("brain_mode", "?"),
            "effective_posture": truth.get("effective_posture", "?"),
            "force_flatten": truth.get("force_flatten", False),
            "regime": truth.get("regime", {}).get("dominant", "?"),
            "pair_regime": truth.get("regime", {}).get("pair_regime", {}),
        }
    # Fallback to direct reads
    feedback = _read_json(os.path.join(ENZOBOT_DIR, "supervisor_feedback.json"))
    brain = _read_json(os.path.join(ENZOBOT_DIR, "brain_state.json"))
    return {
        "sleeve": "kraken",
        "equity": feedback.get("portfolio", {}).get("equity", 0),
        "dd_pct": feedback.get("portfolio", {}).get("dd_pct", 0),
        "cash": feedback.get("portfolio", {}).get("cash", 0),
        "open_positions": feedback.get("portfolio", {}).get("open_positions", 0),
        "brain_mode": brain.get("active_mode", "?"),
        "effective_posture": "?",
        "force_flatten": False,
        "regime": "?",
        "pair_regime": feedback.get("pair_regime", {}),
    }


def _read_sfm() -> dict:
    feedback = _read_json(os.path.join(SFMBOT_DIR, "sfm_supervisor_feedback.json"))
    state = _read_json(os.path.join(SFMBOT_DIR, "solana_state.json"))
    # Multi-pair state: equity = usdc + sum of position costs
    usdc = float(state.get("usdc_balance", 0))
    sol_usd = float(state.get("sol_usd", 0))
    positions = state.get("positions", {})
    deployed = sum(float(p.get("cost_usd", 0)) for p in positions.values() if isinstance(p, dict))
    equity = usdc + sol_usd + deployed if (usdc + sol_usd + deployed) > 0 else feedback.get("equity", 0)
    from supervisor_settings import SFMBOT_BASELINE
    dd_pct = min(0.0, (equity - SFMBOT_BASELINE) / SFMBOT_BASELINE * 100) if SFMBOT_BASELINE > 0 else 0
    return {
        "sleeve": "sfm",
        "equity": equity,
        "dd_pct": dd_pct,
        "open_position": len(positions) > 0,
        "realized_pnl": state.get("realized_pnl_usd", 0),
        "total_trades": state.get("total_trades", 0),
        "winning_trades": state.get("winning_trades", 0),
    }


def _read_alpaca() -> dict:
    state = _read_json(os.path.join(ALPACA_DIR, "alpaca_state.json"))
    from supervisor_settings import ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASELINE
    equity = ALPACA_BASELINE + state.get("realized_pnl_usd", 0)
    try:
        from alpaca.trading.client import TradingClient
        client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY,
                               paper=ALPACA_API_KEY.startswith("PK"))
        acct = client.get_account()
        equity = float(acct.equity)
    except Exception:
        pass
    dd_pct = min(0.0, (equity - ALPACA_BASELINE) / ALPACA_BASELINE * 100) if ALPACA_BASELINE > 0 else 0
    return {
        "sleeve": "alpaca",
        "equity": equity,
        "dd_pct": dd_pct,
        "realized_pnl": state.get("realized_pnl_usd", 0),
        "total_trades": state.get("total_trades", 0),
        "winning_trades": state.get("winning_trades", 0),
        "losing_trades": state.get("losing_trades", 0),
        "open_positions": len(state.get("positions", {})),
    }


# ── Brain replacement: deterministic advisory ─────────────────────────

def _sleeve_advisory(regime_label: str, dd_pct: float, sleeve: str) -> dict:
    """Compute advisory for a single sleeve based on its own DD.
    SCOUT OFFENSE thresholds (2026-04-05): loosened to break DD catch-22.
    DEFENSE only on severe DD (<-12%) or RISK_OFF.
    SCOUT with reduced entries allowed between -5% and -12%.
    NORMAL with full entries above -5%."""
    if regime_label == "RISK_OFF" or dd_pct < -12:
        mode, size, entry = "DEFENSE", 0.0, False
    elif dd_pct < -5:
        mode, size, entry = "SCOUT", 0.3, True  # reduced size, entries ALLOWED
    elif regime_label == "RISK_ON" and dd_pct > -5:
        mode, size, entry = "NORMAL", 0.8, True
    else:
        mode, size, entry = "SCOUT", 0.5, True
    return {"mode": mode, "size_mult": size, "entry_allowed": entry,
            "reasoning": f"Hermes advisory: {regime_label}, {sleeve} DD {dd_pct:.1f}%"}


def compute_advisory(regime_label: str, kraken_dd: float,
                     sfm_dd: float = 0.0, alpaca_dd: float = 0.0) -> dict:
    """Per-sleeve deterministic advisory. Each sleeve uses its own DD."""
    k = _sleeve_advisory(regime_label, kraken_dd, "kraken")
    s = _sleeve_advisory(regime_label, sfm_dd, "sfm")
    a = _sleeve_advisory(regime_label, alpaca_dd, "alpaca")
    return {
        "kraken": k, "sfm": s, "alpaca": a,
        "note": f"Hermes advisory: {regime_label}, K={kraken_dd:.1f}% S={sfm_dd:.1f}% A={alpaca_dd:.1f}%",
    }


# ── Event detection ───────────────────────────────────────────────────

def _detect_events(kraken: dict, sfm: dict, alpaca: dict, regime: str,
                    execution_truth: dict = None) -> List[dict]:
    """Detect significant events worth logging. Only logs state CHANGES."""
    events = []
    now_iso = datetime.now(timezone.utc).isoformat()

    # Regime change
    if _regime_history and _regime_history[-1].get("regime") != regime:
        events.append({"ts": now_iso, "type": "regime_change",
                       "detail": f"{_regime_history[-1].get('regime')} -> {regime}"})

    # PnL milestone (every $25 change)
    if _pnl_history:
        last_eq = _pnl_history[-1].get("universe_eq", 0)
        curr_eq = kraken.get("equity", 0) + sfm.get("equity", 0) + alpaca.get("equity", 0)
        if abs(curr_eq - last_eq) >= 25:
            direction = "up" if curr_eq > last_eq else "down"
            events.append({"ts": now_iso, "type": "pnl_milestone",
                           "detail": f"Universe ${direction} ${abs(curr_eq - last_eq):.0f} ({last_eq:.0f} -> {curr_eq:.0f})"})

    # Position changes
    k_pos = kraken.get("open_positions", 0)
    if _pnl_history:
        prev_k_pos = _pnl_history[-1].get("kraken_positions", 0)
        if k_pos != prev_k_pos:
            events.append({"ts": now_iso, "type": "position_change",
                           "detail": f"Kraken positions: {prev_k_pos} -> {k_pos}"})

    # ── Escalation detection (urgent findings for Opus) ────────────────
    escalations = []
    curr_eq = kraken.get("equity", 0) + sfm.get("equity", 0) + alpaca.get("equity", 0)
    if _pnl_history and len(_pnl_history) >= 2:
        prev_eq = _pnl_history[-2].get("universe_eq", curr_eq)
        if curr_eq - prev_eq < -50:
            escalations.append({"severity": "HIGH", "type": "equity_drop",
                                "detail": f"Universe equity dropped ${abs(curr_eq - prev_eq):.0f} in one cycle ({prev_eq:.0f} -> {curr_eq:.0f})",
                                "ts": now_iso})
    if kraken.get("dd_pct", 0) < -10:
        escalations.append({"severity": "HIGH", "type": "kraken_dd_critical",
                            "detail": f"Kraken DD at {kraken.get('dd_pct', 0):.1f}% — below -10% threshold",
                            "ts": now_iso})
    if sfm.get("dd_pct", 0) < -10:
        escalations.append({"severity": "HIGH", "type": "sfm_dd_critical",
                            "detail": f"SFM DD at {sfm.get('dd_pct', 0):.1f}% — below -10% threshold",
                            "ts": now_iso})
    if alpaca.get("dd_pct", 0) < -10:
        escalations.append({"severity": "HIGH", "type": "alpaca_dd_critical",
                            "detail": f"Alpaca DD at {alpaca.get('dd_pct', 0):.1f}% — below -10% threshold",
                            "ts": now_iso})

    # Authority violation escalation — dedup against already-escalated violations
    # Belt-and-suspenders: check both _violation_cache AND _escalated_violation_keys
    # to prevent the same violations from generating repeated CRITICAL escalations.
    if execution_truth:
        violations = execution_truth.get("authority_violations", [])
        if violations:
            # Primary dedup: skip violations already in violation_cache
            cached_keys = {(v.get("ts"), v.get("symbol")) for v in _violation_cache}
            new_violations = [v for v in violations
                             if (v.get("ts"), v.get("symbol")) not in cached_keys]
            # Secondary dedup: skip violations already escalated (persists across restarts)
            new_violations = [v for v in new_violations
                             if (v.get("ts"), v.get("symbol")) not in _escalated_violation_keys]
            # Only count snapshot-verified violations as CRITICAL
            verified = [v for v in new_violations if v.get("cmd_source") == "snapshot"]
            unverified = [v for v in new_violations if v.get("cmd_source") != "snapshot"]
            if verified:
                escalations.append({"severity": "CRITICAL", "type": "authority_violation",
                                    "detail": f"{len(verified)} VERIFIED BUY(s) while entry_allowed=false: "
                                               f"{verified[0].get('symbol','?')} at {verified[0].get('ts','?')[:19]}",
                                    "ts": now_iso})
                for v in verified:
                    _escalated_violation_keys.add((v.get("ts"), v.get("symbol")))
            if unverified and not verified:
                # Log as INFO, not CRITICAL — no historical snapshot to confirm
                log.info("[HERMES] %d unverified violation(s) (no snapshot at execution time, "
                         "using current cmd state) — not escalating as CRITICAL", len(unverified))
                for v in unverified:
                    _escalated_violation_keys.add((v.get("ts"), v.get("symbol")))

    if escalations:
        try:
            with open(ESCALATION_FILE, "a", encoding="utf-8") as f:
                for esc in escalations:
                    f.write(json.dumps(esc) + "\n")
            for esc in escalations:
                log.warning("[HERMES] ESCALATION: %s — %s", esc["type"], esc["detail"])
        except Exception as exc:
            log.error("[HERMES] Failed to write escalation: %s", exc)

    return events


# ── Context builder ───────────────────────────────────────────────────

def build_context(regime_label: str, regime_confidence: float) -> dict:
    """Build the complete consolidated context. Called every supervisor cycle."""
    global _last_context_ts

    kraken = _read_kraken()
    sfm = _read_sfm()
    alpaca = _read_alpaca()

    universe_eq = kraken.get("equity", 0) + sfm.get("equity", 0) + alpaca.get("equity", 0)
    universe_pnl = universe_eq - 6969.62
    now = time.time()
    now_iso = datetime.now(timezone.utc).isoformat()

    # Track PnL history (keep last 288 entries = ~24h at 5min cycles)
    _pnl_history.append({
        "ts": now_iso, "universe_eq": round(universe_eq, 2),
        "kraken_eq": round(kraken.get("equity", 0), 2),
        "sfm_eq": round(sfm.get("equity", 0), 2),
        "alpaca_eq": round(alpaca.get("equity", 0), 2),
        "kraken_positions": kraken.get("open_positions", 0),
    })
    while len(_pnl_history) > 288:
        _pnl_history.pop(0)

    # Track regime history (keep last 288)
    _regime_history.append({"ts": now_iso, "regime": regime_label})
    while len(_regime_history) > 288:
        _regime_history.pop(0)

    # Read execution truth (reconcile intent vs reality)
    execution_truth = _read_execution_truth()

    # Detect events (including authority violations from execution truth)
    events = _detect_events(kraken, sfm, alpaca, regime_label, execution_truth)
    _event_log.extend(events)
    while len(_event_log) > 100:
        _event_log.pop(0)

    # Compute deltas
    pnl_1h_ago = None
    pnl_12h_ago = None
    for entry in _pnl_history:
        # ~12 entries ago = 1h, ~144 entries ago = 12h
        pass
    if len(_pnl_history) >= 12:
        pnl_1h_ago = _pnl_history[-12].get("universe_eq")
    if len(_pnl_history) >= 144:
        pnl_12h_ago = _pnl_history[-144].get("universe_eq")

    # ── Full universe observation — learn from every action ────────────
    # Governor decisions
    gov_decisions = _read_jsonl_tail(os.path.join(BASE_DIR, "governor_decisions.jsonl"), 20)

    # Posture outcomes (did the governor's posture produce good results?)
    posture_outcomes = _read_jsonl_tail(os.path.join(BASE_DIR, "governor_posture_outcomes.jsonl"), 10)

    # Kraken exits — learn from every exit (what worked, what didn't)
    kraken_exits = _read_jsonl_tail(os.path.join(ENZOBOT_DIR, "logs", "exit_counterfactuals.jsonl"), 100)
    kraken_exit_records = [e for e in kraken_exits if e.get("type") == "exit"]

    # Kraken blocked candidates — learn what entries were rejected and why
    blocked = _read_jsonl_tail(os.path.join(ENZOBOT_DIR, "logs", "blocked_candidates.jsonl"), 20)

    # SFM trade state
    sfm_state_full = _read_json(os.path.join(SFMBOT_DIR, "solana_state.json"))

    # Alpaca trade state
    alpaca_state_full = _read_json(os.path.join(ALPACA_DIR, "alpaca_state.json"))

    # Opus review memory
    opus_memory = _read_json(os.path.join(BASE_DIR, "opus_review_memory.json"))

    # ── Generate advisory insights from observations ────────────────
    insights = []

    # Insight: exit quality
    if kraken_exit_records:
        recent_exits = kraken_exit_records[-10:]
        wins = sum(1 for e in recent_exits if e.get("pnl_usd", 0) > 0)
        losses = sum(1 for e in recent_exits if e.get("pnl_usd", 0) < 0)
        avg_pnl = sum(e.get("pnl_usd", 0) for e in recent_exits) / len(recent_exits)
        if losses > wins * 2:
            insights.append(f"CONCERN: last 10 exits have {losses} losses vs {wins} wins (avg ${avg_pnl:.2f})")
        exit_reasons = {}
        for e in recent_exits:
            r = e.get("exit_reason", "?")
            exit_reasons[r] = exit_reasons.get(r, 0) + 1
        top_reason = max(exit_reasons, key=exit_reasons.get) if exit_reasons else "?"
        insights.append(f"Top exit reason: {top_reason} ({exit_reasons.get(top_reason, 0)}/{len(recent_exits)})")
        kraken_total = len(kraken_exit_records)
        kraken_wins = sum(1 for e in kraken_exit_records if e.get("pnl_usd", 0) > 0)
        insights.append(f"Kraken: {kraken_wins}/{kraken_total} wins ({kraken_wins/kraken_total*100:.0f}%)")

    # Insight: blocking patterns
    if blocked:
        block_reasons = {}
        for b in blocked[-20:]:
            r = b.get("block_reason", "?")
            block_reasons[r] = block_reasons.get(r, 0) + 1
        top_block = max(block_reasons, key=block_reasons.get) if block_reasons else "?"
        insights.append(f"Top entry blocker: {top_block} ({block_reasons.get(top_block, 0)}/20)")

    # Insight: posture accuracy
    if posture_outcomes:
        recent_postures = posture_outcomes[-5:]
        correct = sum(1 for p in recent_postures if p.get("verdict") == "CORRECT")
        wrong = sum(1 for p in recent_postures if p.get("verdict") == "WRONG")
        if wrong > correct:
            insights.append(f"CONCERN: governor posture was WRONG {wrong}/{len(recent_postures)} times recently")

    # Insight: SFM readiness
    sfm_trades = sfm_state_full.get("total_trades", 0)
    sfm_wins = sfm_state_full.get("winning_trades", 0)
    if sfm_trades > 0:
        insights.append(f"SFM: {sfm_wins}/{sfm_trades} wins ({sfm_wins/sfm_trades*100:.0f}%)")

    # Insight: Alpaca quality
    alp_trades = alpaca_state_full.get("total_trades", 0)
    alp_wins = alpaca_state_full.get("winning_trades", 0)
    if alp_trades > 0:
        insights.append(f"Alpaca: {alp_wins}/{alp_trades} wins ({alp_wins/alp_trades*100:.0f}%)")

    # Build advisory (replaces Brain)
    advisory = compute_advisory(
        regime_label,
        kraken_dd=kraken.get("dd_pct", 0),
        sfm_dd=sfm.get("dd_pct", 0),
        alpaca_dd=alpaca.get("dd_pct", 0),
    )

    context = {
        "ts": now_iso,
        "cycle_source": "hermes_context",

        # Universe snapshot
        "universe": {
            "equity": round(universe_eq, 2),
            "pnl_vs_baseline": round(universe_pnl, 2),
            "pnl_pct": round(universe_pnl / 6969.62 * 100, 2),
            "delta_1h": round(universe_eq - pnl_1h_ago, 2) if pnl_1h_ago else None,
            "delta_12h": round(universe_eq - pnl_12h_ago, 2) if pnl_12h_ago else None,
        },

        # Per-sleeve state
        "kraken": kraken,
        "sfm": sfm,
        "alpaca": alpaca,

        # Regime
        "regime": {
            "label": regime_label,
            "confidence": regime_confidence,
        },

        # Brain replacement advisory
        "advisory": advisory,

        # Recent events (state changes only)
        "recent_events": _event_log[-20:],

        # Governor decisions (last 10)
        "governor_decisions": [
            {"action": d.get("action"), "sleeve": d.get("sleeve"), "reason": d.get("reason", "")[:80]}
            for d in gov_decisions if d.get("action") not in ("HOLD", "HOLD_FLAT")
        ][-10:],

        # Posture outcome feedback
        "posture_outcomes": posture_outcomes[-5:],

        # ── Full universe observation data ────────────────────────
        "observation": {
            "kraken_recent_exits": [
                {"reason": e.get("exit_reason"), "pnl": e.get("pnl_usd"), "pair": e.get("pair")}
                for e in kraken_exit_records[-10:]
            ],
            "kraken_recent_blocks": [
                {"pair": b.get("pair"), "reason": b.get("block_reason"), "score": b.get("score")}
                for b in blocked[-10:]
            ],
            "sfm_win_rate": f"{sfm_wins}/{sfm_trades}" if sfm_trades else "0/0",
            "alpaca_win_rate": f"{alp_wins}/{alp_trades}" if alp_trades else "0/0",
        },

        # ── Hermes advisory insights (learned from observation) ───
        "hermes_insights": insights,

        # ── Execution truth (reconciled intent vs reality) ────────
        "execution_truth": {
            "recent_executions": execution_truth["recent_executions"],
            "recent_buys": execution_truth["buys"],
            "recent_sells": execution_truth["sells"],
            "force_flattens": execution_truth["force_flattens"],
            "authority_violations": execution_truth["authority_violations"],
            "reconciliation_summary": execution_truth["reconciliation_summary"],
        },

        # Opus review memory (carried forward)
        "opus_memory": {
            "cycle_count": opus_memory.get("cycle_count", 0),
            "issues_active": opus_memory.get("issues_active", []),
            "issues_fixed": opus_memory.get("issues_fixed", []),
            "last_regime": opus_memory.get("last_regime"),
        },
    }

    # Write context file
    try:
        tmp = CONTEXT_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(context, f, indent=2)
        os.replace(tmp, CONTEXT_FILE)
    except Exception as exc:
        log.error("[HERMES] Failed to write context: %s", exc)

    # Log significant events
    for e in events:
        log.info("[HERMES] EVENT: %s — %s", e["type"], e["detail"])

    # Log advisory insights (Hermes observes and advises)
    for insight in insights:
        log.info("[HERMES] INSIGHT: %s", insight)

    _last_context_ts = now

    # Persist working memory to disk (survives restarts)
    _save_state()

    return context

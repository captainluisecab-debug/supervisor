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

# Rolling windows
_pnl_history: List[dict] = []       # [{ts, universe_eq, kraken_eq, sfm_eq, alpaca_eq}]
_regime_history: List[dict] = []     # [{ts, regime}]
_event_log: List[dict] = []          # [{ts, type, detail}] — significant events only
_last_context_ts: float = 0


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
    state = _read_json(os.path.join(SFMBOT_DIR, "sfm_state.json"))
    return {
        "sleeve": "sfm",
        "equity": feedback.get("equity", 0),
        "dd_pct": feedback.get("dd_pct", 0),
        "open_position": feedback.get("open_position", False),
        "realized_pnl": state.get("realized_pnl_usd", 0),
        "total_trades": state.get("total_trades", 0),
        "winning_trades": state.get("winning_trades", 0),
    }


def _read_alpaca() -> dict:
    state = _read_json(os.path.join(ALPACA_DIR, "alpaca_state.json"))
    return {
        "sleeve": "alpaca",
        "equity": 500 + state.get("realized_pnl_usd", 0),
        "realized_pnl": state.get("realized_pnl_usd", 0),
        "total_trades": state.get("total_trades", 0),
        "winning_trades": state.get("winning_trades", 0),
        "losing_trades": state.get("losing_trades", 0),
        "open_positions": len(state.get("positions", {})),
    }


# ── Brain replacement: deterministic advisory ─────────────────────────

def _sleeve_advisory(regime_label: str, dd_pct: float, sleeve: str) -> dict:
    """Compute advisory for a single sleeve based on its own DD."""
    if regime_label == "RISK_OFF" or dd_pct < -5:
        mode, size, entry = "DEFENSE", 0.3, False
    elif regime_label == "RISK_ON" and dd_pct > -3:
        mode, size, entry = "NORMAL", 0.8, True
    else:
        mode, size, entry = "SCOUT", 0.5, False
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

def _detect_events(kraken: dict, sfm: dict, alpaca: dict, regime: str) -> List[dict]:
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

    # Detect events
    events = _detect_events(kraken, sfm, alpaca, regime_label)
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
    kraken_exits = _read_jsonl_tail(os.path.join(ENZOBOT_DIR, "logs", "exit_counterfactuals.jsonl"), 20)
    kraken_exit_records = [e for e in kraken_exits if e.get("type") == "exit"]

    # Kraken blocked candidates — learn what entries were rejected and why
    blocked = _read_jsonl_tail(os.path.join(ENZOBOT_DIR, "logs", "blocked_candidates.jsonl"), 20)

    # SFM trade state
    sfm_state_full = _read_json(os.path.join(SFMBOT_DIR, "sfm_state.json"))

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
        alpaca_dd=(alpaca.get("equity", 500) - 500) / 500 * 100 if alpaca.get("equity", 500) < 500 else 0,
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
    return context

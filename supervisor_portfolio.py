"""
supervisor_portfolio.py — Read all bot states and compute portfolio metrics.

Phase 1: read-only. No writes to bot files.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from supervisor_settings import (
    ALPACA_API_KEY, ALPACA_BASELINE, ALPACA_SECRET_KEY, ALPACA_STATE,
    ENZOBOT_BASELINE, ENZOBOT_BRAIN, ENZOBOT_STATE,
    SFMBOT_BASELINE, SFMBOT_STATE, TOTAL_BASELINE,
)

log = logging.getLogger("supervisor_portfolio")


@dataclass
class SleeveState:
    name: str
    equity_usd: float
    baseline_usd: float
    pnl_usd: float
    pnl_pct: float
    drawdown_pct: float        # from sleeve peak
    open_positions: int
    mode: str                  # bot's current operating mode
    cycle: int
    health: str                # GOOD / WARN / CRITICAL
    notes: List[str] = field(default_factory=list)


@dataclass
class PortfolioState:
    total_equity: float
    total_baseline: float
    total_pnl_usd: float
    total_pnl_pct: float
    total_dd_pct: float        # from total peak (tracked in history)
    sleeves: Dict[str, SleeveState]
    kill_switch_active: bool
    emergency_stop: bool


def _read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        log.warning("Could not read %s: %s", path, exc)
        return {}


def _health(pnl_pct: float, dd_pct: float) -> str:
    if dd_pct < -8 or pnl_pct < -10:
        return "CRITICAL"
    if dd_pct < -4 or pnl_pct < -5:
        return "WARN"
    return "GOOD"


def read_enzobot() -> SleeveState:
    state = _read_json(ENZOBOT_STATE)
    brain = _read_json(ENZOBOT_BRAIN)

    cash    = float(state.get("cash", ENZOBOT_BASELINE))
    pos     = state.get("positions", {})
    # Estimate equity: cash + sum of position values (mark at cost if no price)
    pos_value = sum(
        float(p.get("qty", 0)) * float(p.get("last_price") or p.get("avg_price") or 0)
        for p in pos.values()
        if float(p.get("qty", 0)) > 0
    ) if isinstance(pos, dict) else 0.0
    equity = cash + pos_value if pos_value > 0 else cash

    # Fallback: use realized_pnl + baseline
    if equity <= 0 or equity == ENZOBOT_BASELINE:
        rpnl = float(state.get("realized_pnl", 0))
        equity = ENZOBOT_BASELINE + rpnl

    pnl_usd  = equity - ENZOBOT_BASELINE
    pnl_pct  = pnl_usd / ENZOBOT_BASELINE * 100
    # Compute dd_pct from equity and equity_peak (state.json has no "drawdown_pct" field)
    eq_peak  = float(state.get("equity_peak", ENZOBOT_BASELINE))
    dd_pct   = ((equity - eq_peak) / eq_peak * 100) if eq_peak > 0 else 0.0
    mode     = brain.get("active_mode", "UNKNOWN")
    # brain_state.json uses "last_change_cycle" not "cycle"
    cycle    = int(brain.get("last_change_cycle", state.get("cycle", 0)))
    open_ct  = sum(1 for p in pos.values() if float(p.get("qty", 0)) > 0) if isinstance(pos, dict) else 0

    notes = []
    if mode == "DEFEND":
        notes.append("Brain in DEFEND — capital protection active")
    if dd_pct < -5:
        notes.append(f"Drawdown {dd_pct:.1f}% — monitor closely")

    return SleeveState(
        name="kraken_crypto",
        equity_usd=equity,
        baseline_usd=ENZOBOT_BASELINE,
        pnl_usd=pnl_usd,
        pnl_pct=pnl_pct,
        drawdown_pct=dd_pct,
        open_positions=open_ct,
        mode=mode,
        cycle=cycle,
        health=_health(pnl_pct, dd_pct),
        notes=notes,
    )


def read_sfmbot() -> SleeveState:
    state = _read_json(SFMBOT_STATE)
    if not state:
        return SleeveState("sfm_tactical", SFMBOT_BASELINE, SFMBOT_BASELINE,
                           0, 0, 0, 0, "UNKNOWN", 0, "GOOD",
                           ["State file not found — bot may not have run yet"])

    usdc    = float(state.get("usdc_balance", SFMBOT_BASELINE))
    pos     = state.get("position")
    # SFM position value is not tracked in USD in state — use cost as proxy
    pos_val = float(pos.get("cost_usd", 0)) if pos else 0.0
    equity  = usdc + pos_val
    rpnl    = float(state.get("realized_pnl_usd", 0))
    pnl_usd = rpnl  # realized only (unrealized not tracked in state)
    pnl_pct = pnl_usd / SFMBOT_BASELINE * 100
    cycle   = int(state.get("cycle", 0))
    open_ct = 1 if pos else 0

    notes = []
    if open_ct:
        notes.append(f"Open SFM position: {pos.get('sfm_qty',0):,.0f} tokens")
    notes.append("Liquidity: $40k — max $100 per trade")

    return SleeveState(
        name="sfm_tactical",
        equity_usd=equity,
        baseline_usd=SFMBOT_BASELINE,
        pnl_usd=pnl_usd,
        pnl_pct=pnl_pct,
        drawdown_pct=0.0,      # not tracked by sfmbot
        open_positions=open_ct,
        mode="PAPER",
        cycle=cycle,
        health=_health(pnl_pct, 0),
        notes=notes,
    )


def read_alpacabot() -> SleeveState:
    local = _read_json(ALPACA_STATE)

    # Try live Alpaca account first
    equity = 0.0
    open_ct = 0
    try:
        from alpaca.trading.client import TradingClient
        client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)
        account   = client.get_account()
        positions = client.get_all_positions()
        equity  = float(account.equity)
        open_ct = len(positions)
    except Exception as exc:
        log.warning("Alpaca live read failed: %s — using local state", exc)
        equity  = ALPACA_BASELINE + float(local.get("realized_pnl_usd", 0))
        open_ct = len(local.get("positions", {}))

    pnl_usd = equity - ALPACA_BASELINE
    pnl_pct = pnl_usd / ALPACA_BASELINE * 100
    cycle   = int(local.get("cycle", 0))
    rpnl    = float(local.get("realized_pnl_usd", 0))

    notes = []
    if open_ct == 0:
        notes.append("Flat — waiting for market hours / signal")

    return SleeveState(
        name="alpaca_stocks",
        equity_usd=equity,
        baseline_usd=ALPACA_BASELINE,
        pnl_usd=pnl_usd,
        pnl_pct=pnl_pct,
        drawdown_pct=0.0,
        open_positions=open_ct,
        mode="PAPER",
        cycle=cycle,
        health=_health(pnl_pct, 0),
        notes=notes,
    )


def build_portfolio(peak_equity: float = 0.0) -> PortfolioState:
    sleeves = {
        "kraken_crypto": read_enzobot(),
        "sfm_tactical":  read_sfmbot(),
        "alpaca_stocks": read_alpacabot(),
    }

    total_equity = sum(s.equity_usd for s in sleeves.values())
    total_pnl    = total_equity - TOTAL_BASELINE
    total_pnl_pct = total_pnl / TOTAL_BASELINE * 100

    effective_peak = max(peak_equity, total_equity, TOTAL_BASELINE)
    dd_pct = (total_equity - effective_peak) / effective_peak * 100 if effective_peak > 0 else 0.0

    from supervisor_settings import KILL_SWITCH_DD_PCT, STOP_FILE
    kill_switch = dd_pct <= -KILL_SWITCH_DD_PCT
    emergency   = os.path.exists(STOP_FILE)

    return PortfolioState(
        total_equity=total_equity,
        total_baseline=TOTAL_BASELINE,
        total_pnl_usd=total_pnl,
        total_pnl_pct=total_pnl_pct,
        total_dd_pct=dd_pct,
        sleeves=sleeves,
        kill_switch_active=kill_switch,
        emergency_stop=emergency,
    )

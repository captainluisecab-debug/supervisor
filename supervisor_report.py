"""
supervisor_report.py — Generate portfolio report and Phase 1 recommendations.

Phase 1: OBSERVE ONLY. Recommendations are advisory — no bot files are written.
Phase 2 (future): supervisor will write mode files each bot reads.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from supervisor_settings import HISTORY_FILE, REPORT_FILE, STOP_FILE
from supervisor_portfolio import PortfolioState, SleeveState
from supervisor_regime import RegimeSnapshot

log = logging.getLogger("supervisor_report")


# ── Recommendation engine ────────────────────────────────────────────

def _recommend_mode(sleeve: SleeveState, regime: str, portfolio_dd: float) -> str:
    """Determine what mode we WOULD assign this sleeve (advisory only in Phase 1)."""
    # Emergency conditions always → DEFENSE
    if portfolio_dd <= -10.0:
        return "DEFENSE"
    if sleeve.health == "CRITICAL":
        return "DEFENSE"

    # Regime-based
    if regime == "RISK_OFF":
        if sleeve.health == "WARN":
            return "DEFENSE"
        return "SCOUT"
    if regime == "NEUTRAL":
        if sleeve.health == "GOOD":
            return "NORMAL"
        return "SCOUT"
    if regime == "RISK_ON":
        if sleeve.health == "GOOD":
            return "NORMAL"
        return "SCOUT"

    return "SCOUT"


def _recommend_size_mult(sleeve: SleeveState, regime: str, portfolio_dd: float) -> float:
    """Size multiplier 0.0–1.0 we WOULD recommend."""
    base = {"RISK_ON": 1.0, "NEUTRAL": 0.7, "RISK_OFF": 0.4}.get(regime, 0.7)
    health_adj = {"GOOD": 1.0, "WARN": 0.6, "CRITICAL": 0.0}.get(sleeve.health, 0.7)
    dd_adj = max(0.0, 1.0 - abs(min(portfolio_dd, 0)) / 10.0)
    return round(base * health_adj * dd_adj, 2)


def _portfolio_alert(portfolio: PortfolioState) -> list:
    alerts = []
    if portfolio.emergency_stop:
        alerts.append("EMERGENCY_STOP.txt detected — all bots should halt")
    if portfolio.kill_switch_active:
        alerts.append(f"KILL SWITCH: portfolio DD {portfolio.total_dd_pct:.1f}% exceeds -10% threshold")
    for name, sleeve in portfolio.sleeves.items():
        if sleeve.health == "CRITICAL":
            alerts.append(f"{name} CRITICAL — drawdown {sleeve.drawdown_pct:.1f}%")
    return alerts


# ── Report builder ───────────────────────────────────────────────────

def build_report(
    portfolio: PortfolioState,
    regime: RegimeSnapshot,
    cycle: int,
    peak_equity: float,
) -> dict:

    now = datetime.now(timezone.utc).isoformat()
    alerts = _portfolio_alert(portfolio)

    recommendations = {}
    for name, sleeve in portfolio.sleeves.items():
        rec_mode = _recommend_mode(sleeve, regime.regime, portfolio.total_dd_pct)
        rec_size = _recommend_size_mult(sleeve, regime.regime, portfolio.total_dd_pct)
        recommendations[name] = {
            "advisory_mode":      rec_mode,
            "advisory_size_mult": rec_size,
            "current_mode":       sleeve.mode,
            "health":             sleeve.health,
            "notes":              sleeve.notes,
        }

    report = {
        "ts":    now,
        "cycle": cycle,
        "phase": "1-OBSERVE",

        "regime": {
            "classification": regime.regime,
            "confidence":     round(regime.confidence, 2),
            "btc_7d_pct":     round(regime.btc_7d_pct, 2),
            "btc_price_usd":  round(regime.btc_price, 2),
            "spy_vol_10d_pct": round(regime.spy_vol_10d, 3),
            "spy_price_usd":  round(regime.spy_price, 2),
            "notes":          regime.notes,
        },

        "portfolio": {
            "total_equity_usd":  round(portfolio.total_equity, 2),
            "total_baseline_usd": round(portfolio.total_baseline, 2),
            "total_pnl_usd":     round(portfolio.total_pnl_usd, 2),
            "total_pnl_pct":     round(portfolio.total_pnl_pct, 2),
            "total_dd_pct":      round(portfolio.total_dd_pct, 2),
            "peak_equity_usd":   round(peak_equity, 2),
            "kill_switch_active": portfolio.kill_switch_active,
            "emergency_stop":    portfolio.emergency_stop,
        },

        "sleeves": {
            name: {
                "equity_usd":     round(s.equity_usd, 2),
                "baseline_usd":   round(s.baseline_usd, 2),
                "pnl_usd":        round(s.pnl_usd, 2),
                "pnl_pct":        round(s.pnl_pct, 2),
                "drawdown_pct":   round(s.drawdown_pct, 2),
                "open_positions": s.open_positions,
                "mode":           s.mode,
                "cycle":          s.cycle,
                "health":         s.health,
            }
            for name, s in portfolio.sleeves.items()
        },

        "recommendations": recommendations,   # ADVISORY ONLY in Phase 1
        "alerts": alerts,
    }

    return report


def save_report(report: dict) -> None:
    """Write latest report + append to history log."""
    try:
        with open(REPORT_FILE, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
    except Exception as exc:
        log.error("Failed to write report: %s", exc)

    try:
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(report, separators=(",", ":")) + "\n")
    except Exception as exc:
        log.error("Failed to append history: %s", exc)

"""
supervisor.py — Master Supervisor v1 | Phase 1: OBSERVE

Runs every CYCLE_SEC. Reads all bot states, classifies global regime,
computes portfolio metrics, writes advisory report. Does NOT control bots.

This is the foundation. After 60 days of observation the data here
will inform Phase 2 (soft control via mode files).

Run:
    python supervisor.py
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

# ── Logging ──────────────────────────────────────────────────────────
os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs"), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s][SUPERVISOR] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "supervisor.log"),
            encoding="utf-8",
        ),
    ],
)
log = logging.getLogger("supervisor")

from supervisor_settings import CYCLE_SEC, STOP_FILE, TOTAL_BASELINE
from supervisor_portfolio import build_portfolio
from supervisor_regime import classify_regime
from supervisor_report import build_report, save_report


def _load_peak() -> float:
    """Load tracked portfolio peak from last report."""
    from supervisor_settings import REPORT_FILE
    try:
        with open(REPORT_FILE, encoding="utf-8") as f:
            r = json.load(f)
        return float(r.get("portfolio", {}).get("peak_equity_usd", TOTAL_BASELINE))
    except Exception:
        return TOTAL_BASELINE


def _run_cycle(cycle: int, peak_equity: float) -> float:
    log.info("── CYCLE %d ──────────────────────────────────────", cycle)

    # Emergency stop check
    if os.path.exists(STOP_FILE):
        log.warning("EMERGENCY_STOP.txt detected — reporting only, no actions in Phase 1")

    # 1. Portfolio state
    portfolio = build_portfolio(peak_equity)
    new_peak  = max(peak_equity, portfolio.total_equity)

    log.info(
        "Portfolio: equity=$%.2f pnl=$%+.2f (%.2f%%) dd=%.2f%%",
        portfolio.total_equity, portfolio.total_pnl_usd,
        portfolio.total_pnl_pct, portfolio.total_dd_pct,
    )

    for name, sleeve in portfolio.sleeves.items():
        log.info(
            "  %-18s eq=$%.2f pnl=$%+.2f (%.1f%%) mode=%-8s health=%s",
            name, sleeve.equity_usd, sleeve.pnl_usd, sleeve.pnl_pct,
            sleeve.mode, sleeve.health,
        )

    # 2. Regime
    log.info("Fetching macro regime...")
    regime = classify_regime()
    log.info(
        "Regime: %s (conf=%.0f%%) BTC_7d=%.1f%% SPY_vol=%.2f%%",
        regime.regime, regime.confidence * 100,
        regime.btc_7d_pct, regime.spy_vol_10d,
    )

    # 3. Report
    report = build_report(portfolio, regime, cycle, new_peak)
    save_report(report)

    # 4. Log alerts + recommendations
    if report["alerts"]:
        for alert in report["alerts"]:
            log.warning("ALERT: %s", alert)

    if portfolio.kill_switch_active:
        log.warning(
            "KILL SWITCH WOULD FIRE — portfolio DD %.1f%% exceeds threshold "
            "(Phase 1: advisory only — no bot control yet)",
            portfolio.total_dd_pct,
        )

    for name, rec in report["recommendations"].items():
        if rec["advisory_mode"] != rec["current_mode"]:
            log.info(
                "  ADVISORY [%s]: current=%s → recommended=%s (size=%.1fx)",
                name, rec["current_mode"], rec["advisory_mode"], rec["advisory_size_mult"],
            )

    log.info("Report saved → supervisor_report.json")
    return new_peak


def main() -> None:
    log.info("=" * 65)
    log.info("MASTER SUPERVISOR v1 — Phase 1: OBSERVE")
    log.info("Total baseline: $%.2f across 3 sleeves", TOTAL_BASELINE)
    log.info("Cycle: %ds | Mode: READ-ONLY (no bot control)", CYCLE_SEC)
    log.info("Kill switch: portfolio DD > 10%% (advisory only in Phase 1)")
    log.info("=" * 65)
    log.info("Sleeves:")
    log.info("  kraken_crypto  — core growth engine    (enzobot)")
    log.info("  sfm_tactical   — tactical booster      (sfmbot)")
    log.info("  alpaca_stocks  — stable compounder     (alpacabot)")
    log.info("=" * 65)

    peak_equity = _load_peak()
    cycle = 0

    while True:
        cycle += 1
        try:
            peak_equity = _run_cycle(cycle, peak_equity)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            log.error("[CYCLE %d] Error: %s", cycle, exc, exc_info=True)
        time.sleep(CYCLE_SEC)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Supervisor stopped.")

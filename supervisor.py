"""
supervisor.py — Master Supervisor v2 | Phase 2: UNIFIED CLAUDE BRAIN

Runs every CYCLE_SEC. Every BRAIN_INTERVAL_CYCLES calls Claude with full
portfolio + regime context. Claude assigns mode + size_mult to each bot.
Writes command files each bot reads every cycle.

Phase 2: Claude now controls all three bots through command files.
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

# Force UTF-8 on stdout — Windows services default to cp1252 which breaks Unicode chars
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

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

from supervisor_settings import (
    BRAIN_INTERVAL_CYCLES, CYCLE_SEC, HISTORY_FILE,
    REPORT_FILE, STOP_FILE, TOTAL_BASELINE,
)
from supervisor_portfolio import build_portfolio
from supervisor_regime import classify_regime
from supervisor_report import build_report, save_report
from supervisor_allocation import compute_allocations
from supervisor_memory import load_recent_outcomes
from supervisor_morning_brief import should_fire, fire_morning_brief
from supervisor_signals import get_sentiment_signals
from supervisor_correlation import check_correlation
from supervisor_calendar import get_calendar
from supervisor_anomaly import AnomalyDetector
from supervisor_selfheal import run_selfheal
from supervisor_governor import run_governor
from supervisor_kernel import run_kernel
from hermes_context import build_context, compute_advisory
from paperclip_bridge import run_bridge
from command_snapshots import snapshot_commands


def _dynamic_brain_interval(regime, portfolio) -> int:
    """
    Compute how frequently Claude should fire based on current conditions.

    Normal market:        every 6 cycles = ~30 min (BRAIN_INTERVAL_CYCLES)
    Elevated volatility:  every 3 cycles = ~15 min
    High stress:          every 2 cycles = ~10 min
    Crisis / FOMC day:    every cycle    = ~5 min

    This ensures Claude responds faster when markets are moving fast.
    """
    vix = getattr(regime, "vix", 0.0)
    dd  = portfolio.total_dd_pct

    # Crisis conditions — fire every cycle
    if dd < -8.0 or vix > 35:
        return 1

    # High stress — fire every 2 cycles
    if dd < -5.0 or vix > 28:
        return 2

    # Elevated — fire every 3 cycles
    if dd < -3.0 or vix > 23:
        return 3

    # Normal
    return BRAIN_INTERVAL_CYCLES


def _load_peak() -> float:
    try:
        with open(REPORT_FILE, encoding="utf-8") as f:
            r = json.load(f)
        return float(r.get("portfolio", {}).get("peak_equity_usd", TOTAL_BASELINE))
    except Exception:
        return TOTAL_BASELINE


def _load_history_tail(n: int = 3) -> list:
    """Load last n entries from history for Claude context."""
    lines = []
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, encoding="utf-8") as f:
            all_lines = f.readlines()
        for line in all_lines[-n:]:
            lines.append(json.loads(line.strip()))
    except Exception:
        pass
    return lines


def _run_cycle(cycle: int, peak_equity: float, anomaly_detector: AnomalyDetector) -> float:
    log.info("== CYCLE %d ==========================================", cycle)

    if os.path.exists(STOP_FILE):
        log.warning("EMERGENCY_STOP.txt detected")

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
    regime = classify_regime()
    log.info(
        "Regime: %s (conf=%.0f%%) BTC_7d=%.1f%% SPY_vol=%.2f%%",
        regime.regime, regime.confidence * 100,
        regime.btc_7d_pct, regime.spy_vol_10d,
    )

    # 3. Morning pre-market brief — once per weekday at 9 AM ET
    if should_fire():
        from supervisor_news import fetch_news
        from supervisor_social import fetch_social
        allocations     = compute_allocations()
        recent_outcomes = load_recent_outcomes(8)
        sentiment       = get_sentiment_signals()
        correlation     = check_correlation()
        news            = fetch_news()
        calendar        = get_calendar()
        social          = fetch_social()
        fire_morning_brief(portfolio, regime, allocations, recent_outcomes,
                           sentiment=sentiment, correlation=correlation,
                           news=news, calendar=calendar, social=social)

    # 4. Hermes context layer — runs every cycle, $0, replaces Brain
    _regime_label = regime.regime if regime else "NEUTRAL"
    _regime_conf = regime.confidence if regime else 0
    _dd = portfolio.total_dd_pct if hasattr(portfolio, 'total_dd_pct') else 0
    hermes_ctx = build_context(_regime_label, _regime_conf)
    advisory = compute_advisory(_regime_label, _dd)  # supervisor uses portfolio DD for log line
    log.info("[HERMES] %s | universe=$%.2f | %s",
             _regime_label, hermes_ctx.get("universe", {}).get("equity", 0),
             advisory.get("note", ""))

    # Brain replaced by Hermes context layer (cf062bc)

    # 5. Escalation bus — DISABLED (actions suppressed, wasting API credits)
    # Escalation responses are handled by the 12h Opus review cycle instead.

    # 6. Anomaly detection (detect + log only, no auto-remediation)
    anomaly_report = anomaly_detector.check(cycle)
    if anomaly_report.anomalies:
        portfolio_summary = (
            f"Total equity ${portfolio.total_equity:.2f} | PnL ${portfolio.total_pnl_usd:+.2f} "
            f"({portfolio.total_pnl_pct:+.2f}%) | DD {portfolio.total_dd_pct:.2f}%"
        )
        regime_summary = (
            f"{regime.regime} (conf {regime.confidence:.0%}) | BTC 7d {regime.btc_7d_pct:+.1f}% "
            f"| VIX {regime.vix:.1f} | {' | '.join(regime.notes)}"
        )
        healed = run_selfheal(anomaly_report, portfolio_summary, regime_summary, cycle)
        if healed:
            log.info("[SELFHEAL] %d action(s) executed this cycle", healed)

    # 5a. Kernel — invariant validation gate (runs BEFORE Governor)
    kernel_result = run_kernel(cycle)
    if kernel_result.status == "HALT":
        log.warning("[KERNEL] Governor SKIPPED this cycle — invariant violations")
    else:
        # 5b. Governor — local deterministic control
        try:
            gov_decisions = run_governor(cycle)
        except Exception as exc:
            log.error("[GOVERNOR] error: %s", exc)

    # 5c. Command snapshots — persist timestamped command state for reconciliation
    try:
        snapshot_commands(cycle)
    except Exception:
        pass

    # 6. Report
    report = build_report(portfolio, regime, cycle, new_peak)
    save_report(report)

    if report["alerts"]:
        for alert in report["alerts"]:
            log.warning("ALERT: %s", alert)

    if portfolio.kill_switch_active:
        log.warning("KILL SWITCH ACTIVE — all bots forced to DEFENSE via command files")

    log.info("Report saved → supervisor_report.json")

    # 7. Paperclip bridge — loop-closure tracking (read-only, no command writes)
    try:
        run_bridge(cycle)
    except Exception as exc:
        log.debug("[PAPERCLIP] bridge error: %s", exc)

    return new_peak


def main() -> None:
    log.info("=" * 65)
    log.info("MASTER SUPERVISOR v2 — Phase 2: UNIFIED CLAUDE BRAIN")
    log.info("Total baseline: $%.2f across 3 sleeves", TOTAL_BASELINE)
    log.info("Cycle: %ds | Brain: every %d cycles (~%dm)",
             CYCLE_SEC, BRAIN_INTERVAL_CYCLES,
             CYCLE_SEC * BRAIN_INTERVAL_CYCLES // 60)
    log.info("=" * 65)
    log.info("Sleeves:")
    log.info("  kraken_crypto  — core growth engine    (enzobot)")
    log.info("  sfm_tactical   — tactical booster      (sfmbot)")
    log.info("  alpaca_stocks  — stable compounder     (alpacabot)")
    log.info("=" * 65)

    peak_equity = _load_peak()
    cycle = 0
    anomaly_detector = AnomalyDetector()

    while True:
        cycle += 1
        try:
            peak_equity = _run_cycle(cycle, peak_equity, anomaly_detector)
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

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
from supervisor_brain import run_brain
from supervisor_allocation import compute_allocations
from supervisor_memory import load_recent_outcomes
from supervisor_morning_brief import should_fire, fire_morning_brief
from supervisor_signals import get_sentiment_signals
from supervisor_correlation import check_correlation
from supervisor_calendar import get_calendar
from supervisor_anomaly import AnomalyDetector
from supervisor_selfheal import run_selfheal
from supervisor_escalation import check_escalations
from supervisor_telegram import send_alert, start_telegram_bot
from supervisor_web import start_web_server


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


_prev_regime: str = ""
_prev_kill_switch: bool = False


def _run_cycle(cycle: int, peak_equity: float, anomaly_detector: AnomalyDetector) -> float:
    global _prev_regime, _prev_kill_switch
    log.info("── CYCLE %d ──────────────────────────────────────", cycle)

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

    # Alert: regime change
    if _prev_regime and regime.regime != _prev_regime:
        emoji = {"RISK_ON": "🟢", "NEUTRAL": "🟡", "RISK_OFF": "🔴"}.get(regime.regime, "⚪")
        send_alert(
            f"{emoji} <b>Regime changed: {_prev_regime} → {regime.regime}</b>\n"
            f"BTC 7d: {regime.btc_7d_pct:+.2f}%  |  VIX: {regime.vix:.1f}  |  Conf: {regime.confidence:.0%}"
        )
    _prev_regime = regime.regime

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
        send_alert(
            f"🌅 <b>Morning brief ready</b>\n"
            f"Regime: {regime.regime}  |  Equity: ${portfolio.total_equity:,.2f}  "
            f"|  PnL: {portfolio.total_pnl_pct:+.2f}%\n"
            f"Use /brief to read full report."
        )

    # 4. Claude unified brain — dynamic interval based on market conditions
    brain_interval = _dynamic_brain_interval(regime, portfolio)
    if brain_interval != BRAIN_INTERVAL_CYCLES:
        log.info("Dynamic brain interval: every %d cycles (~%dm) [stress mode]",
                 brain_interval, brain_interval * CYCLE_SEC // 60)

    if cycle % brain_interval == 1:
        history = _load_history_tail(3)
        decision = run_brain(portfolio, regime, history)
        log.info(
            "[BRAIN] Decision: kraken=%s %.1fx | sfm=%s %.1fx | alpaca=%s %.1fx",
            decision.kraken.get("mode"), decision.kraken.get("size_mult"),
            decision.sfm.get("mode"),    decision.sfm.get("size_mult"),
            decision.alpaca.get("mode"), decision.alpaca.get("size_mult"),
        )
        log.info("[BRAIN] %s", decision.portfolio_note)

        # Alert if any bot is put into DEFENSE
        defense_bots = [
            b for b, d in [("kraken", decision.kraken), ("sfm", decision.sfm), ("alpaca", decision.alpaca)]
            if d.get("mode") == "DEFENSE"
        ]
        if defense_bots:
            send_alert(
                f"🛡️ <b>Brain → DEFENSE</b>: {', '.join(defense_bots)}\n"
                f"{decision.portfolio_note}"
            )
    else:
        next_brain = brain_interval - (cycle % brain_interval)
        log.info("Brain update in %d cycles (~%dm) [interval=%d]",
                 next_brain, next_brain * CYCLE_SEC // 60, brain_interval)

    # 5. Escalation bus — bot Sonnet → Opus → bot (every cycle, immediate)
    escalated = check_escalations(portfolio, regime, cycle)
    if escalated:
        log.info("[ESCALATION] Handled %d bot escalation(s) this cycle", escalated)

    # 6. Self-healing — anomaly detection + Opus remediation (every cycle)
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

        # Alert on HIGH severity anomalies
        high = [a for a in anomaly_report.anomalies if getattr(a, "severity", "") == "HIGH"]
        if high:
            names = ", ".join(getattr(a, "type", str(a)) for a in high)
            send_alert(f"🔧 <b>Anomaly detected</b>: {names}\nSelf-heal running...")

        healed = run_selfheal(anomaly_report, portfolio_summary, regime_summary, cycle)
        if healed:
            log.info("[SELFHEAL] %d action(s) executed this cycle", healed)
            send_alert(f"✅ <b>Self-heal complete</b>: {healed} action(s) applied this cycle.")

    # 6. Report
    report = build_report(portfolio, regime, cycle, new_peak)
    save_report(report)

    if report["alerts"]:
        for alert in report["alerts"]:
            log.warning("ALERT: %s", alert)

    if portfolio.kill_switch_active:
        log.warning("KILL SWITCH ACTIVE — all bots forced to DEFENSE via command files")
        if not _prev_kill_switch:
            send_alert(
                f"🚨 <b>KILL SWITCH ACTIVATED</b>\n"
                f"Portfolio DD {portfolio.total_dd_pct:.2f}% exceeded threshold.\n"
                f"All bots forced to DEFENSE."
            )
    _prev_kill_switch = portfolio.kill_switch_active

    log.info("Report saved → supervisor_report.json")
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

    # Start remote access servers
    start_telegram_bot()
    start_web_server()

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

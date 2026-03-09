"""
status.py — Human-readable portfolio dashboard.
Usage: python status.py
"""
from __future__ import annotations
import json, os
from datetime import datetime, timezone

REPORT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "supervisor_report.json")

HEALTH_ICON = {"GOOD": "[OK]", "WARN": "[!!]", "CRITICAL": "[XX]"}
REGIME_BAR  = {"RISK_ON": "^ RISK_ON ", "NEUTRAL": "- NEUTRAL ", "RISK_OFF": "v RISK_OFF"}


def main():
    if not os.path.exists(REPORT):
        print("No report yet — run: python watchdog.py")
        return

    with open(REPORT, encoding="utf-8") as f:
        r = json.load(f)

    ts      = r.get("ts", "")[:19].replace("T", " ")
    cycle   = r.get("cycle", 0)
    phase   = r.get("phase", "?")
    pf      = r.get("portfolio", {})
    reg     = r.get("regime", {})
    sleeves = r.get("sleeves", {})
    recs    = r.get("recommendations", {})
    alerts  = r.get("alerts", [])

    print("=" * 62)
    print(f"  MASTER SUPERVISOR — {phase}")
    print(f"  {ts}  |  Cycle {cycle}")
    print("=" * 62)

    # Regime bar
    regime_str = REGIME_BAR.get(reg.get("classification", "?"), "? UNKNOWN")
    print(f"  REGIME:  {regime_str}  (conf={reg.get('confidence',0)*100:.0f}%)")
    print(f"  BTC 7d:  {reg.get('btc_7d_pct',0):+.1f}%  |  "
          f"SPY vol: {reg.get('spy_vol_10d_pct',0):.2f}%  |  "
          f"BTC: ${reg.get('btc_price_usd',0):,.0f}  SPY: ${reg.get('spy_price_usd',0):.2f}")
    print()

    # Portfolio totals
    eq    = pf.get("total_equity_usd", 0)
    pnl   = pf.get("total_pnl_usd", 0)
    pnlp  = pf.get("total_pnl_pct", 0)
    dd    = pf.get("total_dd_pct", 0)
    peak  = pf.get("peak_equity_usd", 0)
    print(f"  PORTFOLIO EQUITY:  ${eq:>10,.2f}")
    print(f"  Total PnL:         ${pnl:>+10,.2f}  ({pnlp:+.2f}%)")
    print(f"  Peak:              ${peak:>10,.2f}  |  DD: {dd:.2f}%")
    ks = pf.get("kill_switch_active", False)
    em = pf.get("emergency_stop", False)
    if ks:  print("  *** KILL SWITCH ACTIVE ***")
    if em:  print("  *** EMERGENCY STOP ACTIVE ***")
    print()

    # Sleeve breakdown
    print(f"  {'SLEEVE':<20} {'EQUITY':>10} {'PnL':>10} {'PnL%':>7} {'DD%':>7} {'POS':>4} {'MODE':<10} {'HEALTH'}")
    print("  " + "-" * 78)
    for name, s in sleeves.items():
        rec   = recs.get(name, {})
        amode = rec.get("advisory_mode", "?")
        curr  = s.get("mode", "?")
        icon  = HEALTH_ICON.get(s.get("health", "?"), "?")
        flag  = f" -> {amode}" if amode != curr else ""
        print(f"  {name:<20} ${s.get('equity_usd',0):>9,.2f} "
              f"${s.get('pnl_usd',0):>+9,.2f} "
              f"{s.get('pnl_pct',0):>+6.1f}% "
              f"{s.get('drawdown_pct',0):>+6.1f}% "
              f"{s.get('open_positions',0):>4} "
              f"{curr:<10} {icon}{flag}")

    # Alerts
    if alerts:
        print()
        print("  ALERTS:")
        for a in alerts:
            print(f"    !! {a}")

    # Regime notes
    print()
    print("  REGIME SIGNALS:")
    for note in reg.get("notes", []):
        print(f"    * {note}")

    print("=" * 62)


if __name__ == "__main__":
    main()

"""
supervisor_morning_brief.py — Daily pre-market intelligence brief.

Fires once per weekday at 9:00 AM ET (14:00 UTC, EDT).
Covers everything the human needs to know before the US market opens:
  - Overnight global markets (Asia closed, Europe live, US futures)
  - Portfolio status + drawdown
  - Each sleeve: equity, positions, mode, health
  - Allocation engine scores (who earned more size)
  - Outcome memory: recent accuracy
  - Brain's current stance (last command files)
  - Alerts and action items

Written to:  morning_brief.txt  (always overwritten — latest brief)
Appended to: morning_briefs.jsonl (permanent log)
Logged to:   supervisor.log
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

log = logging.getLogger("supervisor_morning_brief")

BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
BRIEF_FILE     = os.path.join(BASE_DIR, "morning_brief.txt")
BRIEF_LOG      = os.path.join(BASE_DIR, "morning_briefs.jsonl")
LAST_FIRED_FILE = os.path.join(BASE_DIR, "morning_brief_last.json")

COMMANDS_DIR = os.path.join(BASE_DIR, "commands")
CMD_FILES = {
    "kraken": os.path.join(COMMANDS_DIR, "kraken_cmd.json"),
    "sfm":    os.path.join(COMMANDS_DIR, "sfm_cmd.json"),
    "alpaca": os.path.join(COMMANDS_DIR, "alpaca_cmd.json"),
}

# Fire window: 9:00–9:14 AM ET (14:00–14:14 UTC during EDT)
# During EST (Nov–Mar) it's 14:00–14:14 → same UTC window works fine
# We use UTC offset -4 (EDT) for Mar–Nov, -5 (EST) for Nov–Mar
# Simple approach: check ET hour = 9 using UTC - 4 (EDT) for spring/summer
# For winter, brief will fire at 8:00 AM ET — acceptable early notice

FIRE_HOURS_ET = [8, 20]  # 8 AM + 8 PM ET
ET_OFFSET    = 4      # EDT (UTC-4); covers most of trading season


def _et_now() -> datetime:
    """Current time in approximate ET (EDT UTC-4)."""
    return datetime.now(timezone.utc) - timedelta(hours=ET_OFFSET)


def _load_last_fired() -> Optional[str]:
    """Return the date string (YYYY-MM-DD) of the last brief that fired."""
    try:
        if os.path.exists(LAST_FIRED_FILE):
            with open(LAST_FIRED_FILE, encoding="utf-8") as f:
                return json.load(f).get("date")
    except Exception:
        pass
    return None


def _save_last_fired(date_str: str) -> None:
    try:
        with open(LAST_FIRED_FILE, "w", encoding="utf-8") as f:
            json.dump({"date": date_str}, f)
    except Exception as exc:
        log.error("Failed to save last_fired: %s", exc)


def should_fire() -> bool:
    """
    Return True if the brief should fire right now.
    Fires at 8:02 AM and 8:02 PM ET, any day (crypto runs 24/7).
    Deduped by hour so it fires once per window.
    """
    now_et = _et_now()
    if now_et.hour not in FIRE_HOURS_ET:
        return False
    if now_et.minute < 2:
        return False
    fire_key = now_et.strftime("%Y-%m-%d") + f"_{now_et.hour}"
    if _load_last_fired() == fire_key:
        return False
    return True


def _read_cmd(sleeve: str) -> dict:
    path = CMD_FILES.get(sleeve, "")
    try:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"mode": "NORMAL", "size_mult": 0.8, "entry_allowed": True, "reasoning": "unknown"}


def _bar(label: str, width: int = 60) -> str:
    pad = width - len(label) - 4
    return f"== {label} {'=' * max(0, pad)}"


def generate_brief(portfolio, regime, allocations, recent_outcomes,
                   sentiment=None, correlation=None,
                   news=None, calendar=None, social=None) -> str:
    """
    Build the full morning brief as a plain-text string.
    """
    now_et  = _et_now()
    now_utc = datetime.now(timezone.utc)
    lines   = []

    # ── Header ──────────────────────────────────────────────────────────
    lines += [
        "=" * 64,
        f"  MORNING PRE-MARKET BRIEF",
        f"  {now_et.strftime('%A, %B %d, %Y')}  |  {now_et.strftime('%I:%M %p ET')}  ({now_utc.strftime('%H:%M UTC')})",
        "=" * 64,
        "",
    ]

    # ── Global Markets ───────────────────────────────────────────────────
    lines.append(_bar("OVERNIGHT GLOBAL MARKETS"))
    vix_label = "HIGH" if regime.vix > 25 else ("elevated" if regime.vix > 20 else "calm")
    lines += [
        f"  VIX:         {regime.vix:.1f}  ({vix_label})",
        f"  Asia avg:    {regime.asia_pct:+.2f}%",
        f"  Europe avg:  {regime.europe_pct:+.2f}%",
        f"  US futures:  {regime.us_futures_pct:+.2f}%",
        f"  US open bias: {regime.us_open_bias}",
        f"  Global:      {regime.global_sentiment}",
    ]
    for note in regime.global_notes:
        lines.append(f"    * {note}")
    lines.append("")

    # ── Macro Regime ─────────────────────────────────────────────────────
    lines.append(_bar("MACRO REGIME"))
    lines += [
        f"  Classification: {regime.regime}  (confidence {regime.confidence:.0%})",
        f"  BTC 7-day:      {regime.btc_7d_pct:+.1f}%  (${regime.btc_price:,.0f})",
        f"  SPY vol 10d:    {regime.spy_vol_10d:.2f}%  (${regime.spy_price:.2f})",
    ]
    for note in regime.notes:
        lines.append(f"    * {note}")
    lines.append("")

    # ── Portfolio Status ─────────────────────────────────────────────────
    lines.append(_bar("PORTFOLIO STATUS"))
    ks = "ACTIVE" if portfolio.kill_switch_active else "off"
    dd_flag = " <-- ALERT" if portfolio.total_dd_pct < -5 else ""
    lines += [
        f"  Total equity:  ${portfolio.total_equity:,.2f}  (baseline ${portfolio.total_baseline:,.2f})",
        f"  Total PnL:     ${portfolio.total_pnl_usd:+,.2f}  ({portfolio.total_pnl_pct:+.2f}%)",
        f"  Drawdown:      {portfolio.total_dd_pct:.2f}%{dd_flag}",
        f"  Kill switch:   {ks}",
        "",
    ]

    # ── Sleeve Status ────────────────────────────────────────────────────
    lines.append(_bar("SLEEVE STATUS"))
    sleeve_labels = {
        "kraken_crypto": "KRAKEN CRYPTO",
        "sfm_tactical":  "SFM TACTICAL ",
        "alpaca_stocks": "ALPACA STOCKS",
    }
    for key, label in sleeve_labels.items():
        s = portfolio.sleeves.get(key)
        if not s:
            continue
        cmd_key = key.split("_")[0]  # kraken / sfm / alpaca
        cmd = _read_cmd(cmd_key)
        health_flag = "  <-- WARN" if s.health == "WARN" else ("  <-- CRITICAL" if s.health == "CRITICAL" else "")
        _entry_str = "YES" if cmd.get("entry_allowed", True) else "NO"
        _flatten_str = " FORCE_FLATTEN" if cmd.get("force_flatten") else ""
        lines += [
            f"  [{label}]",
            f"    Equity:    ${s.equity_usd:,.2f}  (baseline ${s.baseline_usd:,.2f})",
            f"    PnL:       ${s.pnl_usd:+,.2f}  ({s.pnl_pct:+.1f}%)",
            f"    Drawdown:  {s.drawdown_pct:.2f}%{health_flag}",
            f"    Positions: {s.open_positions}  |  Health: {s.health}  |  Mode: {s.mode}",
            f"    Governor:  {cmd.get('mode','?')} {cmd.get('size_mult',0):.1f}x  entry={_entry_str}{_flatten_str}",
            f"    Reason:    {cmd.get('reasoning','--')[:80]}",
        ]
        if s.notes:
            for note in s.notes:
                lines.append(f"    Note: {note}")
        lines.append("")

    # ── USDG Yield (Kraken+ 4.25% APR) ──────────────────────────────────
    lines.append(_bar("USDG YIELD  (Kraken+ 4.25% APR)"))
    try:
        _enzo_state_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            r"..\enzobot\state.json",
        )
        with open(_enzo_state_path, encoding="utf-8") as _sf:
            _enzo_cash = float(json.load(_sf).get("cash", 0.0))
        _usdg_apr      = 0.0425
        _daily_yield   = _enzo_cash * _usdg_apr / 365
        _monthly_yield = _daily_yield * 30
        _annual_yield  = _enzo_cash * _usdg_apr
        lines += [
            f"  Cash earning yield: ${_enzo_cash:,.2f}",
            f"  Daily yield:        ${_daily_yield:,.2f}",
            f"  Monthly yield:      ${_monthly_yield:,.2f}",
            f"  Annual yield:       ${_annual_yield:,.2f}",
            f"  Note: Allocate idle Kraken cash to USDG to activate yield",
        ]
    except Exception as _yield_exc:
        lines.append(f"  [Yield data unavailable: {_yield_exc}]")
    lines.append("")

    # ── Kraken+ Free Tier ────────────────────────────────────────────────
    lines.append(_bar("KRAKEN+ FREE TIER  (fee-free allowance)"))
    try:
        import sys
        sys.path.insert(0, r"C:\Projects\enzobot")
        from kraken_free_tier import format_for_brief
        lines.append(format_for_brief())
    except Exception as _free_tier_exc:
        lines.append(f"  [Free tier data unavailable: {_free_tier_exc}]")
    lines.append("")

    # ── Economic Calendar ────────────────────────────────────────────────
    if calendar:
        from supervisor_calendar import format_calendar_for_prompt
        lines.append(_bar("ECONOMIC CALENDAR"))
        lines.append(format_calendar_for_prompt(calendar))
        lines.append("")

    # ── News Headlines ───────────────────────────────────────────────────
    if news:
        from supervisor_news import format_news_for_prompt
        lines.append(_bar("BREAKING NEWS"))
        lines.append(format_news_for_prompt(news, max_headlines=8))
        lines.append("")

    # ── Social Sentiment ─────────────────────────────────────────────────
    if social:
        from supervisor_social import format_social_for_prompt
        lines.append(_bar("SOCIAL SENTIMENT  (Stocktwits)"))
        lines.append(format_social_for_prompt(social))
        lines.append("")

    # ── Sentiment & On-Chain ────────────────────────────────────────────
    if sentiment:
        lines.append(_bar("SENTIMENT & ON-CHAIN SIGNALS"))
        for note in sentiment.notes:
            lines.append(f"  {note}")
        lines.append("")

    # ── Correlation ─────────────────────────────────────────────────────
    if correlation:
        lines.append(_bar("BTC/SPY CORRELATION"))
        for note in correlation.notes:
            lines.append(f"  {note}")
        if correlation.warning:
            lines.append(f"  !! COLLAPSE: size_mult capped at {correlation.size_mult_cap}x")
        lines.append("")

    # ── Allocation Engine ────────────────────────────────────────────────
    lines.append(_bar("ALLOCATION ENGINE  (performance scores)"))
    if allocations:
        for a in allocations:
            arrow = "^" if a.direction == "UP" else ("v" if a.direction == "DOWN" else "=")
            lines.append(
                f"  {a.sleeve:<8}  score={a.score:.2f}  win={a.win_rate:.0%}  "
                f"sharpe={a.sharpe:+.2f}  avg={a.avg_return:+.2f}%  "
                f"{a.current_mult:.1f}x -> {a.recommended_mult:.1f}x [{arrow}]  "
                f"(n={a.sample_size})"
            )
    else:
        lines.append("  No allocation data yet.")
    lines.append("")

    # ── Outcome Memory ───────────────────────────────────────────────────
    lines.append(_bar("OUTCOME MEMORY  (last decisions scored)"))
    if recent_outcomes:
        for o in recent_outcomes[-5:]:
            ts      = o.get("decision_ts", "")[:16]
            overall = o.get("overall_verdict", "?")
            chg     = o.get("total_chg_pct", 0)
            sleeves = o.get("sleeves", [])
            parts   = [f"{s['sleeve']}:{s['mode'][0]}({s['chg_pct']:+.2f}%={s['verdict'][0]})"
                       for s in sleeves]
            lines.append(f"  {ts}  {overall:<8}  {chg:+.2f}%  |  {' | '.join(parts)}")

        verdicts     = [o.get("overall_verdict") for o in recent_outcomes]
        correct_rate = verdicts.count("CORRECT") / len(verdicts) * 100
        lines.append(f"  Accuracy: {correct_rate:.0f}% correct over last {len(verdicts)} decisions")
    else:
        lines.append("  No scored decisions yet — system is learning.")
    lines.append("")

    # ── Alerts ───────────────────────────────────────────────────────────
    alerts = []
    if portfolio.kill_switch_active:
        alerts.append("KILL SWITCH ACTIVE — all bots in DEFENSE")
    if portfolio.emergency_stop:
        alerts.append("EMERGENCY STOP FILE detected")
    if portfolio.total_dd_pct < -8:
        alerts.append(f"Portfolio drawdown {portfolio.total_dd_pct:.1f}% — approaching kill switch")
    if regime.vix > 30:
        alerts.append(f"VIX {regime.vix:.1f} — panic level, expect volatility")
    if regime.us_futures_pct < -1.0:
        alerts.append(f"US futures down {regime.us_futures_pct:.2f}% — expect weak open")
    for key, s in portfolio.sleeves.items():
        if s.health == "CRITICAL":
            alerts.append(f"{key} sleeve CRITICAL — drawdown {s.drawdown_pct:.1f}%")

    lines.append(_bar("ALERTS"))
    if alerts:
        for a in alerts:
            lines.append(f"  !! {a}")
    else:
        lines.append("  No alerts — all systems nominal.")
    lines.append("")

    # ── Today's Plan ─────────────────────────────────────────────────────
    lines.append(_bar("TODAY'S PLAN  (current brain stance)"))
    k_cmd = _read_cmd("kraken")
    s_cmd = _read_cmd("sfm")
    a_cmd = _read_cmd("alpaca")
    lines += [
        f"  Kraken crypto:  {k_cmd.get('mode','?')} {k_cmd.get('size_mult',0):.1f}x",
        f"  SFM tactical:   {s_cmd.get('mode','?')} {s_cmd.get('size_mult',0):.1f}x",
        f"  Alpaca stocks:  {a_cmd.get('mode','?')} {a_cmd.get('size_mult',0):.1f}x",
        "",
        "  Brain fires every 30 min — stance will update as markets evolve.",
        "  Monitor supervisor.log for intraday decisions.",
    ]
    lines.append("")
    lines.append("=" * 64)
    lines.append(f"  End of brief  |  Generated {now_utc.strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("=" * 64)

    # ── Go-Live Readiness Scorecard ──────────────────────────────────────────
    try:
        from golive_tracker import generate_golive_scorecard
        lines.append("")
        lines.append("")
        scorecard = generate_golive_scorecard()
        lines.append(scorecard)
    except Exception as _golive_exc:
        lines.append("")
        lines.append(f"[GO-LIVE SCORECARD] Failed to generate: {_golive_exc}")

    return "\n".join(lines)


def save_brief(text: str) -> None:
    """Write brief to morning_brief.txt and append a record to morning_briefs.jsonl."""
    try:
        with open(BRIEF_FILE, "w", encoding="utf-8") as f:
            f.write(text)
        log.info("[BRIEF] Saved to %s", BRIEF_FILE)
    except Exception as exc:
        log.error("[BRIEF] Failed to save brief: %s", exc)

    try:
        record = {
            "ts":    datetime.now(timezone.utc).isoformat(),
            "brief": text,
        }
        with open(BRIEF_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, separators=(",", ":")) + "\n")
    except Exception as exc:
        log.error("[BRIEF] Failed to append brief log: %s", exc)


def fire_morning_brief(portfolio, regime, allocations, recent_outcomes,
                       sentiment=None, correlation=None,
                       news=None, calendar=None, social=None) -> None:
    """
    Generate and save the morning brief. Mark today as fired.
    Called by supervisor main loop when should_fire() returns True.
    """
    log.info("[BRIEF] Generating morning pre-market brief...")
    text = generate_brief(portfolio, regime, allocations, recent_outcomes,
                          sentiment=sentiment, correlation=correlation,
                          news=news, calendar=calendar, social=social)
    save_brief(text)

    # Print brief to supervisor log (truncated to first 40 lines)
    for line in text.split("\n")[:40]:
        log.info("[BRIEF] %s", line)

    now_et  = _et_now()
    _save_last_fired(now_et.strftime("%Y-%m-%d") + f"_{now_et.hour}")
    log.info("[BRIEF] Brief complete (%d:02 ET).", now_et.hour)

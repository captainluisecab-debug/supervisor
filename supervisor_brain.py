"""
supervisor_brain.py — Unified Claude brain for all three bots.

Called every BRAIN_INTERVAL_CYCLES by the supervisor main loop.
Receives full portfolio context + regime + recent history.
Returns unified commands for all three bots.
Writes command files that each bot reads every cycle.

This is Phase 2 of the supervisor — Claude now sees everything.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

try:
    import anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    anthropic = None  # type: ignore[assignment]
    _ANTHROPIC_AVAILABLE = False
    import logging as _logging
    _logging.getLogger("supervisor_brain").warning(
        "anthropic package not installed — Claude brain disabled. "
        "Install with: pip install anthropic"
    )

from supervisor_settings import (
    ANTHROPIC_API_KEY, CLAUDE_MODEL,
    CMD_ALPACA, CMD_KRAKEN, CMD_SFM, COMMANDS_DIR,
)
from supervisor_memory import (
    evaluate_and_log, save_pending,
    load_recent_outcomes, format_outcomes_for_prompt,
)
from supervisor_allocation import compute_allocations, format_allocations_for_prompt
from supervisor_signals import get_sentiment_signals, format_signals_for_prompt
from supervisor_correlation import (
    check_correlation, format_correlation_for_prompt, apply_correlation_cap,
)
from supervisor_news import fetch_news, format_news_for_prompt
from supervisor_calendar import get_calendar, format_calendar_for_prompt
from supervisor_social import fetch_social, format_social_for_prompt
from supervisor_execution import read_recent_executions, format_executions_for_prompt
from supervisor_unified import read_unified_portfolio, format_unified_for_prompt

log = logging.getLogger("supervisor_brain")

# ── Defaults written if Claude call fails ────────────────────────────
SAFE_DEFAULT = {
    "mode": "NORMAL",
    "size_mult": 0.8,
    "entry_allowed": True,
    "max_positions_override": None,
    "reasoning": "default — Claude unavailable",
}

_VALID_MODES = {"NORMAL", "SCOUT", "DEFENSE"}


def _validate_cmd(cmd: dict, bot: str) -> dict:
    """
    Return a new normalized command dict with mode/size_mult/entry_allowed validated.
    Never mutates the incoming dict (which may be the shared SAFE_DEFAULT object).
    Logs every correction at WARNING level before any file write occurs.
    """
    if not isinstance(cmd, dict):
        log.warning(
            "[BRAIN][VALIDATE] %s: command is not a dict (got %s) -> DEFENSE fallback",
            bot, type(cmd).__name__,
        )
        out = {"mode": "DEFENSE", "size_mult": 0.3, "entry_allowed": False,
               "reasoning": "non-dict Claude output — conservative fallback"}
    else:
        out = dict(cmd)  # shallow copy — never mutate incoming

    # ── mode ──────────────────────────────────────────────────────────
    raw_mode = out.get("mode")
    if raw_mode not in _VALID_MODES:
        log.warning(
            "[BRAIN][VALIDATE] %s: invalid mode %r -> DEFENSE (conservative fallback)",
            bot, raw_mode,
        )
        out["mode"] = "DEFENSE"

    # ── size_mult ──────────────────────────────────────────────────────
    raw_mult = out.get("size_mult")
    try:
        clamped = max(0.3, min(1.3, float(raw_mult)))
        if clamped != float(raw_mult):
            log.warning(
                "[BRAIN][VALIDATE] %s: size_mult %r outside [0.3, 1.3] -> clamped to %.2f",
                bot, raw_mult, clamped,
            )
        out["size_mult"] = clamped
    except (TypeError, ValueError):
        log.warning(
            "[BRAIN][VALIDATE] %s: size_mult %r not numeric -> 0.8 (safe default)",
            bot, raw_mult,
        )
        out["size_mult"] = 0.8

    # ── entry_allowed ──────────────────────────────────────────────────
    raw_entry = out.get("entry_allowed")
    if not isinstance(raw_entry, bool):
        derived = (out["mode"] != "DEFENSE")
        log.warning(
            "[BRAIN][VALIDATE] %s: entry_allowed %r not bool -> derived %s from mode %s",
            bot, raw_entry, derived, out["mode"],
        )
        out["entry_allowed"] = derived

    return out


@dataclass
class BrainDecision:
    kraken: dict
    sfm: dict
    alpaca: dict
    portfolio_note: str
    ts: str


# ── Prompt builder ───────────────────────────────────────────────────

def _build_prompt(portfolio, regime, history_tail: list,
                  corr_snap=None, sentiment_snap=None,
                  news_snap=None, calendar_snap=None, social_snap=None) -> str:
    sleeves = portfolio.sleeves
    k = sleeves.get("kraken_crypto")
    s = sleeves.get("sfm_tactical")
    a = sleeves.get("alpaca_stocks")

    # Outcome memory — scored decisions from past brain calls
    recent_outcomes = load_recent_outcomes(8)
    outcome_text = format_outcomes_for_prompt(recent_outcomes)

    # Performance-based allocation recommendations
    allocations  = compute_allocations()
    alloc_text   = format_allocations_for_prompt(allocations)

    # Sentiment + on-chain signals (passed in from run_brain to avoid double fetch)
    signal_text   = format_signals_for_prompt(sentiment_snap) if sentiment_snap else "  unavailable"

    # Correlation collapse detection (passed in from run_brain)
    corr_text     = format_correlation_for_prompt(corr_snap) if corr_snap else "  unavailable"

    # News headlines
    news_text     = format_news_for_prompt(news_snap) if news_snap else "  unavailable"

    # Economic calendar
    calendar_text = format_calendar_for_prompt(calendar_snap) if calendar_snap else "  unavailable"

    # Social sentiment
    social_text   = format_social_for_prompt(social_snap) if social_snap else "  unavailable"

    # Recent executions across all bots
    recent_execs  = read_recent_executions(20)
    exec_text     = format_executions_for_prompt(recent_execs)

    # Unified portfolio — direct read of all 3 bot state files
    unified       = read_unified_portfolio()
    unified_text  = format_unified_for_prompt(unified)

    prompt = f"""You are the unified trading brain for a 3-sleeve autonomous trading ecosystem.
Your job: analyze all three bots together and assign each one an operating mode and size multiplier.
Be disciplined. Capital preservation comes before growth.

═══════════════════════════════════════════════════
PORTFOLIO SNAPSHOT  [{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}]
═══════════════════════════════════════════════════
Total Equity:   ${portfolio.total_equity:,.2f}
Total PnL:      ${portfolio.total_pnl_usd:+,.2f} ({portfolio.total_pnl_pct:+.2f}%)
Drawdown:       {portfolio.total_dd_pct:.2f}% from peak
Kill Switch:    {"ACTIVE" if portfolio.kill_switch_active else "off"}

MACRO REGIME: {regime.regime} (confidence {regime.confidence:.0%})
  BTC 7-day:  {regime.btc_7d_pct:+.1f}%  (price ${regime.btc_price:,.0f})
  SPY vol:    {regime.spy_vol_10d:.2f}%   (price ${regime.spy_price:.2f})
  Signals:    {" | ".join(regime.notes)}

GLOBAL MARKETS: {regime.global_sentiment} | US open bias: {regime.us_open_bias} | VIX: {regime.vix:.1f}
  Asia avg:      {regime.asia_pct:+.2f}%
  Europe avg:    {regime.europe_pct:+.2f}%
  US futures:    {regime.us_futures_pct:+.2f}%
  {chr(10).join(f"  {n}" for n in regime.global_notes)}

{unified_text}

═══════════════════════════════════════════════════
SLEEVE STATUS
═══════════════════════════════════════════════════
[KRAKEN CRYPTO — core growth engine]
  Equity:     ${k.equity_usd:,.2f} (baseline $4,000)
  PnL:        ${k.pnl_usd:+,.2f} ({k.pnl_pct:+.1f}%)
  Drawdown:   {k.drawdown_pct:.2f}%
  Open pos:   {k.open_positions}
  Bot mode:   {k.mode}
  Health:     {k.health}
  Notes:      {" | ".join(k.notes) if k.notes else "none"}

[SFM TACTICAL — Solana meme token booster]
  Equity:     ${s.equity_usd:,.2f} (baseline ${s.baseline_usd:,.0f} paper USDC)
  PnL:        ${s.pnl_usd:+,.2f} ({s.pnl_pct:+.1f}%)
  Open pos:   {s.open_positions}
  Bot mode:   {s.mode}
  Health:     {s.health}
  Notes:      {" | ".join(s.notes) if s.notes else "none"}
  WARNING:    SFM pool liquidity only $40k — max $100 per trade

[ALPACA STOCKS — stable compounder]
  Equity:     ${a.equity_usd:,.2f} (baseline $500)
  PnL:        ${a.pnl_usd:+,.2f} ({a.pnl_pct:+.1f}%)
  Open pos:   {a.open_positions}
  Bot mode:   {a.mode}
  Health:     {a.health}
  Notes:      {" | ".join(a.notes) if a.notes else "none"}

═══════════════════════════════════════════════════
OUTCOME MEMORY (scored decisions — learn from these)
═══════════════════════════════════════════════════
{outcome_text}

═══════════════════════════════════════════════════
BREAKING NEWS & MARKET HEADLINES
═══════════════════════════════════════════════════
{news_text}

═══════════════════════════════════════════════════
ECONOMIC CALENDAR (high-impact events)
═══════════════════════════════════════════════════
{calendar_text}

═══════════════════════════════════════════════════
SOCIAL SENTIMENT (Stocktwits crowd)
═══════════════════════════════════════════════════
{social_text}

═══════════════════════════════════════════════════
SENTIMENT & ON-CHAIN SIGNALS
═══════════════════════════════════════════════════
{signal_text}

═══════════════════════════════════════════════════
CROSS-ASSET CORRELATION (BTC vs SPY)
═══════════════════════════════════════════════════
{corr_text}

═══════════════════════════════════════════════════
ALLOCATION ENGINE (Sharpe + Kelly Criterion)
═══════════════════════════════════════════════════
{alloc_text}

═══════════════════════════════════════════════════
RECENT EXECUTIONS (last 10 across all bots)
═══════════════════════════════════════════════════
{exec_text}

═══════════════════════════════════════════════════
YOUR TASK
═══════════════════════════════════════════════════
Assign each bot one of these modes:
  NORMAL  — full operation, entries allowed
  SCOUT   — monitor only, reduced size, cautious entries
  DEFENSE — no new entries, protect capital, trail stops tight

And a size_mult between 0.3 and 1.3 (multiplier on base trade size).

Rules:
- If portfolio DD > 8%: all bots DEFENSE
- If portfolio DD > 5%: no NORMAL allowed, max SCOUT
- If regime RISK_OFF: max SCOUT for crypto, NORMAL allowed for stocks
- If regime RISK_ON: NORMAL allowed for all if health is GOOD
- SFM is tactical only — never push it above SCOUT unless regime strongly RISK_ON AND sfm health GOOD
- Alpaca stocks are the stability sleeve — default NORMAL unless portfolio is in crisis
- Use the ALLOCATION ENGINE suggestions as starting points for size_mult
- You may override allocation suggestions when regime or health contradicts them
- Never assign size_mult outside 0.3–1.3 range
- Never change size_mult by more than 0.2 from the suggested value in a single call

Respond with ONLY valid JSON, no markdown, no explanation outside JSON:
{{
  "kraken": {{
    "mode": "NORMAL|SCOUT|DEFENSE",
    "size_mult": 0.3-1.3,
    "entry_allowed": true|false,
    "reasoning": "one sentence"
  }},
  "sfm": {{
    "mode": "NORMAL|SCOUT|DEFENSE",
    "size_mult": 0.3-1.3,
    "entry_allowed": true|false,
    "reasoning": "one sentence"
  }},
  "alpaca": {{
    "mode": "NORMAL|SCOUT|DEFENSE",
    "size_mult": 0.3-1.3,
    "entry_allowed": true|false,
    "reasoning": "one sentence"
  }},
  "portfolio_note": "one sentence summary of overall portfolio stance"
}}"""
    return prompt


# ── Claude call ──────────────────────────────────────────────────────

def _call_claude(prompt: str) -> Optional[dict]:
    if not _ANTHROPIC_AVAILABLE or anthropic is None:
        log.warning("anthropic package not available — cannot call Claude")
        return None
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    try:
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
    except json.JSONDecodeError as exc:
        log.error("Claude returned invalid JSON: %s", exc)
        return None
    except Exception as exc:
        log.error("Claude call failed: %s", exc)
        return None


# ── Command writer ───────────────────────────────────────────────────

def _write_command(path: str, cmd: dict, bot: str) -> None:
    cmd["bot"]  = bot
    cmd["ts"]   = datetime.now(timezone.utc).isoformat()
    cmd["source"] = "supervisor_brain_v2"
    os.makedirs(COMMANDS_DIR, exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cmd, f, indent=2)
    except Exception as exc:
        log.error("Failed to write command %s: %s", path, exc)


def _write_defaults(reason: str = "fallback") -> None:
    # DISABLED — governor owns command files. Brain fallback no longer writes.
    log.info("[BRAIN] fallback triggered (%s) — logged only, governor owns commands", reason)


# ── Enzobot command bridge ───────────────────────────────────────────

_last_enzobot_command: str | None = None  # tracks last written command; avoids repeated injection


def _write_enzobot_command(kraken_cmd: dict) -> None:
    """
    Translate supervisor mode into enzobot's supervisor_command.json format.
    Enzobot's brain reads this file and applies the command on next cycle.
    Only writes when the command changes — prevents repeated injection that bypasses
    enzobot's can_change_mode() gate and inflates changes_today (ISSUE-002).
    """
    global _last_enzobot_command
    mode = kraken_cmd.get("mode", "NORMAL")
    # Map supervisor modes to enzobot brain commands
    mode_map = {
        "NORMAL":  "resume_auto",   # let the brain decide freely
        "SCOUT":   "hold",          # hold — cautious, no new entries
        "DEFENSE": "defend",        # force DEFEND mode
    }
    command = mode_map.get(mode, "resume_auto")
    if command == _last_enzobot_command:
        return
    _last_enzobot_command = command
    reason  = kraken_cmd.get("reasoning", "supervisor directive")

    _enzobot_base = os.path.dirname(
        os.environ.get("ENZOBOT_STATE", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                      "..", "enzobot", "state.json"))
    )
    enzobot_cmd_path = os.path.join(_enzobot_base, "supervisor_command.json")
    payload = {
        "enabled": True,
        "command": command,
        "reason":  f"[MASTER SUPERVISOR] {reason}",
    }
    try:
        with open(enzobot_cmd_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        log.info("[BRAIN] Enzobot command: %s (%s)", command, reason[:60])
    except Exception as exc:
        log.error("Failed to write enzobot command: %s", exc)


# ── Main entry point ─────────────────────────────────────────────────

_last_brain_decision: Optional[BrainDecision] = None
_last_regime_label: Optional[str] = None
_last_dd_bucket: Optional[int] = None   # DD rounded to nearest 1%
_last_call_ts: float = 0.0
_BRAIN_BACKSTOP_SEC = 21600  # force a call every 6 hours regardless


def run_brain(portfolio, regime, history_tail: list) -> BrainDecision:
    """
    Call Claude with full portfolio context. Write command files.
    Returns BrainDecision. On failure, writes safe defaults.

    PHASE 1: Claude call is gated — only fires when regime changes, DD crosses
    a 1% boundary, an anomaly is active, or 6 hours have passed. Otherwise reuses
    the cached decision. Reduces calls from 96-288/day to ~4-8/day.
    """
    global _last_brain_decision, _last_regime_label, _last_dd_bucket, _last_call_ts

    if not ANTHROPIC_API_KEY:
        log.warning("ANTHROPIC_API_KEY not set — writing safe defaults")
        _write_defaults("no api key")
        return BrainDecision(SAFE_DEFAULT, SAFE_DEFAULT, SAFE_DEFAULT,
                             "Claude unavailable", datetime.now(timezone.utc).isoformat())

    # Emergency stop or kill switch — skip Claude, force DEFENSE
    if portfolio.emergency_stop or portfolio.kill_switch_active:
        defense = {"mode": "DEFENSE", "size_mult": 0.0, "entry_allowed": False,
                   "reasoning": "emergency stop or kill switch active"}
        for path, bot in [(CMD_KRAKEN, "kraken"), (CMD_SFM, "sfm"), (CMD_ALPACA, "alpaca")]:
            _write_command(path, dict(defense), bot)
        log.warning("[BRAIN] EMERGENCY — all bots forced to DEFENSE")
        return BrainDecision(defense, defense, defense,
                             "EMERGENCY DEFENSE", datetime.now(timezone.utc).isoformat())

    # Score previous decision before making a new one
    outcome = evaluate_and_log(portfolio)
    if outcome:
        log.info(
            "[MEMORY] Previous decision scored: %s | portfolio %+.2f%%",
            outcome.overall_verdict, outcome.total_chg_pct,
        )

    # Brain runs every cycle at $0 — no gating needed (Claude call disabled)

    # Fetch all intelligence signals once — passed to prompt builder
    corr_snap      = check_correlation()
    sentiment_snap = get_sentiment_signals()
    news_snap      = fetch_news()
    calendar_snap  = get_calendar()
    social_snap    = fetch_social()

    prompt = _build_prompt(portfolio, regime, history_tail,
                           corr_snap=corr_snap, sentiment_snap=sentiment_snap,
                           news_snap=news_snap, calendar_snap=calendar_snap,
                           social_snap=social_snap)
    # BRAIN CLAUDE CALL DISABLED — governor owns all live decisions.
    # Brain produces deterministic advisory from regime data at $0 cost.
    # Claude was costing $2-8/day and producing 94.5% NEUTRAL outcomes.
    _regime_label = regime.regime if regime else "NEUTRAL"
    _dd = portfolio.total_dd_pct if hasattr(portfolio, 'total_dd_pct') else 0
    if _regime_label == "RISK_OFF" or _dd < -5:
        _default_mode = {"mode": "DEFENSE", "size_mult": 0.3, "entry_allowed": False,
                         "reasoning": f"Brain advisory: {_regime_label}, DD {_dd:.1f}%"}
    elif _regime_label == "RISK_ON" and _dd > -3:
        _default_mode = {"mode": "NORMAL", "size_mult": 0.8, "entry_allowed": True,
                         "reasoning": f"Brain advisory: {_regime_label}, DD {_dd:.1f}%"}
    else:
        _default_mode = {"mode": "SCOUT", "size_mult": 0.5, "entry_allowed": False,
                         "reasoning": f"Brain advisory: {_regime_label}, DD {_dd:.1f}%"}
    raw = {"kraken": _default_mode, "sfm": dict(_default_mode), "alpaca": dict(_default_mode),
           "portfolio_note": f"Deterministic advisory: {_regime_label} DD={_dd:.1f}%"}
    log.info("[BRAIN] Advisory (no Claude call): %s DD=%.1f%%", _regime_label, _dd)

    k_cmd = _validate_cmd(raw.get("kraken", SAFE_DEFAULT), "kraken")
    s_cmd = _validate_cmd(raw.get("sfm",    SAFE_DEFAULT), "sfm")
    a_cmd = _validate_cmd(raw.get("alpaca", SAFE_DEFAULT), "alpaca")
    note  = raw.get("portfolio_note", "")

    # Enforce correlation collapse size cap (hard override — not advisory)
    if corr_snap.warning:
        for cmd, name in [(k_cmd, "kraken"), (s_cmd, "sfm"), (a_cmd, "alpaca")]:
            original = cmd.get("size_mult", 1.0)
            capped   = apply_correlation_cap(float(original), corr_snap)
            if capped < original:
                log.warning(
                    "[CORR] %s size_mult capped: %.1fx -> %.1fx (correlation collapse)",
                    name, original, capped,
                )
                cmd["size_mult"] = capped

    # COMMAND WRITES DISABLED — governor is the single source of truth for command files.
    # Brain still runs for advisory, logging, and outcome scoring. It does not write commands.
    # Emergency stop (kill switch) still writes directly — defense-in-depth.
    # _write_command(CMD_KRAKEN, dict(k_cmd), "kraken")
    # _write_command(CMD_SFM,    dict(s_cmd), "sfm")
    # _write_command(CMD_ALPACA, dict(a_cmd), "alpaca")
    # _write_enzobot_command(k_cmd)

    # Save equity snapshot + decision — scored on next brain call
    save_pending(raw, portfolio, regime=regime)

    log.info("[BRAIN] kraken=%s %.1fx | sfm=%s %.1fx | alpaca=%s %.1fx",
             k_cmd.get("mode"), k_cmd.get("size_mult"),
             s_cmd.get("mode"), s_cmd.get("size_mult"),
             a_cmd.get("mode"), a_cmd.get("size_mult"))
    log.info("[BRAIN] %s", note)

    _result = BrainDecision(
        kraken=k_cmd, sfm=s_cmd, alpaca=a_cmd,
        portfolio_note=note,
        ts=datetime.now(timezone.utc).isoformat(),
    )
    _last_brain_decision = _result
    _last_regime_label = _current_regime
    _last_dd_bucket = _current_dd_bucket
    _last_call_ts = _now
    return _result

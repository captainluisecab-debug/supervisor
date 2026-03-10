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

import anthropic

from supervisor_settings import (
    ANTHROPIC_API_KEY, CLAUDE_MODEL,
    CMD_ALPACA, CMD_KRAKEN, CMD_SFM, COMMANDS_DIR,
)
from supervisor_memory import (
    evaluate_and_log, save_pending,
    load_recent_outcomes, format_outcomes_for_prompt,
)
from supervisor_allocation import compute_allocations, format_allocations_for_prompt

log = logging.getLogger("supervisor_brain")

# ── Defaults written if Claude call fails ────────────────────────────
SAFE_DEFAULT = {
    "mode": "NORMAL",
    "size_mult": 0.8,
    "entry_allowed": True,
    "max_positions_override": None,
    "reasoning": "default — Claude unavailable",
}


@dataclass
class BrainDecision:
    kraken: dict
    sfm: dict
    alpaca: dict
    portfolio_note: str
    ts: str


# ── Prompt builder ───────────────────────────────────────────────────

def _build_prompt(portfolio, regime, history_tail: list) -> str:
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
  Equity:     ${s.equity_usd:,.2f} (baseline $1,000 paper USDC)
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
ALLOCATION ENGINE (data-driven size_mult guidance)
═══════════════════════════════════════════════════
{alloc_text}

═══════════════════════════════════════════════════
YOUR TASK
═══════════════════════════════════════════════════
Assign each bot one of these modes:
  NORMAL  — full operation, entries allowed
  SCOUT   — monitor only, reduced size, cautious entries
  DEFENSE — no new entries, protect capital, trail stops tight

And a size_mult between 0.3 and 1.0 (multiplier on base trade size).

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
    "size_mult": 0.0-1.0,
    "entry_allowed": true|false,
    "reasoning": "one sentence"
  }},
  "sfm": {{
    "mode": "NORMAL|SCOUT|DEFENSE",
    "size_mult": 0.0-1.0,
    "entry_allowed": true|false,
    "reasoning": "one sentence"
  }},
  "alpaca": {{
    "mode": "NORMAL|SCOUT|DEFENSE",
    "size_mult": 0.0-1.0,
    "entry_allowed": true|false,
    "reasoning": "one sentence"
  }},
  "portfolio_note": "one sentence summary of overall portfolio stance"
}}"""
    return prompt


# ── Claude call ──────────────────────────────────────────────────────

def _call_claude(prompt: str) -> Optional[dict]:
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
    for path, bot in [(CMD_KRAKEN, "kraken"), (CMD_SFM, "sfm"), (CMD_ALPACA, "alpaca")]:
        _write_command(path, {**SAFE_DEFAULT, "reasoning": reason}, bot)


# ── Enzobot command bridge ───────────────────────────────────────────

def _write_enzobot_command(kraken_cmd: dict) -> None:
    """
    Translate supervisor mode into enzobot's supervisor_command.json format.
    Enzobot's brain reads this file and applies the command on next cycle.
    """
    mode = kraken_cmd.get("mode", "NORMAL")
    # Map supervisor modes to enzobot brain commands
    mode_map = {
        "NORMAL":  "resume_auto",   # let the brain decide freely
        "SCOUT":   "hold",          # hold — cautious, no new entries
        "DEFENSE": "defend",        # force DEFEND mode
    }
    command = mode_map.get(mode, "resume_auto")
    reason  = kraken_cmd.get("reasoning", "supervisor directive")

    enzobot_cmd_path = r"C:\Projects\enzobot\supervisor_command.json"
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

def run_brain(portfolio, regime, history_tail: list) -> BrainDecision:
    """
    Call Claude with full portfolio context. Write command files.
    Returns BrainDecision. On failure, writes safe defaults.
    """
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

    prompt = _build_prompt(portfolio, regime, history_tail)
    log.info("[BRAIN] Calling Claude for unified portfolio decision...")

    raw = _call_claude(prompt)
    if raw is None:
        log.warning("[BRAIN] Claude failed — writing safe defaults")
        _write_defaults("claude call failed")
        return BrainDecision(SAFE_DEFAULT, SAFE_DEFAULT, SAFE_DEFAULT,
                             "Claude failed", datetime.now(timezone.utc).isoformat())

    k_cmd = raw.get("kraken", SAFE_DEFAULT)
    s_cmd = raw.get("sfm",    SAFE_DEFAULT)
    a_cmd = raw.get("alpaca", SAFE_DEFAULT)
    note  = raw.get("portfolio_note", "")

    _write_command(CMD_KRAKEN, dict(k_cmd), "kraken")
    _write_command(CMD_SFM,    dict(s_cmd), "sfm")
    _write_command(CMD_ALPACA, dict(a_cmd), "alpaca")

    # Wire Enzobot: translate mode to supervisor_command.json format
    _write_enzobot_command(k_cmd)

    # Save equity snapshot + decision — scored on next brain call
    save_pending(raw, portfolio)

    log.info("[BRAIN] kraken=%s %.1fx | sfm=%s %.1fx | alpaca=%s %.1fx",
             k_cmd.get("mode"), k_cmd.get("size_mult"),
             s_cmd.get("mode"), s_cmd.get("size_mult"),
             a_cmd.get("mode"), a_cmd.get("size_mult"))
    log.info("[BRAIN] %s", note)

    return BrainDecision(
        kraken=k_cmd, sfm=s_cmd, alpaca=a_cmd,
        portfolio_note=note,
        ts=datetime.now(timezone.utc).isoformat(),
    )

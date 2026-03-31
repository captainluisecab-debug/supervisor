"""
supervisor_escalation.py — Bidirectional Bot↔Opus Escalation Bus

Each bot's local Sonnet brain writes a request file when it hits a problem
it cannot resolve locally. Opus reads it immediately (bypassing the normal
brain schedule), diagnoses with full portfolio context, and writes a response
the bot applies on its next cycle.

Qualities baked into Opus's escalation prompt:
  DYNAMIC     — responds to real-time conditions, not templates
  STRATEGIC   — considers 24h+ horizon and cross-bot impact
  INSTITUTIONAL — risk-adjusted, Kelly sizing, correlation-aware
  NEGOTIATOR  — considers bot's pushback data before deciding
  LEADER      — sets clear direction with reasoning, not just commands
  BROKER      — can reallocate capital across bots on the spot
  PROACTIVE   — scans for opportunities even when no problem is reported

Flow:
  Bot Sonnet   →  escalations/{bot}_request.json
  Supervisor   →  Opus (immediate, bypasses schedule)
  Opus         →  escalations/{bot}_response.json
  Bot Sonnet   →  reads response, applies actions
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from supervisor_settings import ANTHROPIC_API_KEY, COMMANDS_DIR

log = logging.getLogger("supervisor_escalation")

SUPERVISOR_DIR   = os.path.dirname(os.path.abspath(__file__))
ESCALATION_DIR   = os.path.join(SUPERVISOR_DIR, "escalations")
ESCALATION_LOG   = os.path.join(SUPERVISOR_DIR, "escalation_log.jsonl")

ENZOBOT_DIR  = r"C:\Projects\enzobot"
SFMBOT_DIR   = r"C:\Projects\sfmbot"
ALPACA_DIR   = r"C:\Projects\alpacabot"

os.makedirs(ESCALATION_DIR, exist_ok=True)


# ── Opus escalation prompt ────────────────────────────────────────────

def _build_escalation_prompt(request: dict, portfolio_summary: str,
                              regime_summary: str, recent_outcomes: str) -> str:
    bot         = request.get("bot", "unknown")
    problem     = request.get("problem_code", "UNKNOWN")
    urgency     = request.get("urgency", "MEDIUM")
    context     = request.get("context", {})
    question    = request.get("question", "")
    disagrees   = request.get("disagrees_with_supervisor", False)
    local_data  = request.get("local_reasoning", "")

    return f"""You are OPUS — the institutional master brain of a 3-sleeve autonomous trading ecosystem.
You are the leader, strategist, negotiator, and final decision authority.

A bot's local Sonnet brain has escalated a problem it cannot solve alone.
Your job: diagnose it, decide, and prescribe precise actions. Be direct. Be decisive.

═══════════════════════════════════════════════════
ESCALATION  [{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}]
═══════════════════════════════════════════════════
Bot:          {bot.upper()}
Problem:      {problem}
Urgency:      {urgency}
Disagrees with supervisor command: {disagrees}

Bot's question:
  {question}

Bot's local context:
  {json.dumps(context, indent=2)}

Bot's local reasoning (if disagreeing):
  {local_data or "N/A"}

═══════════════════════════════════════════════════
PORTFOLIO CONTEXT (your view as master brain)
═══════════════════════════════════════════════════
{portfolio_summary}

═══════════════════════════════════════════════════
MARKET REGIME
═══════════════════════════════════════════════════
{regime_summary}

═══════════════════════════════════════════════════
RECENT OUTCOME MEMORY (learn from these)
═══════════════════════════════════════════════════
{recent_outcomes}

═══════════════════════════════════════════════════
YOUR MANDATE AS OPUS
═══════════════════════════════════════════════════
DYNAMIC:       Respond to real conditions, not rigid rules
STRATEGIC:     Think 24h+ horizon. How does this affect overall portfolio?
INSTITUTIONAL: Risk-adjusted returns. Capital preservation first, then growth.
NEGOTIATOR:    If the bot disagrees, weigh its data seriously before deciding.
               If the bot is right, override your previous command and say so.
               If the bot is wrong, explain clearly why.
LEADER:        Set clear direction. Bots follow you. Don't be vague.
BROKER:        You can reallocate size_mult across bots if one opportunity
               is clearly better than another right now.
PROACTIVE:     Even while solving this problem, scan for opportunities.
               If you see a positive trend developing, say so.
SELF-HEALING:  Prescribe the specific parameter fix, not just advice.

═══════════════════════════════════════════════════
AVAILABLE RESPONSE ACTIONS
═══════════════════════════════════════════════════
1. override_mode
   Override supervisor command for this bot for next N cycles.
   {{"type":"override_mode","mode":"NORMAL|SCOUT|DEFENSE","size_mult":0.3-1.3,"cycles":1-6,"reason":"..."}}

2. adjust_param
   Change a specific parameter in the bot's config.
   Safe params: ADX_MIN_ENTRY(8-20), MIN_SCORE_TO_TRADE(48-70),
                attack_max_dd(2-8), SCORE_DROP_EXIT(4-15)
   {{"type":"adjust_param","param":"ADX_MIN_ENTRY","value":12,"reason":"..."}}

3. confirm_supervisor
   Confirm the existing supervisor command is correct despite bot's objection.
   {{"type":"confirm_supervisor","reason":"clear explanation for the bot"}}

4. strategic_directive
   Set a strategic stance for the bot to hold for the next N hours.
   {{"type":"strategic_directive","stance":"wait_for_adx|accumulate|reduce_risk|rotate_to_X","hours":2,"reason":"..."}}

5. opportunity_alert
   Tell this bot (or another) about an opportunity you see developing.
   {{"type":"opportunity_alert","target_bot":"enzobot|sfmbot|alpacabot","signal":"...","action":"..."}}

6. capital_reallocation
   Adjust size multipliers across bots — broker decision.
   {{"type":"capital_reallocation","enzobot_mult":0.8,"sfmbot_mult":0.5,"alpacabot_mult":1.0,"reason":"..."}}

7. escalate_to_human
   Flag something that requires human judgment.
   {{"type":"escalate_to_human","severity":"HIGH","message":"...","reason":"..."}}

═══════════════════════════════════════════════════
RESPOND WITH ONLY VALID JSON:
═══════════════════════════════════════════════════
{{
  "diagnosis": "2-4 sentence root cause analysis",
  "decision": "what you decided and why in 1 sentence",
  "negotiation_outcome": "agreed_with_bot|overruled_bot|confirmed_supervisor|N/A",
  "proactive_scan": "any opportunity or risk you spotted beyond the immediate problem",
  "actions": [
    {{...action objects...}}
  ],
  "message_to_bot": "direct message to the bot's Sonnet brain — be a leader, be clear"
}}"""


# ── Opus call ─────────────────────────────────────────────────────────

def _call_opus(prompt: str) -> Optional[dict]:
    if not ANTHROPIC_API_KEY:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        return json.loads(raw)
    except Exception as exc:
        log.error("[ESCALATION] Opus call failed: %s", exc)
        return None


# ── Response writer ───────────────────────────────────────────────────

def _write_response(bot: str, opus_result: dict, request: dict):
    path = os.path.join(ESCALATION_DIR, f"{bot}_response.json")
    payload = {
        "bot":                 bot,
        "ts":                  datetime.now(timezone.utc).isoformat(),
        "request_problem":     request.get("problem_code"),
        "diagnosis":           opus_result.get("diagnosis", ""),
        "decision":            opus_result.get("decision", ""),
        "negotiation_outcome": opus_result.get("negotiation_outcome", "N/A"),
        "proactive_scan":      opus_result.get("proactive_scan", ""),
        "message_to_bot":      opus_result.get("message_to_bot", ""),
        "actions":             opus_result.get("actions", []),
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        log.info("[ESCALATION] Response written for %s: %s actions | %s",
                 bot, len(payload["actions"]), opus_result.get("decision", "")[:80])
    except Exception as exc:
        log.error("[ESCALATION] Failed to write response: %s", exc)


def _apply_opus_actions(bot: str, actions: list, cycle: int):
    """DISABLED — governor is the single live authority for command files.
    Opus escalation actions are logged for review only, not executed.
    Governor owns all command files and .env is operator-write-only."""
    for action in actions:
        log.warning("[ESCALATION] ACTION SUPPRESSED (governor owns commands): %s -> %s",
                    bot, json.dumps(action)[:120])
    return

    # Original code below — unreachable until re-enabled.
    from supervisor_selfheal import (
        _execute_write_supervisor_cmd, _execute_adjust_policy_json,
        _execute_adjust_env, _log_action,
    )

    bot_map = {"enzobot": "kraken", "sfmbot": "sfm", "alpacabot": "alpaca"}

    for action in actions:
        atype = action.get("type", "")

        if atype == "override_mode":
            cmd_bot = bot_map.get(bot, "kraken")
            _execute_write_supervisor_cmd({
                "type":          "write_supervisor_cmd",
                "bot":           cmd_bot,
                "mode":          action.get("mode", "SCOUT"),
                "size_mult":     action.get("size_mult", 0.5),
                "entry_allowed": action.get("mode", "SCOUT") != "DEFENSE",
                "reason":        f"[OPUS ESCALATION] {action.get('reason', '')}",
            }, cycle)

        elif atype == "adjust_param":
            param = action.get("param", "")
            value = action.get("value")
            # Map to appropriate executor
            policy_params = {"attack_max_dd": "attack_rules.max_dd_pct"}
            env_params    = {"ADX_MIN_ENTRY", "MIN_SCORE_TO_TRADE", "SCORE_DROP_EXIT"}

            if param in policy_params:
                _execute_adjust_policy_json({
                    "key": policy_params[param], "value": value,
                    "reason": action.get("reason", ""),
                }, cycle)
            elif param in env_params:
                _execute_adjust_env({
                    "bot": bot, "key": param, "value": str(value),
                    "reason": action.get("reason", ""),
                }, cycle)

        elif atype == "capital_reallocation":
            for b, mult_key in [("kraken","enzobot_mult"), ("sfm","sfmbot_mult"), ("alpaca","alpacabot_mult")]:
                mult = action.get(mult_key)
                if mult is not None:
                    _execute_write_supervisor_cmd({
                        "bot": b, "mode": "NORMAL", "size_mult": float(mult),
                        "entry_allowed": True,
                        "reason": f"[OPUS BROKER] {action.get('reason', '')}",
                    }, cycle)

        elif atype == "escalate_to_human":
            log.warning("[OPUS→HUMAN] [%s] %s: %s",
                        action.get("severity"), bot, action.get("message", ""))
            _log_action(action, "HUMAN ALERT RAISED", cycle)


# ── Log ───────────────────────────────────────────────────────────────

def _log_escalation(request: dict, response: dict, cycle: int):
    entry = {
        "ts":       datetime.now(timezone.utc).isoformat(),
        "cycle":    cycle,
        "bot":      request.get("bot"),
        "problem":  request.get("problem_code"),
        "urgency":  request.get("urgency"),
        "diagnosis":response.get("diagnosis", ""),
        "decision": response.get("decision", ""),
        "negotiation_outcome": response.get("negotiation_outcome", "N/A"),
        "actions":  [a.get("type") for a in response.get("actions", [])],
    }
    try:
        with open(ESCALATION_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


# ── Main entry: called every supervisor cycle ─────────────────────────

def check_escalations(portfolio, regime, cycle: int) -> int:
    """
    Scan for bot escalation requests. For each found:
      1. Call Opus with full context
      2. Apply immediate actions
      3. Write response for bot to read
      4. Archive the request

    Returns number of escalations handled.
    """
    handled = 0

    for bot in ("enzobot", "sfmbot", "alpacabot"):
        req_path = os.path.join(ESCALATION_DIR, f"{bot}_request.json")
        if not os.path.exists(req_path):
            continue

        try:
            with open(req_path, encoding="utf-8") as f:
                request = json.load(f)
        except Exception as exc:
            log.error("[ESCALATION] Cannot read %s request: %s", bot, exc)
            continue

        log.info("[ESCALATION] %s escalated: [%s] %s",
                 bot.upper(), request.get("urgency"), request.get("problem_code"))

        # Build context for Opus
        portfolio_summary = (
            f"Total equity ${portfolio.total_equity:,.2f} | "
            f"PnL ${portfolio.total_pnl_usd:+,.2f} ({portfolio.total_pnl_pct:+.2f}%) | "
            f"DD {portfolio.total_dd_pct:.2f}% | Kill switch: {'ON' if portfolio.kill_switch_active else 'off'}\n"
        )
        for name, sleeve in portfolio.sleeves.items():
            portfolio_summary += (
                f"  {name}: eq=${sleeve.equity_usd:,.2f} pnl=${sleeve.pnl_usd:+.2f} "
                f"({sleeve.pnl_pct:+.1f}%) mode={sleeve.mode} health={sleeve.health}\n"
            )

        regime_summary = (
            f"{regime.regime} (conf {regime.confidence:.0%}) | "
            f"BTC 7d {regime.btc_7d_pct:+.1f}% | VIX {regime.vix:.1f} | "
            f"Global {regime.global_sentiment} | {' | '.join(regime.notes)}"
        )

        try:
            from supervisor_memory import load_recent_outcomes, format_outcomes_for_prompt
            outcomes = load_recent_outcomes(5)
            recent_outcomes = format_outcomes_for_prompt(outcomes)
        except Exception:
            recent_outcomes = "unavailable"

        prompt = _build_escalation_prompt(request, portfolio_summary,
                                          regime_summary, recent_outcomes)
        result = _call_opus(prompt)

        if result:
            _apply_opus_actions(bot, result.get("actions", []), cycle)
            _write_response(bot, result, request)
            _log_escalation(request, result, cycle)

            log.info("[ESCALATION] %s → %s | negotiation=%s | proactive: %s",
                     bot.upper(), result.get("decision", "")[:60],
                     result.get("negotiation_outcome", "N/A"),
                     result.get("proactive_scan", "")[:60])
        else:
            log.warning("[ESCALATION] Opus failed for %s — leaving request for retry", bot)
            handled -= 1  # don't archive if Opus failed

        # Archive request (rename to _handled)
        try:
            archive = req_path.replace("_request.json", "_request_handled.json")
            os.replace(req_path, archive)
        except Exception:
            try:
                os.remove(req_path)
            except Exception:
                pass

        handled += 1

    return handled

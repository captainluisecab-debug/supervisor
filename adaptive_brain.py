"""
adaptive_brain.py — Opus-powered adaptive reasoning for all 3 sleeves.

Architecture:
  - Cycle-level: fast deterministic rules handle 95% of cycles (zero cost)
  - Review-level: Opus reviews recent performance + outcome data when triggered
  - Gate: only calls Opus when conditions indicate current params are underperforming

Call triggers (any one fires the review):
  - Win rate declining (last 5 trades worse than last 20)
  - DD increasing (equity trending down over last hour)
  - Regime changed since last review
  - 30+ minutes since last review AND there are new trades to analyze

Cost target: ~$2-4/day across all 3 bots (conditional calls, not every cycle).
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

log = logging.getLogger("adaptive_brain")

REVIEW_COOLDOWN_SEC = 1800  # min 30 min between reviews
MODEL = "claude-sonnet-4-6"  # latest Sonnet — best reasoning at same cost


def _load_api_key() -> str:
    for env_path in [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "supervisor", ".env"),
    ]:
        if os.path.exists(env_path):
            with open(env_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("ANTHROPIC_API_KEY="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("ANTHROPIC_API_KEY", "")


def _should_review(state: dict) -> tuple[bool, str]:
    last_review = state.get("last_review_ts", 0)
    elapsed = time.time() - last_review
    if elapsed < REVIEW_COOLDOWN_SEC:
        return False, "cooldown"

    recent_wr = state.get("recent_win_rate", -1)
    overall_wr = state.get("overall_win_rate", -1)
    if recent_wr >= 0 and overall_wr > 0 and recent_wr < overall_wr - 10:
        return True, f"win_rate_declining (recent={recent_wr:.0f}% vs overall={overall_wr:.0f}%)"

    dd_trend = state.get("dd_trend", 0)
    if dd_trend < -0.5:
        return True, f"dd_increasing ({dd_trend:.1f}%/h)"

    regime_changed = state.get("regime_changed_since_review", False)
    if regime_changed:
        return True, "regime_changed"

    new_trades = state.get("trades_since_review", 0)
    if new_trades > 0 and elapsed > REVIEW_COOLDOWN_SEC:
        return True, f"{new_trades} new trades since last review"

    if elapsed > 7200:
        return True, "2h since last review (periodic)"

    return False, "no_trigger"


def review_sleeve(
    sleeve_name: str,
    current_params: dict,
    hard_bounds: dict,
    outcome_summary: dict,
    recent_trades: list,
    market_context: dict,
    portfolio_context: dict,
) -> Optional[dict]:
    """
    Call Opus to review a sleeve's performance and recommend parameter adjustments.

    Returns dict with:
      - recommended_params: {param: new_value, ...}
      - reasoning: str
      - confidence: float (0-1)
    Or None if API call fails.
    """
    api_key = _load_api_key()
    if not api_key or api_key == "disabled":
        log.warning("[BRAIN] No valid ANTHROPIC_API_KEY — skipping Opus review")
        return None

    prompt = f"""You are the adaptive brain for the {sleeve_name} trading sleeve. Your job: analyze recent performance and recommend SPECIFIC parameter changes to improve PnL.

CURRENT PARAMETERS:
{json.dumps(current_params, indent=2)}

HARD BOUNDS (do not exceed):
{json.dumps(hard_bounds, indent=2)}

OUTCOME ANALYZER SUMMARY (last 14 days):
{json.dumps(outcome_summary, indent=2)}

RECENT TRADES (last 10):
{json.dumps(recent_trades[-10:], indent=2)}

MARKET CONTEXT:
{json.dumps(market_context, indent=2)}

PORTFOLIO CONTEXT:
{json.dumps(portfolio_context, indent=2)}

RULES:
1. Only recommend changes that are supported by the outcome data
2. Stay within hard bounds
3. Be conservative — max 1-2 param changes per review
4. If performance is good, say "hold" — don't change what's working
5. Focus on the HIGHEST IMPACT change first

Respond in this EXACT JSON format only (no markdown, no explanation outside JSON):
{{"action": "adjust" or "hold", "recommended_params": {{"param_name": new_value}}, "reasoning": "one sentence why", "confidence": 0.0-1.0}}"""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        result = json.loads(text)
        log.info("[BRAIN] Opus review for %s: action=%s confidence=%.2f reasoning=%s",
                 sleeve_name, result.get("action"), result.get("confidence", 0),
                 result.get("reasoning", ""))
        return result
    except json.JSONDecodeError as exc:
        log.error("[BRAIN] Opus returned non-JSON: %s (raw: %s)", exc, text[:200])
        return None
    except Exception as exc:
        log.error("[BRAIN] Opus API call failed for %s: %s", sleeve_name, exc)
        return None


def apply_recommendations(
    current_params: dict,
    recommendations: dict,
    hard_bounds: dict,
) -> tuple[dict, list]:
    """
    Apply Opus recommendations within hard bounds.
    Returns (new_params, list_of_changes_applied).
    """
    if not recommendations or recommendations.get("action") == "hold":
        return current_params, []

    confidence = recommendations.get("confidence", 0)
    if confidence < 0.5:
        log.info("[BRAIN] Low confidence (%.2f) — holding params", confidence)
        return current_params, []

    new_params = dict(current_params)
    changes = []
    rec_params = recommendations.get("recommended_params", {})

    for param, new_val in rec_params.items():
        if param not in hard_bounds:
            log.warning("[BRAIN] Opus recommended unknown param %s — ignoring", param)
            continue
        lo, hi = hard_bounds[param]
        clamped = max(lo, min(hi, new_val))
        if clamped != new_val:
            log.info("[BRAIN] Clamped %s: opus=%s -> bounds=[%s,%s] -> %s",
                     param, new_val, lo, hi, clamped)
        old_val = current_params.get(param)
        # FIX (2026-04-24): Original condition required old_val is not None,
        # which silently dropped any Opus recommendation for a param not
        # already in current_params. This bit Kraken because supervisor_brain
        # passes the rule-engine's intended diff (often {}) as current_params,
        # not the live overrides — so every Opus recommendation Kraken's
        # rule engine wasn't already touching got dropped. 4+ logged Opus
        # reviews for kraken with action="adjust" + changes=[] confirmed.
        # Treating old_val=None as "not yet set, apply new value" — both
        # diff-from-old and brand-new override now count as a change.
        if old_val is None or abs(float(clamped) - float(old_val)) > 0.001:
            new_params[param] = clamped
            changes.append({"param": param, "old": old_val, "new": clamped,
                           "reasoning": recommendations.get("reasoning", "")})
            log.info("[BRAIN] CHANGE: %s %s -> %s (conf=%.2f)",
                     param, old_val, clamped, confidence)

    return new_params, changes


def log_review(sleeve: str, trigger: str, result: Optional[dict], changes: list) -> None:
    """Append review to brain_review_log.jsonl for audit trail."""
    record = {
        "ts": time.time(),
        "sleeve": sleeve,
        "trigger": trigger,
        "action": result.get("action", "error") if result else "api_fail",
        "confidence": result.get("confidence", 0) if result else 0,
        "reasoning": result.get("reasoning", "") if result else "",
        "changes": changes,
    }
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "brain_review_log.jsonl")
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass

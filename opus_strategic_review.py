"""
opus_strategic_review.py — Opus-powered 12h strategic review for the universe.

Runs on the existing 8AM/8PM schedule (via opus_12h_review.py).
Reads all 3 outcome analyzers, regime data, trade history, and portfolio state.
Writes opus_strategic_directive.json that Governor reads each cycle.

This is the "thinking" layer — the only component that reasons about the
whole portfolio as one coordinated team and steers toward positive PnL.

Cost: ~$2-4 per review = $4-8/day at 2 reviews/day.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone

log = logging.getLogger("opus_strategic_review")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIRECTIVE_FILE = os.path.join(BASE_DIR, "opus_strategic_directive.json")
REVIEW_LOG = os.path.join(BASE_DIR, "opus_strategic_log.jsonl")

ENZOBOT_DIR = r"C:\Projects\enzobot"
SFMBOT_DIR  = r"C:\Projects\sfmbot"
ALPACABOT_DIR = r"C:\Projects\alpacabot"


def _read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _read_jsonl_tail(path: str, n: int = 20) -> list:
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        return [json.loads(l) for l in lines[-n:] if l.strip()]
    except Exception:
        return []


def _load_api_key() -> str:
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        for line in open(env_path, encoding="utf-8"):
            if line.strip().startswith("ANTHROPIC_API_KEY="):
                return line.strip().split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def gather_universe_context() -> dict:
    """Collect all data the strategic review needs."""

    # Supervisor state
    report = _read_json(os.path.join(BASE_DIR, "supervisor_report.json"))
    hermes = _read_json(os.path.join(BASE_DIR, "hermes_context.json"))

    # Outcome analyzers
    kraken_outcomes = _read_json(os.path.join(ENZOBOT_DIR, "score_adjustments.json"))
    sfm_outcomes = _read_json(os.path.join(SFMBOT_DIR, "sfm_score_adjustments.json"))
    alpaca_outcomes = _read_json(os.path.join(ALPACABOT_DIR, "alpaca_score_adjustments.json"))

    # Brain review log (adaptive brain decisions)
    brain_reviews = _read_jsonl_tail(os.path.join(BASE_DIR, "brain_review_log.jsonl"), 10)

    # Execution truth (recent trades)
    exec_log = _read_jsonl_tail(os.path.join(BASE_DIR, "execution_log.jsonl"), 30)

    # Current sleeve states
    sleeves = report.get("sleeves", {})
    portfolio = report.get("portfolio", {})
    regime = report.get("regime", {})

    # Per-sleeve summaries
    context = {
        "review_ts": datetime.now(timezone.utc).isoformat(),
        "portfolio": {
            "total_equity": portfolio.get("total_equity_usd", 0),
            "total_pnl": portfolio.get("total_pnl_usd", 0),
            "total_pnl_pct": portfolio.get("total_pnl_pct", 0),
            "total_dd_pct": portfolio.get("total_dd_pct", 0),
            "kill_switch": portfolio.get("kill_switch_active", False),
        },
        "regime": {
            "classification": regime.get("classification", "UNKNOWN"),
            "confidence": regime.get("confidence", 0),
            "btc_7d_pct": regime.get("btc_7d_pct", 0),
            "spy_vol_10d_pct": regime.get("spy_vol_10d_pct", 0),
        },
        "kraken": {
            "equity": sleeves.get("kraken_crypto", {}).get("equity_usd", 0),
            "pnl_pct": sleeves.get("kraken_crypto", {}).get("pnl_pct", 0),
            "dd_pct": sleeves.get("kraken_crypto", {}).get("drawdown_pct", 0),
            "mode": sleeves.get("kraken_crypto", {}).get("mode", "?"),
            "positions": sleeves.get("kraken_crypto", {}).get("open_positions", 0),
            "outcome_summary": {
                "total_trades": kraken_outcomes.get("trading_exits", 0),
                "win_rate": kraken_outcomes.get("overall_win_rate", 0),
                "total_pnl": kraken_outcomes.get("total_pnl", 0),
                "pair_adjustments": kraken_outcomes.get("pair_adjustments", {}),
                "recommended_min_score": kraken_outcomes.get("recommended_min_score", 0),
            },
        },
        "sfm": {
            "equity": sleeves.get("sfm_tactical", {}).get("equity_usd", 0),
            "pnl_pct": sleeves.get("sfm_tactical", {}).get("pnl_pct", 0),
            "dd_pct": sleeves.get("sfm_tactical", {}).get("drawdown_pct", 0),
            "mode": sleeves.get("sfm_tactical", {}).get("mode", "?"),
            "positions": sleeves.get("sfm_tactical", {}).get("open_positions", 0),
            "outcome_summary": {
                "total_trades": sfm_outcomes.get("total_trades", 0),
                "win_rate": sfm_outcomes.get("overall_win_rate", 0),
                "total_pnl": sfm_outcomes.get("total_pnl", 0),
                "entry_signal_quality": sfm_outcomes.get("entry_signal_quality", {}),
                "recommendations": sfm_outcomes.get("recommendations", {}),
            },
        },
        "alpaca": {
            "equity": sleeves.get("alpaca_stocks", {}).get("equity_usd", 0),
            "pnl_pct": sleeves.get("alpaca_stocks", {}).get("pnl_pct", 0),
            "dd_pct": sleeves.get("alpaca_stocks", {}).get("drawdown_pct", 0),
            "mode": sleeves.get("alpaca_stocks", {}).get("mode", "?"),
            "positions": sleeves.get("alpaca_stocks", {}).get("open_positions", 0),
            "outcome_summary": {
                "total_trades": alpaca_outcomes.get("total_trades", 0),
                "win_rate": alpaca_outcomes.get("overall_win_rate", 0),
                "total_pnl": alpaca_outcomes.get("total_pnl", 0),
                "per_symbol": alpaca_outcomes.get("per_symbol_quality", {}),
                "recommended_blocks": alpaca_outcomes.get("recommended_blocks", []),
            },
        },
        "recent_brain_reviews": brain_reviews[-3:],
        "recent_trades": exec_log[-10:],
        "hermes_insights": hermes.get("hermes_insights", []),
    }
    return context


def run_strategic_review() -> dict:
    """
    Call Opus to produce a strategic directive for the next 12 hours.
    Returns the directive dict (also written to opus_strategic_directive.json).
    """
    api_key = _load_api_key()
    if not api_key:
        log.warning("[STRATEGIC] No API key — skipping review")
        return {}

    context = gather_universe_context()

    prompt = f"""You are the Chief Strategy Officer for a 3-bot live trading system managing ${context['portfolio']['total_equity']:.2f} of REAL MONEY.

Your job: analyze the last 12 hours of performance across all 3 sleeves and produce SPECIFIC, ACTIONABLE directives for the next 12 hours. Every recommendation must be backed by the outcome data below.

PORTFOLIO STATE:
{json.dumps(context['portfolio'], indent=2)}

MARKET REGIME:
{json.dumps(context['regime'], indent=2)}

KRAKEN SLEEVE (crypto — {context['kraken']['positions']} positions, equity ${context['kraken']['equity']:.2f}):
{json.dumps(context['kraken'], indent=2)}

SFM SLEEVE (Solana token — {context['sfm']['positions']} positions, equity ${context['sfm']['equity']:.2f}):
{json.dumps(context['sfm'], indent=2)}

ALPACA SLEEVE (US equities — {context['alpaca']['positions']} positions, equity ${context['alpaca']['equity']:.2f}):
{json.dumps(context['alpaca'], indent=2)}

RECENT BRAIN REVIEWS:
{json.dumps(context['recent_brain_reviews'], indent=2)}

RECENT TRADES (last 15):
{json.dumps(context['recent_trades'], indent=2)}

HERMES INSIGHTS:
{json.dumps(context['hermes_insights'], indent=2)}

YOUR TASK — produce a strategic directive with these sections:

1. UNIVERSE ASSESSMENT: Is the system on track for positive PnL? What is the biggest risk and biggest opportunity right now?

2. PER-SLEEVE DIRECTIVES: For each sleeve, what specific action should Governor take in the next 12h?
   - Should it be more aggressive, more defensive, or hold?
   - Should entry criteria be tightened or loosened?
   - Which positions should be held, which should be cut, which new entries should be sought?

3. CROSS-SLEEVE PRIORITIES: Given limited capital, where should the system focus?
   - Which sleeve has the best risk-adjusted opportunity right now?
   - Should capital be rebalanced between sleeves?

4. SPECIFIC PARAMETER RECOMMENDATIONS: Only if outcome data supports a change.
   - Name the exact parameter, current value, recommended value, and evidence.

5. RISK WARNINGS: Anything that could hurt the portfolio in the next 12h.

Respond ONLY with valid JSON in this format:
{{
  "universe_assessment": "2-3 sentences",
  "biggest_risk": "one sentence",
  "biggest_opportunity": "one sentence",
  "kraken_directive": {{
    "posture": "AGGRESSIVE|MODERATE|DEFENSIVE|HOLD",
    "action": "specific instruction",
    "reasoning": "evidence-based"
  }},
  "sfm_directive": {{
    "posture": "AGGRESSIVE|MODERATE|DEFENSIVE|HOLD",
    "action": "specific instruction",
    "reasoning": "evidence-based"
  }},
  "alpaca_directive": {{
    "posture": "AGGRESSIVE|MODERATE|DEFENSIVE|HOLD",
    "action": "specific instruction",
    "reasoning": "evidence-based"
  }},
  "capital_priority": "which sleeve to favor and why",
  "param_recommendations": [
    {{"sleeve": "...", "param": "...", "current": "...", "recommended": "...", "evidence": "..."}}
  ],
  "risk_warnings": ["warning 1", "warning 2"]
}}"""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        directive = json.loads(text)

        directive["_meta"] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "model": "claude-sonnet-4-20250514",
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
            "portfolio_equity": context["portfolio"]["total_equity"],
        }

        # Write directive for Governor
        tmp = DIRECTIVE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(directive, f, indent=2)
        os.replace(tmp, DIRECTIVE_FILE)

        # Append to review log
        with open(REVIEW_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": directive["_meta"]["ts"], "directive": directive}) + "\n")

        log.info("[STRATEGIC] Review complete: %s | risk=%s | priority=%s",
                 directive.get("universe_assessment", "")[:80],
                 directive.get("biggest_risk", "")[:50],
                 directive.get("capital_priority", "")[:50])
        return directive

    except json.JSONDecodeError as exc:
        log.error("[STRATEGIC] Opus returned non-JSON: %s", exc)
        return {}
    except Exception as exc:
        log.error("[STRATEGIC] Review failed: %s", exc)
        return {}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = run_strategic_review()
    if result:
        print(json.dumps(result, indent=2))
    else:
        print("Review failed or no API key.")

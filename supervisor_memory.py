"""
supervisor_memory.py — Outcome memory for the unified Claude brain.

After every brain decision, saves a snapshot of equity per sleeve.
On the next brain call, compares equity before vs after to score
whether the decision was correct, wrong, or neutral.

Outcomes are logged to brain_outcomes.jsonl and fed back into
the Claude prompt so it learns from its own decisions over time.

Verdict logic per sleeve:
  CORRECT — decision protected or grew capital as intended
  WRONG   — decision was too cautious (missed gains) or too aggressive (lost money)
  NEUTRAL — equity flat, insufficient signal

This is what separates a learning system from a static one.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

log = logging.getLogger("supervisor_memory")

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
OUTCOMES_FILE = os.path.join(BASE_DIR, "brain_outcomes.jsonl")
PENDING_FILE  = os.path.join(BASE_DIR, "brain_pending.json")

# Threshold: equity change > this % is considered meaningful
SIGNAL_THRESHOLD = 0.15


@dataclass
class SleeveOutcome:
    sleeve: str
    mode_assigned: str
    size_mult: float
    equity_before: float
    equity_after: float
    chg_pct: float
    verdict: str      # CORRECT | WRONG | NEUTRAL
    reasoning: str


@dataclass
class BrainOutcome:
    decision_ts: str
    outcome_ts: str
    total_before: float
    total_after: float
    total_chg_pct: float
    sleeves: List[SleeveOutcome]
    overall_verdict: str   # CORRECT | WRONG | MIXED | NEUTRAL


def _verdict(mode: str, chg_pct: float) -> tuple[str, str]:
    """
    Determine if the decision was correct given the outcome.
    Returns (verdict, reasoning).
    """
    defensive = mode in ("SCOUT", "DEFENSE")
    sig = abs(chg_pct) >= SIGNAL_THRESHOLD

    if not sig:
        return "NEUTRAL", f"equity flat ({chg_pct:+.2f}%) — no clear signal"

    if defensive and chg_pct < -SIGNAL_THRESHOLD:
        return "CORRECT", f"cautious mode protected capital ({chg_pct:+.2f}%)"
    if defensive and chg_pct > SIGNAL_THRESHOLD:
        return "WRONG", f"too cautious — missed {chg_pct:+.2f}% gain"
    if not defensive and chg_pct > SIGNAL_THRESHOLD:
        return "CORRECT", f"NORMAL mode captured {chg_pct:+.2f}% gain"
    if not defensive and chg_pct < -SIGNAL_THRESHOLD:
        return "WRONG", f"too aggressive — lost {chg_pct:+.2f}% in NORMAL mode"

    return "NEUTRAL", f"mixed signal ({chg_pct:+.2f}%)"


def save_pending(decision: dict, portfolio) -> None:
    """
    Save current equity snapshot + decision before it takes effect.
    Called immediately after Claude's decision is written.
    """
    sleeves = portfolio.sleeves
    pending = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "decision": {
            "kraken": decision.get("kraken", {}),
            "sfm":    decision.get("sfm", {}),
            "alpaca": decision.get("alpaca", {}),
        },
        "equity_before": {
            "kraken": sleeves.get("kraken_crypto").equity_usd if sleeves.get("kraken_crypto") else 0,
            "sfm":    sleeves.get("sfm_tactical").equity_usd  if sleeves.get("sfm_tactical")  else 0,
            "alpaca": sleeves.get("alpaca_stocks").equity_usd if sleeves.get("alpaca_stocks") else 0,
            "total":  portfolio.total_equity,
        },
    }
    try:
        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump(pending, f, indent=2)
    except Exception as exc:
        log.error("Failed to save pending: %s", exc)


def evaluate_and_log(portfolio) -> Optional[BrainOutcome]:
    """
    Compare current equity to the pending snapshot.
    Score the previous decision and log the outcome.
    Returns BrainOutcome or None if no pending decision exists.
    """
    if not os.path.exists(PENDING_FILE):
        return None

    try:
        with open(PENDING_FILE, encoding="utf-8") as f:
            pending = json.load(f)
    except Exception as exc:
        log.error("Failed to load pending: %s", exc)
        return None

    sleeves_now = portfolio.sleeves
    eq_before   = pending.get("equity_before", {})
    decision    = pending.get("decision", {})
    decision_ts = pending.get("ts", "")

    sleeve_map = {
        "kraken": ("kraken_crypto", "kraken"),
        "sfm":    ("sfm_tactical",  "sfm"),
        "alpaca": ("alpaca_stocks", "alpaca"),
    }

    outcomes = []
    verdicts = []

    for key, (state_key, dec_key) in sleeve_map.items():
        sleeve_now  = sleeves_now.get(state_key)
        eq_now      = sleeve_now.equity_usd if sleeve_now else 0
        eq_then     = eq_before.get(key, eq_now)
        chg_pct     = (eq_now - eq_then) / eq_then * 100 if eq_then > 0 else 0.0
        dec         = decision.get(dec_key, {})
        mode        = dec.get("mode", "NORMAL")
        size_mult   = float(dec.get("size_mult", 1.0))

        verdict, reasoning = _verdict(mode, chg_pct)
        verdicts.append(verdict)

        outcomes.append(SleeveOutcome(
            sleeve=key,
            mode_assigned=mode,
            size_mult=size_mult,
            equity_before=eq_then,
            equity_after=eq_now,
            chg_pct=chg_pct,
            verdict=verdict,
            reasoning=reasoning,
        ))

    total_before = eq_before.get("total", portfolio.total_equity)
    total_after  = portfolio.total_equity
    total_chg    = (total_after - total_before) / total_before * 100 if total_before > 0 else 0.0

    correct_ct = verdicts.count("CORRECT")
    wrong_ct   = verdicts.count("WRONG")
    if correct_ct > wrong_ct:     overall = "CORRECT"
    elif wrong_ct > correct_ct:   overall = "WRONG"
    elif correct_ct == wrong_ct and correct_ct > 0: overall = "MIXED"
    else:                         overall = "NEUTRAL"

    outcome = BrainOutcome(
        decision_ts=decision_ts,
        outcome_ts=datetime.now(timezone.utc).isoformat(),
        total_before=total_before,
        total_after=total_after,
        total_chg_pct=total_chg,
        sleeves=outcomes,
        overall_verdict=overall,
    )

    # Log to outcomes file
    try:
        record = {
            "decision_ts":    outcome.decision_ts,
            "outcome_ts":     outcome.outcome_ts,
            "total_chg_pct":  round(total_chg, 3),
            "overall_verdict": overall,
            "sleeves": [
                {
                    "sleeve":       o.sleeve,
                    "mode":         o.mode_assigned,
                    "size_mult":    o.size_mult,
                    "eq_before":    round(o.equity_before, 2),
                    "eq_after":     round(o.equity_after, 2),
                    "chg_pct":      round(o.chg_pct, 3),
                    "verdict":      o.verdict,
                    "reasoning":    o.reasoning,
                }
                for o in outcomes
            ],
        }
        with open(OUTCOMES_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        log.info(
            "[MEMORY] Decision scored: overall=%s | kraken=%s sfm=%s alpaca=%s | portfolio %+.2f%%",
            overall,
            outcomes[0].verdict if outcomes else "?",
            outcomes[1].verdict if len(outcomes) > 1 else "?",
            outcomes[2].verdict if len(outcomes) > 2 else "?",
            total_chg,
        )
    except Exception as exc:
        log.error("Failed to log outcome: %s", exc)

    return outcome


def load_recent_outcomes(n: int = 8) -> List[dict]:
    """Load last n scored outcomes for Claude context."""
    if not os.path.exists(OUTCOMES_FILE):
        return []
    try:
        with open(OUTCOMES_FILE, encoding="utf-8") as f:
            lines = f.readlines()
        results = []
        for line in lines[-n:]:
            results.append(json.loads(line.strip()))
        return results
    except Exception:
        return []


def format_outcomes_for_prompt(outcomes: List[dict]) -> str:
    """Format outcome history into a readable block for Claude's prompt."""
    if not outcomes:
        return "  No outcome history yet — this is an early decision."

    lines = []
    for o in outcomes:
        ts      = o.get("decision_ts", "")[:16]
        overall = o.get("overall_verdict", "?")
        chg     = o.get("total_chg_pct", 0)
        sleeves = o.get("sleeves", [])

        sleeve_parts = []
        for s in sleeves:
            sleeve_parts.append(
                f"{s['sleeve']}:{s['mode']}({s['chg_pct']:+.2f}%={s['verdict'][0]})"
            )

        lines.append(
            f"  {ts} | portfolio {chg:+.2f}% | {overall} | {' | '.join(sleeve_parts)}"
        )

    # Summary stats
    verdicts     = [o.get("overall_verdict") for o in outcomes]
    correct_rate = verdicts.count("CORRECT") / len(verdicts) * 100 if verdicts else 0
    lines.append(f"  Accuracy: {correct_rate:.0f}% correct over last {len(outcomes)} decisions")

    return "\n".join(lines)

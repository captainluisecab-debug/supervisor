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
_EXEC_LOG     = os.path.join(BASE_DIR, "execution_log.jsonl")

# Threshold: equity change > this % is considered meaningful (equity-delta fallback only)
SIGNAL_THRESHOLD = 0.15

# Fill PnL threshold — moves below this are treated as noise
_FILL_PNL_THRESHOLD = 1.0

# Map bot name in execution_log.jsonl to sleeve key
_BOT_TO_SLEEVE = {"enzo": "kraken", "sfm": "sfm", "alpaca": "alpaca"}


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


def _verdict(mode: str, chg_pct: float,
             had_fills: bool = False, fill_pnl_usd: float = 0.0) -> tuple[str, str]:
    """
    Determine if the decision was correct given the outcome.

    Primary signal: fill PnL when fills occurred in the decision window.
      had_fills  — True if any execution_log entry matched this sleeve in the window.
                   Tracked separately from fill_pnl_usd because BUY fills legitimately
                   log pnl_usd=0.0, so zero pnl alone does not mean no fills occurred.
      fill_pnl_usd — sum of pnl_usd for matched fills (may be 0.0 on BUY-only windows).

    Fallback: equity delta, retained in reasoning for observability; never drives verdict.

    Returns (verdict, reasoning).
    """
    eq_fallback = f"equity delta {chg_pct:+.2f}% (fallback, not scored)"
    defensive   = mode in ("SCOUT", "DEFENSE")

    if had_fills:
        if fill_pnl_usd > _FILL_PNL_THRESHOLD:
            if not defensive:
                return "CORRECT", (
                    f"NORMAL mode captured fill pnl ${fill_pnl_usd:+.2f} | {eq_fallback}"
                )
            else:
                return "NEUTRAL", (
                    f"fills in cautious mode — not conclusive "
                    f"(pnl ${fill_pnl_usd:+.2f}) | {eq_fallback}"
                )
        elif fill_pnl_usd < -_FILL_PNL_THRESHOLD:
            return "WRONG", (
                f"fill pnl ${fill_pnl_usd:+.2f} in {mode} mode | {eq_fallback}"
            )
        else:
            return "NEUTRAL", (
                f"fills occurred but pnl within noise threshold "
                f"(${fill_pnl_usd:+.2f}) | {eq_fallback}"
            )

    # No fills in decision window — no execution evidence; equity delta is not scored
    return "NEUTRAL", f"no fills in decision window | {eq_fallback}"


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

    # Atomically claim the pending file before scoring.
    # Prevents a crash between evaluate_and_log() and save_pending() from causing
    # the same stale snapshot to be re-scored against a later equity value on restart.
    _scoring_path = PENDING_FILE + ".scoring"
    try:
        os.replace(PENDING_FILE, _scoring_path)
    except Exception as exc:
        log.error("Failed to claim pending file for scoring: %s", exc)
        return None

    try:
        with open(_scoring_path, encoding="utf-8") as f:
            pending = json.load(f)
    except Exception as exc:
        log.error("Failed to load pending: %s", exc)
        # Restore so the snapshot is not permanently lost
        try:
            os.replace(_scoring_path, PENDING_FILE)
        except Exception:
            pass
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

    # ── Scan execution log for fills within the decision window ─────────
    scoring_ts = datetime.now(timezone.utc)
    try:
        window_start = datetime.fromisoformat(decision_ts)
    except (ValueError, TypeError):
        window_start = scoring_ts  # unparseable ts — no fills will match

    sleeve_had_fills = {k: False for k in sleeve_map}
    sleeve_fill_pnl  = {k: 0.0   for k in sleeve_map}
    try:
        if os.path.exists(_EXEC_LOG):
            with open(_EXEC_LOG, encoding="utf-8") as f:
                for raw_line in f:
                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue
                    try:
                        entry   = json.loads(raw_line)
                        exec_ts = datetime.fromisoformat(entry["ts"])
                        if window_start <= exec_ts <= scoring_ts:
                            sleeve = _BOT_TO_SLEEVE.get(entry.get("bot", ""))
                            if sleeve in sleeve_had_fills:
                                sleeve_had_fills[sleeve] = True
                                sleeve_fill_pnl[sleeve] += float(entry.get("pnl_usd", 0.0))
                    except Exception:
                        continue  # malformed line — skip
    except Exception as exc:
        log.warning("[MEMORY] Could not read execution log for scoring: %s", exc)

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

        verdict, reasoning = _verdict(
            mode, chg_pct,
            had_fills=sleeve_had_fills[key],
            fill_pnl_usd=sleeve_fill_pnl[key],
        )
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
        outcome_ts=scoring_ts.isoformat(),
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

    # Remove the claimed scoring file — outcome has been written to brain_outcomes.jsonl
    try:
        os.remove(_scoring_path)
    except Exception:
        pass

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
        return "  No outcome history yet — this is an early decision.\n  (scoring method: scored by fill PnL where fills occurred; NEUTRAL where no fills (equity delta in reasoning only))"

    lines = ["  (scoring method: scored by fill PnL where fills occurred; NEUTRAL where no fills (equity delta in reasoning only))"]
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

    return "\n".join(lines)

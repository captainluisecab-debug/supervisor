"""
supervisor_allocation.py — Performance-Based Allocation Engine.

Analyzes scored outcomes per sleeve over a rolling window and recommends
size_mult adjustments for Claude to consider.

Methodology (Sharpe-inspired, simplified):
  - Collect last WINDOW outcomes per sleeve
  - Compute: win_rate, avg_return, std_return, Sharpe-like ratio
  - Map ratio to a performance score (0.0–1.0)
  - Recommend size_mult: current +/- adjustment, bounded by hard limits

Claude sees the recommendations and can apply them or override based on
regime — it stays the decision maker, but now has data-driven guidance.

Boundaries enforced by this engine (Claude respects these):
  MIN_MULT  = 0.3   — never starve a sleeve completely
  MAX_MULT  = 1.3   — never over-concentrate
  MAX_DELTA = 0.2   — max change per brain call (prevents wild swings)
"""
from __future__ import annotations

import json
import logging
import math
import os
import statistics
from dataclasses import dataclass
from typing import List, Optional

log = logging.getLogger("supervisor_allocation")

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
OUTCOMES_FILE = os.path.join(BASE_DIR, "brain_outcomes.jsonl")

# Command files to read current assigned mult
COMMANDS_DIR = os.path.join(BASE_DIR, "commands")
CMD_FILES = {
    "kraken": os.path.join(COMMANDS_DIR, "kraken_cmd.json"),
    "sfm":    os.path.join(COMMANDS_DIR, "sfm_cmd.json"),
    "alpaca": os.path.join(COMMANDS_DIR, "alpaca_cmd.json"),
}

# Allocation boundaries
MIN_MULT  = 0.3
MAX_MULT  = 1.3
MAX_DELTA = 0.2   # max size_mult change per brain call
WINDOW    = 20    # number of past scored decisions to analyze


@dataclass
class SleeveAllocation:
    sleeve: str
    current_mult: float
    win_rate: float          # % CORRECT (excluding NEUTRAL)
    avg_return: float        # mean chg_pct across all outcomes
    std_return: float        # std dev of returns
    sharpe: float            # avg_return / std_return (0 if std=0)
    score: float             # composite 0.0–1.0
    kelly_mult: float        # Kelly Criterion suggestion
    recommended_mult: float  # blended final suggestion
    direction: str           # UP | DOWN | HOLD
    sample_size: int         # how many data points used
    reasoning: str


def _load_current_mult(sleeve: str) -> float:
    """Read the most recently assigned size_mult from the command file."""
    path = CMD_FILES.get(sleeve, "")
    try:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return float(data.get("size_mult", 0.8))
    except Exception:
        pass
    return 0.8  # neutral default


def _load_sleeve_outcomes(sleeve: str, n: int = WINDOW) -> list:
    """Extract per-sleeve outcome rows from the last n brain_outcomes."""
    if not os.path.exists(OUTCOMES_FILE):
        return []
    try:
        with open(OUTCOMES_FILE, encoding="utf-8") as f:
            lines = f.readlines()
        rows = []
        for line in lines[-n:]:
            try:
                record = json.loads(line.strip())
                for s in record.get("sleeves", []):
                    if s.get("sleeve") == sleeve:
                        rows.append(s)
                        break
            except Exception:
                continue
        return rows
    except Exception:
        return []


def _sharpe_like(returns: list) -> float:
    """Simplified Sharpe: mean / std. Returns 0 if insufficient data."""
    if len(returns) < 2:
        return 0.0
    avg = statistics.mean(returns)
    std = statistics.stdev(returns)
    if std == 0:
        return 1.0 if avg > 0 else (-1.0 if avg < 0 else 0.0)
    return avg / std


def kelly_size_mult(rows: list, current_mult: float) -> float:
    """
    Kelly Criterion: compute mathematically optimal bet fraction.

    Formula: K = W - (1 - W) / (avg_win / avg_loss)
      W        = win rate (fraction of CORRECT outcomes, ignoring NEUTRAL)
      avg_win  = average gain when CORRECT
      avg_loss = average |loss| when WRONG

    Kelly fraction is then mapped to size_mult range [MIN_MULT, MAX_MULT].
    Full Kelly is aggressive — we use Half-Kelly (K * 0.5) for safety.

    Returns suggested size_mult, or current_mult if insufficient data.
    """
    if len(rows) < 6:
        return current_mult   # not enough data for Kelly to be reliable

    verdicts = [r.get("verdict", "NEUTRAL") for r in rows]
    returns  = [r.get("chg_pct", 0.0) for r in rows]

    wins  = [returns[i] for i, v in enumerate(verdicts) if v == "CORRECT"]
    loses = [abs(returns[i]) for i, v in enumerate(verdicts) if v == "WRONG"]

    if not wins or not loses:
        return current_mult

    W       = len(wins) / (len(wins) + len(loses))
    avg_win = statistics.mean(wins)
    avg_los = statistics.mean(loses)

    if avg_win <= 0 or avg_los <= 0:
        return current_mult

    # Kelly fraction (raw)
    ratio = avg_win / avg_los
    kelly = W - (1 - W) / ratio

    # Half-Kelly — less aggressive, more robust out of sample
    half_kelly = kelly * 0.5

    # Map Kelly fraction to size_mult
    # Kelly 0.0 = neutral -> 0.8x
    # Kelly 0.5+ = strong edge -> 1.3x
    # Kelly < 0 = no edge -> 0.3x
    if half_kelly <= 0:
        suggested = MIN_MULT
    elif half_kelly >= 0.4:
        suggested = MAX_MULT
    else:
        # Linear interpolation: 0.0 -> 0.8x, 0.4 -> 1.3x
        suggested = 0.8 + (half_kelly / 0.4) * (MAX_MULT - 0.8)

    # Cap change per call
    delta     = suggested - current_mult
    delta     = max(-MAX_DELTA, min(MAX_DELTA, delta))
    result    = max(MIN_MULT, min(MAX_MULT, current_mult + delta))
    return round(result, 2)


def _score_from_sharpe(sharpe: float, win_rate: float) -> float:
    """
    Map Sharpe ratio + win rate to a composite score 0.0–1.0.
    Sharpe >= 1.0 and win_rate >= 0.6 -> score near 1.0
    Sharpe <= -1.0 or win_rate <= 0.3 -> score near 0.0
    """
    # Normalize Sharpe to 0–1 range (clip at ±2)
    sharpe_norm = (max(-2.0, min(2.0, sharpe)) + 2.0) / 4.0  # 0.0–1.0

    # Win rate already 0.0–1.0
    # Weighted average: Sharpe 60%, win rate 40%
    score = sharpe_norm * 0.60 + win_rate * 0.40
    return round(max(0.0, min(1.0, score)), 3)


def _recommend_mult(score: float, current: float) -> tuple[float, str]:
    """
    Map score to a recommended size_mult.
    Returns (recommended_mult, direction).
    """
    # Target mult based on score
    if score >= 0.75:
        target = min(current + 0.15, MAX_MULT)
        direction = "UP"
    elif score >= 0.55:
        target = min(current + 0.05, MAX_MULT)
        direction = "UP"
    elif score >= 0.40:
        target = current  # hold
        direction = "HOLD"
    elif score >= 0.25:
        target = max(current - 0.10, MIN_MULT)
        direction = "DOWN"
    else:
        target = max(current - 0.20, MIN_MULT)
        direction = "DOWN"

    # Cap change at MAX_DELTA per call
    delta = target - current
    delta = max(-MAX_DELTA, min(MAX_DELTA, delta))
    recommended = round(max(MIN_MULT, min(MAX_MULT, current + delta)), 2)

    return recommended, direction


def _build_reasoning(sleeve: str, win_rate: float, avg_return: float,
                     sharpe: float, score: float, direction: str,
                     sample_size: int) -> str:
    if sample_size < 3:
        return f"insufficient data ({sample_size} samples) — holding current allocation"
    parts = [
        f"win_rate={win_rate:.0%}",
        f"avg_return={avg_return:+.2f}%",
        f"sharpe={sharpe:+.2f}",
        f"score={score:.2f}",
        f"-> {direction}",
    ]
    return " | ".join(parts)


def compute_allocations() -> List[SleeveAllocation]:
    """
    Compute allocation recommendations for all three sleeves.
    Returns list of SleeveAllocation objects.
    """
    allocations = []

    for sleeve in ("kraken", "sfm", "alpaca"):
        current_mult = _load_current_mult(sleeve)
        rows = _load_sleeve_outcomes(sleeve, WINDOW)

        if not rows:
            allocations.append(SleeveAllocation(
                sleeve=sleeve,
                current_mult=current_mult,
                win_rate=0.0,
                avg_return=0.0,
                std_return=0.0,
                sharpe=0.0,
                score=0.5,
                kelly_mult=current_mult,
                recommended_mult=current_mult,
                direction="HOLD",
                sample_size=0,
                reasoning="no outcome history — holding current allocation",
            ))
            continue

        returns    = [r.get("chg_pct", 0.0) for r in rows]
        verdicts   = [r.get("verdict", "NEUTRAL") for r in rows]
        decided    = [v for v in verdicts if v != "NEUTRAL"]
        correct_ct = decided.count("CORRECT")
        win_rate   = correct_ct / len(decided) if decided else 0.5

        avg_return = statistics.mean(returns) if returns else 0.0
        std_return = statistics.stdev(returns) if len(returns) > 1 else 0.0
        sharpe     = _sharpe_like(returns)
        score      = _score_from_sharpe(sharpe, win_rate)

        # Sharpe-based recommendation
        sharpe_rec, direction = _recommend_mult(score, current_mult)

        # Kelly Criterion recommendation
        kelly_rec = kelly_size_mult(rows, current_mult)

        # Blend: average of Sharpe and Kelly when Kelly has enough data
        if len(rows) >= 6:
            blended = (sharpe_rec + kelly_rec) / 2
            # Re-apply delta cap on blended result
            delta = blended - current_mult
            delta = max(-MAX_DELTA, min(MAX_DELTA, delta))
            recommended = round(max(MIN_MULT, min(MAX_MULT, current_mult + delta)), 2)
            # Update direction based on final recommended
            if recommended > current_mult + 0.02:   direction = "UP"
            elif recommended < current_mult - 0.02: direction = "DOWN"
            else:                                    direction = "HOLD"
        else:
            recommended = sharpe_rec
            kelly_rec   = current_mult  # not enough data for Kelly

        reasoning = _build_reasoning(
            sleeve, win_rate, avg_return, sharpe, score, direction, len(rows)
        )

        allocations.append(SleeveAllocation(
            sleeve=sleeve,
            current_mult=current_mult,
            win_rate=win_rate,
            avg_return=avg_return,
            std_return=std_return,
            sharpe=sharpe,
            score=score,
            kelly_mult=kelly_rec,
            recommended_mult=recommended,
            direction=direction,
            sample_size=len(rows),
            reasoning=reasoning,
        ))

    return allocations


def format_allocations_for_prompt(allocations: List[SleeveAllocation]) -> str:
    """Format allocation recommendations as a readable block for Claude's prompt."""
    if not allocations:
        return "  Allocation engine: no data available"

    lines = []
    for a in allocations:
        arrow = "^" if a.direction == "UP" else ("v" if a.direction == "DOWN" else "=")
        lines.append(
            f"  {a.sleeve:<8} | score={a.score:.2f} | "
            f"win={a.win_rate:.0%} | sharpe={a.sharpe:+.2f} | kelly={a.kelly_mult:.1f}x | "
            f"avg={a.avg_return:+.2f}% | "
            f"current={a.current_mult:.1f}x -> suggest={a.recommended_mult:.1f}x [{arrow}] "
            f"(n={a.sample_size})"
        )

    lines.append("")
    lines.append(
        "  Use suggestions as guidance. Override if regime or sleeve health dictates."
    )
    lines.append(
        f"  Bounds: min={MIN_MULT}x  max={MAX_MULT}x  max_change_per_call=+/-{MAX_DELTA}x"
    )

    return "\n".join(lines)

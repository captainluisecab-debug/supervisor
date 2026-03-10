"""
golive_tracker.py — Daily go-live readiness scorecard for all 3 bots.

Reads state + execution log, scores each bot against go-live criteria,
writes golive_report.txt and prints a clear summary.

Criteria per bot:
  1. Completed trades >= 30               (weight: 25%)
  2. Win rate >= 52%                      (weight: 20%)
  3. Avg win / avg loss >= 1.5            (weight: 20%)
  4. Max drawdown < 10%                   (weight: 20%)
  5. Profitable days >= 75% of days seen  (weight: 15%)

Overall score 0-100. Go-live when ALL 5 criteria met AND score >= 80.
"""
from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("golive_tracker")

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
EXEC_LOG   = os.path.join(BASE_DIR, "execution_log.jsonl")
REPORT_FILE = os.path.join(BASE_DIR, "golive_report.txt")
GOLIVE_FLAG = os.path.join(BASE_DIR, "GOLIVE_READY.txt")

ALPACA_STATE = r"C:\Projects\alpacabot\alpaca_state.json"
SFM_STATE    = r"C:\Projects\sfmbot\sfm_state.json"
ENZO_STATE   = r"C:\Projects\enzobot\state.json"
ENZO_DAILY   = r"C:\Projects\enzobot\data\daily_report.json"

# ── Thresholds ───────────────────────────────────────────────────────────────
MIN_TRADES       = 30      # criterion 1
MIN_WIN_RATE     = 0.52    # criterion 2 (52%)
MIN_WIN_LOSS_R   = 1.5     # criterion 3  avg_win / avg_loss
MAX_DRAWDOWN     = 0.10    # criterion 4  (10% — stored as positive fraction)
MIN_PROF_DAYS    = 0.75    # criterion 5  (75% of days seen)

WEIGHTS = {
    "trades":    25,
    "win_rate":  20,
    "win_loss":  20,
    "drawdown":  20,
    "prof_days": 15,
}
assert sum(WEIGHTS.values()) == 100

GO_LIVE_MIN_SCORE = 80


# ── State loaders ─────────────────────────────────────────────────────────────

def _load_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def load_alpaca_state() -> dict:
    raw = _load_json(ALPACA_STATE)
    # alpaca_state.json: total_trades, winning_trades, losing_trades,
    # realized_pnl_usd, positions, equity_peak (not stored — derive from cash context)
    return {
        "total_trades":   int(raw.get("total_trades", 0)),
        "winning_trades": int(raw.get("winning_trades", 0)),
        "losing_trades":  int(raw.get("losing_trades", 0)),
        "realized_pnl":   float(raw.get("realized_pnl_usd", 0.0)),
    }


def load_sfm_state() -> dict:
    raw = _load_json(SFM_STATE)
    return {
        "total_trades":   int(raw.get("total_trades", 0)),
        "winning_trades": int(raw.get("winning_trades", 0)),
        "losing_trades":  int(raw.get("losing_trades", 0)),
        "realized_pnl":   float(raw.get("realized_pnl_usd", 0.0)),
        "usdc_balance":   float(raw.get("usdc_balance", 1_000.0)),
    }


def load_enzo_state() -> dict:
    raw = _load_json(ENZO_STATE)
    return {
        "realized_pnl": float(raw.get("realized_pnl", 0.0)),
        "equity_peak":  float(raw.get("equity_peak", 0.0)),
        "cash":         float(raw.get("cash", 0.0)),
    }


def load_enzo_daily() -> dict:
    """Returns {date_str: {wins, losses, net_pnl_usd, trades}} from enzobot's daily_report."""
    raw = _load_json(ENZO_DAILY)
    result: dict = {}
    for date_str, d in raw.items():
        result[date_str] = {
            "wins":        int(d.get("wins", 0)),
            "losses":      int(d.get("losses", 0)),
            "trades":      int(d.get("trades", 0)),
            "net_pnl_usd": float(d.get("net_pnl_usd", 0.0)),
        }
    return result


# ── Execution log parser ──────────────────────────────────────────────────────

def load_execution_log() -> List[dict]:
    """Return all entries from execution_log.jsonl.  Returns [] if missing."""
    if not os.path.exists(EXEC_LOG):
        return []
    entries = []
    try:
        with open(EXEC_LOG, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        pass
    return entries


def compute_exec_stats(executions: List[dict], bot_name: str) -> dict:
    """
    From execution_log.jsonl entries for a given bot, compute:
      - total_trades, winning_trades, losing_trades
      - win_pnl_list, loss_pnl_list (for avg win / avg loss ratio)
      - daily_pnl: {date_str: net_pnl_usd}
      - peak_equity, min_equity (for drawdown)
    Only SELL entries carry pnl_usd (buys have pnl_usd=0).
    """
    sells = [e for e in executions if e.get("bot") == bot_name and e.get("side") == "SELL"]

    total_trades   = len(sells)
    winning_trades = sum(1 for e in sells if e.get("pnl_usd", 0.0) > 0)
    losing_trades  = sum(1 for e in sells if e.get("pnl_usd", 0.0) <= 0)

    win_pnl  = [e["pnl_usd"] for e in sells if e.get("pnl_usd", 0.0) > 0]
    loss_pnl = [abs(e["pnl_usd"]) for e in sells if e.get("pnl_usd", 0.0) < 0]

    # Daily P&L grouping
    daily_pnl: Dict[str, float] = defaultdict(float)
    running_equity = 0.0
    peak_equity    = 0.0
    min_drawdown   = 0.0   # worst intraday drawdown fraction (positive = loss)

    for e in sells:
        pnl  = e.get("pnl_usd", 0.0)
        date = e.get("ts", "")[:10]  # YYYY-MM-DD
        daily_pnl[date] += pnl
        running_equity   += pnl
        if running_equity > peak_equity:
            peak_equity = running_equity
        if peak_equity > 0:
            dd = (peak_equity - running_equity) / peak_equity
            if dd > min_drawdown:
                min_drawdown = dd

    return {
        "total_trades":   total_trades,
        "winning_trades": winning_trades,
        "losing_trades":  losing_trades,
        "win_pnl":        win_pnl,
        "loss_pnl":       loss_pnl,
        "daily_pnl":      dict(daily_pnl),
        "max_drawdown":   min_drawdown,  # fraction, 0–1
    }


# ── Per-bot stat builders ────────────────────────────────────────────────────

class BotStats:
    """Consolidated stats for one bot, blending state JSON + exec log."""

    def __init__(
        self,
        name: str,
        label: str,
        total_trades: int,
        winning_trades: int,
        losing_trades: int,
        win_pnl: List[float],
        loss_pnl: List[float],
        daily_pnl: Dict[str, float],
        max_drawdown: float,        # 0.0–1.0, positive = loss fraction
    ):
        self.name           = name
        self.label          = label
        self.total_trades   = total_trades
        self.winning_trades = winning_trades
        self.losing_trades  = losing_trades
        self.win_pnl        = win_pnl
        self.loss_pnl       = loss_pnl
        self.daily_pnl      = daily_pnl    # {date: net_pnl_usd}
        self.max_drawdown   = max_drawdown  # fraction

    @property
    def win_rate(self) -> Optional[float]:
        if self.total_trades == 0:
            return None
        return self.winning_trades / self.total_trades

    @property
    def avg_win(self) -> Optional[float]:
        return (sum(self.win_pnl) / len(self.win_pnl)) if self.win_pnl else None

    @property
    def avg_loss(self) -> Optional[float]:
        return (sum(self.loss_pnl) / len(self.loss_pnl)) if self.loss_pnl else None

    @property
    def win_loss_ratio(self) -> Optional[float]:
        if self.avg_win is None or self.avg_loss is None or self.avg_loss == 0:
            return None
        return self.avg_win / self.avg_loss

    @property
    def profitable_days_rate(self) -> Optional[float]:
        if not self.daily_pnl:
            return None
        profitable = sum(1 for v in self.daily_pnl.values() if v > 0)
        return profitable / len(self.daily_pnl)

    @property
    def days_seen(self) -> int:
        return len(self.daily_pnl)


# ── Criteria scoring ──────────────────────────────────────────────────────────

def score_bot(stats: BotStats) -> Tuple[int, dict, List[str]]:
    """
    Score a bot 0–100 against the 5 criteria.
    Returns (total_score, criterion_scores, verdict_lines).
    """
    criteria: dict = {}

    # 1. Completed trades >= 30  (25pts)
    if stats.total_trades >= MIN_TRADES:
        criteria["trades"] = WEIGHTS["trades"]
        trades_ok = True
    else:
        criteria["trades"] = 0
        trades_ok = False

    # 2. Win rate >= 52%  (20pts)
    wr = stats.win_rate
    if wr is not None and wr >= MIN_WIN_RATE:
        criteria["win_rate"] = WEIGHTS["win_rate"]
        wr_ok = True
    else:
        criteria["win_rate"] = 0
        wr_ok = False

    # 3. Avg win / avg loss >= 1.5  (20pts)
    wl = stats.win_loss_ratio
    if wl is not None and wl >= MIN_WIN_LOSS_R:
        criteria["win_loss"] = WEIGHTS["win_loss"]
        wl_ok = True
    else:
        criteria["win_loss"] = 0
        wl_ok = False

    # 4. Max drawdown < 10%  (20pts)
    dd = stats.max_drawdown
    if dd < MAX_DRAWDOWN:
        criteria["drawdown"] = WEIGHTS["drawdown"]
        dd_ok = True
    else:
        criteria["drawdown"] = 0
        dd_ok = False

    # 5. Profitable days >= 75%  (15pts)
    pdr = stats.profitable_days_rate
    if pdr is not None and pdr >= MIN_PROF_DAYS:
        criteria["prof_days"] = WEIGHTS["prof_days"]
        pd_ok = True
    else:
        criteria["prof_days"] = 0
        pd_ok = False

    total = sum(criteria.values())
    all_met = trades_ok and wr_ok and wl_ok and dd_ok and pd_ok

    # Build verdict lines
    verdict_lines = []
    if all_met and total >= GO_LIVE_MIN_SCORE:
        verdict_lines.append("READY FOR GO-LIVE")
    else:
        missing = []
        if not trades_ok:
            need = MIN_TRADES - stats.total_trades
            missing.append(f"Need {need} more trade{'s' if need != 1 else ''}")
        if not wr_ok:
            if wr is None:
                missing.append("Need trades to establish win rate")
            else:
                missing.append(f"Win rate {wr:.0%} < 52% target")
        if not wl_ok:
            if wl is None:
                missing.append("Need trades to establish W/L ratio")
            else:
                missing.append(f"W/L ratio {wl:.2f} < 1.5 target")
        if not dd_ok:
            missing.append(f"Drawdown {dd:.1%} >= 10% limit")
        if not pd_ok:
            if pdr is None:
                missing.append("Need multiple days to assess profitability")
            else:
                missing.append(f"Prof days {pdr:.0%} < 75% target")
        verdict_lines.append("NOT READY — " + " | ".join(missing))

    return total, criteria, verdict_lines


# ── Report formatting ─────────────────────────────────────────────────────────

WIDTH = 56   # inner width of the box (between ║ and ║)

def _box_line(text: str = "", fill: str = " ") -> str:
    """Pad text to fill the box width."""
    return f"║ {text:<{WIDTH-2}} ║"


def _separator(char: str = "═") -> str:
    return f"╠{char * (WIDTH)}╣"


def _top() -> str:
    return f"╔{'═' * WIDTH}╗"


def _bottom() -> str:
    return f"╚{'═' * WIDTH}╝"


def _criterion_line(label: str, value_str: str, ok: bool, pts: int) -> str:
    tick = "OK" if ok else "XX"
    pts_str = f"{pts:2d}pts"
    # label: 12, value: 14, tick+pts: 10
    inner = f"   {label:<11} {value_str:<16} {tick}  {pts_str}"
    return _box_line(inner)


def format_bot_block(stats: BotStats, score: int, criteria: dict, verdict_lines: List[str]) -> List[str]:
    lines: List[str] = []
    lines.append(_separator())

    # Header: bot name + score
    header = f" {stats.name} ({stats.label})"
    score_str = f"Score: {score:3d}/100"
    pad = WIDTH - 2 - len(header) - len(score_str)
    lines.append(f"║{header}{' ' * max(1, pad)}{score_str} ║")

    # Criterion 1: Trades
    t_val = f"{stats.total_trades}/{MIN_TRADES}"
    lines.append(_criterion_line("Trades:", t_val, criteria["trades"] > 0, criteria["trades"]))

    # Criterion 2: Win rate
    wr = stats.win_rate
    wr_val = f"{wr:.0%}" if wr is not None else "N/A"
    lines.append(_criterion_line("Win rate:", wr_val, criteria["win_rate"] > 0, criteria["win_rate"]))

    # Criterion 3: Win/Loss ratio
    wl = stats.win_loss_ratio
    wl_val = f"{wl:.2f}" if wl is not None else "N/A"
    lines.append(_criterion_line("Win/Loss:", wl_val, criteria["win_loss"] > 0, criteria["win_loss"]))

    # Criterion 4: Max drawdown
    dd_val = f"-{stats.max_drawdown:.2%}"
    lines.append(_criterion_line("Max DD:", dd_val, criteria["drawdown"] > 0, criteria["drawdown"]))

    # Criterion 5: Profitable days
    pdr = stats.profitable_days_rate
    pd_val = f"{pdr:.0%} ({stats.days_seen}d)" if pdr is not None else "N/A"
    lines.append(_criterion_line("Prof days:", pd_val, criteria["prof_days"] > 0, criteria["prof_days"]))

    # Verdict — wrap long lines so they fit inside the box
    verdict_prefix = "   Verdict: "
    indent = "             "
    for vl in verdict_lines:
        full_text = verdict_prefix + vl
        # Split on " | " delimiters, then wrap each segment onto its own line
        segments = [s.strip() for s in full_text.split(" | ")]
        first = True
        for seg in segments:
            if first:
                lines.append(_box_line(seg))
                first = False
            else:
                lines.append(_box_line(indent + seg))

    return lines


def estimate_timeline(avg_score: float) -> str:
    """Rough estimate of weeks remaining to go-live based on current avg score."""
    if avg_score >= GO_LIVE_MIN_SCORE:
        return "All systems ready — initiate go-live review"
    # Very rough: assume linear progress; need to reach 80
    # If avg is near 0, assume 6+ weeks; if 50+, assume 2 weeks
    gap = GO_LIVE_MIN_SCORE - avg_score
    if gap >= 70:
        return "Need ~6+ weeks of active trading"
    elif gap >= 50:
        return "Need ~4 weeks of active trading"
    elif gap >= 30:
        return "Need ~2 weeks of active trading"
    elif gap >= 15:
        return "Need ~1 week of active trading"
    else:
        return "Close — check individual criteria"


def build_report(
    alpaca_stats: BotStats,
    sfm_stats: BotStats,
    enzo_stats: BotStats,
) -> str:
    now_utc = datetime.now(timezone.utc)
    ts_str  = now_utc.strftime("%Y-%m-%d %H:%M UTC")

    alpaca_score, alpaca_criteria, alpaca_verdict = score_bot(alpaca_stats)
    sfm_score,    sfm_criteria,    sfm_verdict    = score_bot(sfm_stats)
    enzo_score,   enzo_criteria,   enzo_verdict   = score_bot(enzo_stats)

    avg_score = (alpaca_score + sfm_score + enzo_score) / 3

    all_ready = (
        alpaca_score >= GO_LIVE_MIN_SCORE and "READY FOR GO-LIVE" in alpaca_verdict[0]
        and sfm_score >= GO_LIVE_MIN_SCORE and "READY FOR GO-LIVE" in sfm_verdict[0]
        and enzo_score >= GO_LIVE_MIN_SCORE and "READY FOR GO-LIVE" in enzo_verdict[0]
    )

    lines: List[str] = []
    lines.append(_top())

    # Title
    title = "GO-LIVE READINESS REPORT"
    lines.append(_box_line(f"{title:^{WIDTH-2}}"))
    lines.append(_box_line(f"{ts_str:^{WIDTH-2}}"))

    # Bot blocks
    lines += format_bot_block(alpaca_stats, alpaca_score, alpaca_criteria, alpaca_verdict)
    lines += format_bot_block(sfm_stats,    sfm_score,    sfm_criteria,    sfm_verdict)
    lines += format_bot_block(enzo_stats,   enzo_score,   enzo_criteria,   enzo_verdict)

    # Overall footer
    lines.append(_separator())
    if all_ready:
        overall_str = f"OVERALL: *** GO-LIVE READY *** (avg {avg_score:.0f}/100)"
    else:
        overall_str = f"OVERALL: NOT READY (avg {avg_score:.0f}/100)"
    lines.append(_box_line(overall_str))
    lines.append(_box_line(f"Estimated ready: {estimate_timeline(avg_score)}"))

    if all_ready:
        lines.append(_box_line())
        lines.append(_box_line("!! GOLIVE_READY.txt written — review before live trading !!"))

    lines.append(_bottom())

    return "\n".join(lines)


# ── GOLIVE_READY flag ─────────────────────────────────────────────────────────

def check_and_write_golive_flag(alpaca_score: int, sfm_score: int, enzo_score: int,
                                 alpaca_verdict: List[str], sfm_verdict: List[str],
                                 enzo_verdict: List[str]) -> bool:
    """If all 3 bots score >= 80 and all criteria met, write GOLIVE_READY.txt."""
    all_ready = (
        alpaca_score >= GO_LIVE_MIN_SCORE and "READY FOR GO-LIVE" in alpaca_verdict[0]
        and sfm_score  >= GO_LIVE_MIN_SCORE and "READY FOR GO-LIVE" in sfm_verdict[0]
        and enzo_score >= GO_LIVE_MIN_SCORE and "READY FOR GO-LIVE" in enzo_verdict[0]
    )
    if not all_ready:
        return False

    now_utc = datetime.now(timezone.utc).isoformat()
    content = (
        f"GO-LIVE READINESS CONFIRMED\n"
        f"Generated: {now_utc}\n\n"
        f"All 3 bots have passed all 5 go-live criteria and scored >= {GO_LIVE_MIN_SCORE}/100.\n\n"
        f"  ALPACABOT: {alpaca_score}/100\n"
        f"  SFMBOT:    {sfm_score}/100\n"
        f"  ENZOBOT:   {enzo_score}/100\n\n"
        f"ACTION REQUIRED: Human review before enabling live capital deployment.\n"
        f"Delete this file once reviewed, or leave it as a permanent audit record.\n"
    )
    try:
        with open(GOLIVE_FLAG, "w", encoding="utf-8") as f:
            f.write(content)
        log.warning("=" * 70)
        log.warning("!! GO-LIVE CRITERIA MET — ALL 3 BOTS SCORE >= %d/100 !!", GO_LIVE_MIN_SCORE)
        log.warning("!! GOLIVE_READY.txt written to %s !!", GOLIVE_FLAG)
        log.warning("=" * 70)
    except Exception as exc:
        log.error("Failed to write GOLIVE_READY.txt: %s", exc)

    return True


# ── Main builder ──────────────────────────────────────────────────────────────

def build_bot_stats_alpaca(exec_entries: List[dict]) -> BotStats:
    """
    Blend alpaca_state.json (trade counts) with execution log (PnL breakdown).
    The state JSON tracks total_trades/winning_trades but doesn't store per-trade
    PnL history, so we prefer exec log for win_pnl/loss_pnl/daily_pnl/drawdown.
    If exec log has no alpaca entries, fall back to state-only data.
    """
    state = load_alpaca_state()
    exec_stats = compute_exec_stats(exec_entries, "alpacabot")

    # Prefer exec log trade counts if populated, otherwise state JSON
    if exec_stats["total_trades"] > 0:
        total    = exec_stats["total_trades"]
        wins     = exec_stats["winning_trades"]
        losses   = exec_stats["losing_trades"]
        win_pnl  = exec_stats["win_pnl"]
        loss_pnl = exec_stats["loss_pnl"]
        daily    = exec_stats["daily_pnl"]
        max_dd   = exec_stats["max_drawdown"]
    else:
        total    = state["total_trades"]
        wins     = state["winning_trades"]
        losses   = state["losing_trades"]
        win_pnl  = []
        loss_pnl = []
        daily    = {}
        # No position equity history in state — drawdown is 0 (paper, no peak data)
        max_dd   = 0.0

    return BotStats(
        name="ALPACABOT", label="Stocks",
        total_trades=total, winning_trades=wins, losing_trades=losses,
        win_pnl=win_pnl, loss_pnl=loss_pnl,
        daily_pnl=daily, max_drawdown=max_dd,
    )


def build_bot_stats_sfm(exec_entries: List[dict]) -> BotStats:
    state = load_sfm_state()
    exec_stats = compute_exec_stats(exec_entries, "sfmbot")

    if exec_stats["total_trades"] > 0:
        total    = exec_stats["total_trades"]
        wins     = exec_stats["winning_trades"]
        losses   = exec_stats["losing_trades"]
        win_pnl  = exec_stats["win_pnl"]
        loss_pnl = exec_stats["loss_pnl"]
        daily    = exec_stats["daily_pnl"]
        max_dd   = exec_stats["max_drawdown"]
    else:
        total    = state["total_trades"]
        wins     = state["winning_trades"]
        losses   = state["losing_trades"]
        win_pnl  = []
        loss_pnl = []
        daily    = {}
        max_dd   = 0.0

    return BotStats(
        name="SFMBOT", label="Solana",
        total_trades=total, winning_trades=wins, losing_trades=losses,
        win_pnl=win_pnl, loss_pnl=loss_pnl,
        daily_pnl=daily, max_drawdown=max_dd,
    )


def build_bot_stats_enzo(exec_entries: List[dict]) -> BotStats:
    """
    Enzobot has its own rich daily_report.json so we use it directly for
    daily P&L, profitable-days, drawdown.  Execution log supplements
    per-trade PnL breakdown if available.
    """
    enzo_state = load_enzo_state()
    enzo_daily = load_enzo_daily()
    exec_stats = compute_exec_stats(exec_entries, "enzobot")

    # Build daily_pnl from enzobot's own daily_report
    daily_pnl: Dict[str, float] = {d: v["net_pnl_usd"] for d, v in enzo_daily.items()}

    # Total trades from daily_report (most accurate source for enzobot)
    total_from_daily = sum(v["trades"] for v in enzo_daily.values())
    wins_from_daily  = sum(v["wins"]   for v in enzo_daily.values())
    losses_from_daily = sum(v["losses"] for v in enzo_daily.values())

    # If exec log has entries, use those for per-trade PnL breakdown; else daily aggregate
    if exec_stats["total_trades"] > 0:
        total    = exec_stats["total_trades"]
        wins     = exec_stats["winning_trades"]
        losses   = exec_stats["losing_trades"]
        win_pnl  = exec_stats["win_pnl"]
        loss_pnl = exec_stats["loss_pnl"]
        max_dd   = exec_stats["max_drawdown"]
    else:
        total    = total_from_daily
        wins     = wins_from_daily
        losses   = losses_from_daily
        win_pnl  = []
        loss_pnl = []
        # Derive drawdown from enzobot's daily_report (net equity, not cash-only)
        # cash-only vs peak overstates DD because open positions have value
        # Use daily_report net_pnl to estimate real equity trend instead
        try:
            dr_path = os.path.join(r"C:\Projects\enzobot", "data", "daily_report.json")
            with open(dr_path, encoding="utf-8") as _f:
                dr = json.load(_f)
            running = enzo_state.get("equity_peak", 4000.0)
            worst = running
            for _day in sorted(dr.keys()):
                running += dr[_day].get("net_pnl_usd", 0.0)
                if running < worst:
                    worst = running
            peak = enzo_state.get("equity_peak", 4000.0)
            max_dd = max(0.0, (peak - worst) / peak) if peak > 0 else 0.0
        except Exception:
            peak   = enzo_state["equity_peak"]
            cash   = enzo_state["cash"]
            max_dd = max(0.0, (peak - cash) / peak) if peak > 0 else 0.0

    return BotStats(
        name="ENZOBOT", label="Kraken",
        total_trades=total, winning_trades=wins, losing_trades=losses,
        win_pnl=win_pnl, loss_pnl=loss_pnl,
        daily_pnl=daily_pnl, max_drawdown=max_dd,
    )


# ── Public API (used by morning brief) ───────────────────────────────────────

def generate_golive_scorecard() -> str:
    """
    Build and return the full go-live scorecard as a formatted string.
    Also handles side-effects: writes golive_report.txt and GOLIVE_READY.txt.
    """
    exec_entries = load_execution_log()

    alpaca_stats = build_bot_stats_alpaca(exec_entries)
    sfm_stats    = build_bot_stats_sfm(exec_entries)
    enzo_stats   = build_bot_stats_enzo(exec_entries)

    report = build_report(alpaca_stats, sfm_stats, enzo_stats)

    # Side-effects
    alpaca_score, _, alpaca_verdict = score_bot(alpaca_stats)
    sfm_score,    _, sfm_verdict    = score_bot(sfm_stats)
    enzo_score,   _, enzo_verdict   = score_bot(enzo_stats)

    check_and_write_golive_flag(
        alpaca_score, sfm_score, enzo_score,
        alpaca_verdict, sfm_verdict, enzo_verdict,
    )

    # Write report file
    try:
        with open(REPORT_FILE, "w", encoding="utf-8") as f:
            f.write(report + "\n")
        log.info("[GOLIVE] Report written to %s", REPORT_FILE)
    except Exception as exc:
        log.error("[GOLIVE] Failed to write report: %s", exc)

    return report


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    report = generate_golive_scorecard()
    # On Windows the default console encoding may not support box-drawing chars.
    # Reconfigure stdout to UTF-8 so the report always prints correctly.
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    try:
        print(report)
    except UnicodeEncodeError:
        # Fallback: replace unencodable chars with ASCII approximations
        safe = (
            report
            .replace("╔", "+").replace("╗", "+").replace("╚", "+").replace("╝", "+")
            .replace("╠", "+").replace("╣", "+").replace("║", "|")
            .replace("═", "=")
        )
        print(safe)


if __name__ == "__main__":
    main()

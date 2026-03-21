"""
supervisor_unified.py — Reads all 3 bot state files and computes unified portfolio view.
Called every brain cycle to give the master brain full cross-bot visibility.

State file paths (from supervisor_settings.py):
  enzobot:   C:\\Projects\\enzobot\\state.json  + brain_state.json
  sfmbot:    C:\\Projects\\sfmbot\\sfm_state.json
  alpacabot: C:\\Projects\\alpacabot\\alpaca_state.json
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger("supervisor_unified")

# ── State file paths (mirrors supervisor_settings.py) ────────────────
_BASE_ENZOBOT  = r"C:\Projects\enzobot"
_BASE_SFM      = r"C:\Projects\sfmbot"
_BASE_ALPACA   = r"C:\Projects\alpacabot"

ENZOBOT_STATE_PATH  = os.environ.get("ENZOBOT_STATE",  os.path.join(_BASE_ENZOBOT, "state.json"))
ENZOBOT_BRAIN_PATH  = os.environ.get("ENZOBOT_BRAIN",  os.path.join(_BASE_ENZOBOT, "brain_state.json"))
SFMBOT_STATE_PATH   = os.environ.get("SFMBOT_STATE",   os.path.join(_BASE_SFM,     "sfm_state.json"))
ALPACA_STATE_PATH   = os.environ.get("ALPACA_STATE",   os.path.join(_BASE_ALPACA,  "alpaca_state.json"))

# Capital baselines (mirrors supervisor_settings.py defaults)
_ENZOBOT_BASELINE = float(os.environ.get("ENZOBOT_BASELINE", "4000.00"))
_SFMBOT_BASELINE  = float(os.environ.get("SFMBOT_BASELINE",  "2350.87"))
_ALPACA_BASELINE  = float(os.environ.get("ALPACA_BASELINE",  "500.00"))


# ── Data classes ─────────────────────────────────────────────────────

@dataclass
class BotSnapshot:
    name: str
    equity: float
    cash: float
    deployed_usd: float
    dd_pct: float
    open_positions: list          # list of {symbol, entry_price, current_value, pnl_pct}
    realized_pnl: float
    total_trades: int
    win_rate: float
    state_age_sec: float          # how old the state file is in seconds
    ok: bool = True               # False if state file missing / unreadable


@dataclass
class UnifiedPortfolio:
    total_equity: float
    total_cash: float
    total_deployed: float
    total_dd_pct: float
    crypto_exposure_usd: float    # sfmbot + enzobot deployed capital
    equity_exposure_usd: float    # alpacabot deployed capital
    all_positions: list           # all open positions across all bots
    bots: dict                    # name -> BotSnapshot
    generated_at: str


# ── Low-level JSON loader ─────────────────────────────────────────────

def _load_json(path: str) -> tuple[dict, float]:
    """
    Returns (parsed_dict, age_seconds).
    age_seconds is how old the file is. Returns ({}, -1) on any error.
    """
    if not os.path.exists(path):
        return {}, -1.0
    try:
        age = time.time() - os.path.getmtime(path)
        with open(path, encoding="utf-8") as f:
            return json.load(f), age
    except Exception as exc:
        log.warning("Could not read %s: %s", path, exc)
        return {}, -1.0


# ── Per-bot readers ───────────────────────────────────────────────────

def _read_enzobot() -> BotSnapshot:
    """
    enzobot state.json structure:
      cash, realized_pnl, equity_peak, positions: {pair: {qty, avg_price, ...}}, meta

    brain_state.json structure (written by enzobot supervisor_brain.py):
      active_mode, cycle, total_trades, winning_trades, ...
    """
    state, age = _load_json(ENZOBOT_STATE_PATH)
    brain, _   = _load_json(ENZOBOT_BRAIN_PATH)

    if not state and age < 0:
        return BotSnapshot(
            name="enzobot", equity=_ENZOBOT_BASELINE, cash=_ENZOBOT_BASELINE,
            deployed_usd=0.0, dd_pct=0.0, open_positions=[],
            realized_pnl=0.0, total_trades=0, win_rate=0.0,
            state_age_sec=-1.0, ok=False,
        )

    cash     = float(state.get("cash", _ENZOBOT_BASELINE))
    rpnl     = float(state.get("realized_pnl", 0.0))
    eq_peak  = float(state.get("equity_peak", _ENZOBOT_BASELINE))
    raw_pos  = state.get("positions", {}) or {}

    # Build position list and deployed value
    positions_out = []
    deployed = 0.0
    if isinstance(raw_pos, dict):
        for sym, p in raw_pos.items():
            if not isinstance(p, dict):
                continue
            qty       = float(p.get("qty", 0.0))
            avg_price = float(p.get("avg_price", 0.0))
            if qty <= 0:
                continue
            cost_usd   = qty * avg_price
            # Use last_price if available, otherwise mark at cost (no unrealized calc)
            # Guard: last_price=0.0 is falsy — falls back to avg_price (matches supervisor_portfolio.py)
            last_price = float(p.get("last_price") or avg_price)
            curr_val   = qty * last_price
            pnl_pct    = ((last_price - avg_price) / avg_price * 100) if avg_price > 0 else 0.0
            deployed  += cost_usd
            positions_out.append({
                "symbol":        sym,
                "entry_price":   avg_price,
                "current_value": curr_val,
                "pnl_pct":       pnl_pct,
                "bot":           "enzobot",
            })

    equity = cash + deployed if deployed > 0 else cash
    if equity <= 0 or equity == _ENZOBOT_BASELINE:
        equity = _ENZOBOT_BASELINE + rpnl

    dd_pct = ((equity - eq_peak) / eq_peak * 100) if eq_peak > 0 else 0.0
    # Prefer drawdown_pct written directly by bot
    dd_pct = float(state.get("drawdown_pct", dd_pct))

    # Trade stats — brain_state.json does not track these fields; read from state only.
    # win_rate = -1.0 signals "not tracked" (displayed as N/A in prompt).
    total_trades   = int(state.get("total_trades",   0))
    winning_trades = int(state.get("winning_trades", 0))
    win_rate       = (winning_trades / total_trades * 100) if total_trades > 0 else -1.0

    return BotSnapshot(
        name="enzobot",
        equity=equity,
        cash=cash,
        deployed_usd=deployed,
        dd_pct=dd_pct,
        open_positions=positions_out,
        realized_pnl=rpnl,
        total_trades=total_trades,
        win_rate=win_rate,
        state_age_sec=age,
    )


def _read_sfmbot() -> BotSnapshot:
    """
    sfm_state.json structure:
      usdc_balance, realized_pnl_usd, total_trades, winning_trades,
      losing_trades, cycle, last_buy_candle_idx,
      position: {entry_price, sfm_qty, cost_usd, entry_ts, scaled_out} | null
    """
    state, age = _load_json(SFMBOT_STATE_PATH)

    if not state and age < 0:
        return BotSnapshot(
            name="sfmbot", equity=_SFMBOT_BASELINE, cash=_SFMBOT_BASELINE,
            deployed_usd=0.0, dd_pct=0.0, open_positions=[],
            realized_pnl=0.0, total_trades=0, win_rate=0.0,
            state_age_sec=-1.0, ok=False,
        )

    usdc     = float(state.get("usdc_balance", _SFMBOT_BASELINE))
    rpnl     = float(state.get("realized_pnl_usd", 0.0))
    pos      = state.get("position")

    positions_out = []
    deployed = 0.0

    if pos and isinstance(pos, dict):
        cost_usd    = float(pos.get("cost_usd",    0.0))
        entry_price = float(pos.get("entry_price", 0.0))
        sfm_qty     = float(pos.get("sfm_qty",     0.0))
        deployed    = cost_usd
        # SFM current price not in state — mark at cost (no unrealized P&L available)
        positions_out.append({
            "symbol":        "SFM",
            "entry_price":   entry_price,
            "current_value": cost_usd,   # marked at cost; no live price in state
            "pnl_pct":       0.0,
            "bot":           "sfmbot",
        })

    equity = usdc + deployed
    # Drawdown proxy: equity vs baseline (no equity_peak in sfm_state.json).
    dd_pct = min(0.0, (equity - _SFMBOT_BASELINE) / _SFMBOT_BASELINE * 100) if _SFMBOT_BASELINE > 0 else 0.0

    total_trades   = int(state.get("total_trades",   0))
    winning_trades = int(state.get("winning_trades", 0))
    win_rate       = (winning_trades / total_trades * 100) if total_trades > 0 else -1.0

    return BotSnapshot(
        name="sfmbot",
        equity=equity,
        cash=usdc,
        deployed_usd=deployed,
        dd_pct=dd_pct,
        open_positions=positions_out,
        realized_pnl=rpnl,
        total_trades=total_trades,
        win_rate=win_rate,
        state_age_sec=age,
    )


def _read_alpacabot() -> BotSnapshot:
    """
    alpaca_state.json structure:
      realized_pnl_usd, total_trades, winning_trades, losing_trades,
      cycle, positions: {symbol: {symbol, entry_price, entry_ts, usd_invested}},
      stop_loss_strikes, blocked_until
    """
    state, age = _load_json(ALPACA_STATE_PATH)

    if not state and age < 0:
        return BotSnapshot(
            name="alpacabot", equity=_ALPACA_BASELINE, cash=_ALPACA_BASELINE,
            deployed_usd=0.0, dd_pct=0.0, open_positions=[],
            realized_pnl=0.0, total_trades=0, win_rate=0.0,
            state_age_sec=-1.0, ok=False,
        )

    rpnl     = float(state.get("realized_pnl_usd", 0.0))
    raw_pos  = state.get("positions", {}) or {}

    positions_out = []
    deployed = 0.0

    if isinstance(raw_pos, dict):
        for sym, p in raw_pos.items():
            if not isinstance(p, dict):
                continue
            usd_invested = float(p.get("usd_invested", 0.0))
            entry_price  = float(p.get("entry_price",  0.0))
            if usd_invested <= 0:
                continue
            deployed += usd_invested
            # No current price in local state — mark at cost
            positions_out.append({
                "symbol":        sym,
                "entry_price":   entry_price,
                "current_value": usd_invested,  # marked at cost (live price from Alpaca API)
                "pnl_pct":       0.0,
                "bot":           "alpacabot",
            })

    # Equity: baseline + realized PnL (live equity from Alpaca API tracked by portfolio module)
    equity = _ALPACA_BASELINE + rpnl
    # Drawdown proxy: equity vs baseline (no equity_peak in alpaca_state.json).
    dd_pct = min(0.0, (equity - _ALPACA_BASELINE) / _ALPACA_BASELINE * 100) if _ALPACA_BASELINE > 0 else 0.0

    total_trades   = int(state.get("total_trades",   0))
    winning_trades = int(state.get("winning_trades", 0))
    win_rate       = (winning_trades / total_trades * 100) if total_trades > 0 else -1.0

    return BotSnapshot(
        name="alpacabot",
        equity=equity,
        cash=max(equity - deployed, 0.0),
        deployed_usd=deployed,
        dd_pct=dd_pct,
        open_positions=positions_out,
        realized_pnl=rpnl,
        total_trades=total_trades,
        win_rate=win_rate,
        state_age_sec=age,
    )


# ── Main unified reader ───────────────────────────────────────────────

def read_unified_portfolio() -> UnifiedPortfolio:
    """Read all 3 bot states and return a unified view. Never raises."""
    enzo  = _read_enzobot()
    sfm   = _read_sfmbot()
    alpaca = _read_alpacabot()

    bots = {
        "enzobot":   enzo,
        "sfmbot":    sfm,
        "alpacabot": alpaca,
    }

    total_equity   = enzo.equity   + sfm.equity   + alpaca.equity
    total_cash     = enzo.cash     + sfm.cash     + alpaca.cash
    total_deployed = enzo.deployed_usd + sfm.deployed_usd + alpaca.deployed_usd

    # Crypto = enzobot (Kraken) + sfmbot (Solana) deployed
    crypto_exposure = enzo.deployed_usd + sfm.deployed_usd
    # Equity (stocks) = alpacabot deployed
    equity_exposure = alpaca.deployed_usd

    # Weighted drawdown across all three bots (baseline-weighted).
    # sfm/alpaca use a baseline-anchored proxy (no equity_peak in their state files).
    total_baseline = _ENZOBOT_BASELINE + _SFMBOT_BASELINE + _ALPACA_BASELINE
    total_dd_pct   = (
        enzo.dd_pct   * _ENZOBOT_BASELINE +
        sfm.dd_pct    * _SFMBOT_BASELINE  +
        alpaca.dd_pct * _ALPACA_BASELINE
    ) / total_baseline if total_baseline > 0 else 0.0

    all_positions = enzo.open_positions + sfm.open_positions + alpaca.open_positions

    return UnifiedPortfolio(
        total_equity=total_equity,
        total_cash=total_cash,
        total_deployed=total_deployed,
        total_dd_pct=total_dd_pct,
        crypto_exposure_usd=crypto_exposure,
        equity_exposure_usd=equity_exposure,
        all_positions=all_positions,
        bots=bots,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )


# ── Concentration warning logic ───────────────────────────────────────

def _concentration_warnings(u: UnifiedPortfolio) -> list[str]:
    """
    Return a list of human-readable warnings if any asset class
    exceeds 70% of total deployed capital.
    """
    warnings = []
    if u.total_deployed <= 0:
        return warnings

    crypto_pct  = u.crypto_exposure_usd / u.total_deployed * 100
    equity_pct  = u.equity_exposure_usd / u.total_deployed * 100
    THRESHOLD   = 70.0

    if crypto_pct > THRESHOLD:
        warnings.append(
            f"CONCENTRATION: crypto {crypto_pct:.0f}% of deployed "
            f"(${u.crypto_exposure_usd:,.0f}) — threshold {THRESHOLD:.0f}%"
        )
    if equity_pct > THRESHOLD:
        warnings.append(
            f"CONCENTRATION: equities {equity_pct:.0f}% of deployed "
            f"(${u.equity_exposure_usd:,.0f}) — threshold {THRESHOLD:.0f}%"
        )

    # Per-bot concentration check
    for name, snap in u.bots.items():
        if u.total_deployed > 0:
            bot_pct = snap.deployed_usd / u.total_deployed * 100
            if bot_pct > THRESHOLD:
                warnings.append(
                    f"CONCENTRATION: {name} holds {bot_pct:.0f}% of deployed "
                    f"(${snap.deployed_usd:,.0f})"
                )

    # Stale state warnings (> 20 min)
    for name, snap in u.bots.items():
        if snap.state_age_sec < 0:
            warnings.append(f"OFFLINE: {name} state file missing — bot may be down")
        elif snap.state_age_sec > 1200:
            minutes = snap.state_age_sec / 60
            warnings.append(f"STALE: {name} state is {minutes:.0f}m old — bot may be hung")

    return warnings


# ── Prompt formatter ──────────────────────────────────────────────────

def _fmt_positions(positions: list, max_show: int = 6) -> str:
    if not positions:
        return "none"
    shown = positions[:max_show]
    parts = []
    for p in shown:
        sym  = p.get("symbol", "?")
        val  = p.get("current_value", 0.0)
        ppct = p.get("pnl_pct", 0.0)
        parts.append(f"{sym}(${val:,.0f}/{ppct:+.1f}%)")
    suffix = f" +{len(positions) - max_show} more" if len(positions) > max_show else ""
    return ", ".join(parts) + suffix


def _fmt_age(age_sec: float) -> str:
    if age_sec < 0:
        return "MISSING"
    if age_sec < 60:
        return f"{age_sec:.0f}s ago"
    return f"{age_sec / 60:.0f}m ago"


def format_unified_for_prompt(u: UnifiedPortfolio) -> str:
    """Format unified portfolio for injection into the Claude brain prompt."""
    deployed_pct = (u.total_deployed / u.total_equity * 100) if u.total_equity > 0 else 0.0
    crypto_pct   = (u.crypto_exposure_usd / u.total_equity * 100) if u.total_equity > 0 else 0.0
    equity_pct   = (u.equity_exposure_usd / u.total_equity * 100) if u.total_equity > 0 else 0.0

    warnings = _concentration_warnings(u)
    warn_text = "\n".join(f"  !! {w}" for w in warnings) if warnings else "  none"

    e = u.bots.get("enzobot")
    s = u.bots.get("sfmbot")
    a = u.bots.get("alpacabot")

    def bot_line(snap: Optional[BotSnapshot], label: str) -> str:
        if snap is None:
            return f"  {label}: UNAVAILABLE"
        status  = "" if snap.ok else " [OFFLINE]"
        age     = _fmt_age(snap.state_age_sec)
        pos_s   = _fmt_positions(snap.open_positions)
        win_str = f"{snap.win_rate:.0f}%" if snap.win_rate >= 0 else "N/A"
        return (
            f"  {label}:{status}\n"
            f"    eq=${snap.equity:,.2f}  cash=${snap.cash:,.2f}  deployed=${snap.deployed_usd:,.2f}"
            f"  dd={snap.dd_pct:.1f}%  state={age}\n"
            f"    trades={snap.total_trades}  winrate={win_str}"
            f"  realized_pnl=${snap.realized_pnl:+,.2f}\n"
            f"    positions=[{pos_s}]"
        )

    lines = [
        "═══════════════════════════════════════════════════",
        f"UNIFIED PORTFOLIO (all 3 bots)  [{u.generated_at}]",
        "═══════════════════════════════════════════════════",
        f"Total equity:   ${u.total_equity:,.2f}",
        f"Deployed:       ${u.total_deployed:,.2f} ({deployed_pct:.1f}% of equity)",
        f"Cash:           ${u.total_cash:,.2f}",
        f"DD from peak:   {u.total_dd_pct:.2f}%",
        f"",
        f"Crypto exposure (enzobot+sfmbot): ${u.crypto_exposure_usd:,.2f} ({crypto_pct:.1f}% of equity)",
        f"Equity exposure (alpacabot):      ${u.equity_exposure_usd:,.2f} ({equity_pct:.1f}% of equity)",
        f"",
        "Bot breakdown:",
        bot_line(e, "enzobot  "),
        bot_line(s, "sfmbot   "),
        bot_line(a, "alpacabot"),
        f"",
        "Cross-bot risk:",
        warn_text,
        "═══════════════════════════════════════════════════",
    ]
    return "\n".join(lines)

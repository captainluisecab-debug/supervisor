"""
supervisor_correlation.py — Cross-asset correlation collapse detector.

The core insight: when BTC and SPY start moving together (correlation > 0.7),
the three-sleeve portfolio loses its diversification benefit. Everything drops
at once. This happened in March 2020, May 2022, October 2023.

Detecting it early and forcing defensive posture across all bots is one of
the most valuable risk management signals available.

Method:
  - Fetch last 20 days of BTC daily prices (CoinGecko)
  - Fetch last 20 days of SPY daily closes (Alpaca)
  - Compute Pearson correlation of daily returns
  - Classify: LOW / ELEVATED / COLLAPSE

Correlation thresholds:
  < 0.35   LOW        — diversification intact, normal operation
  0.35–0.6 ELEVATED   — watch closely, slight caution
  > 0.60   COLLAPSE   — diversification gone, force DEFENSE/SCOUT

When COLLAPSE detected:
  - Injected into Claude's prompt as a critical alert
  - Claude is instructed to reduce exposure across ALL sleeves
  - size_mult cap applied automatically (max 0.6x during collapse)
"""
from __future__ import annotations

import logging
import math
import os
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import requests

log = logging.getLogger("supervisor_correlation")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

COINGECKO_MARKET_CHART = (
    "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
    "?vs_currency=usd&days=25&interval=daily"
)

# Thresholds
COLLAPSE_THRESHOLD  = 0.60
ELEVATED_THRESHOLD  = 0.35
COLLAPSE_SIZE_CAP   = 0.6    # max size_mult when COLLAPSE detected
MIN_POINTS          = 10     # minimum data points for reliable correlation


@dataclass
class CorrelationSnapshot:
    correlation: float          # Pearson r, -1.0 to +1.0
    classification: str         # LOW | ELEVATED | COLLAPSE
    btc_points: int             # data points used
    spy_points: int
    btc_returns: List[float]
    spy_returns: List[float]
    size_mult_cap: float        # max allowed size_mult right now
    notes: List[str] = field(default_factory=list)
    warning: bool = False


def _pearson(x: List[float], y: List[float]) -> float:
    """Pearson correlation coefficient."""
    n = len(x)
    if n < 3:
        return 0.0
    try:
        mean_x = statistics.mean(x)
        mean_y = statistics.mean(y)
        num    = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
        den_x  = math.sqrt(sum((v - mean_x) ** 2 for v in x))
        den_y  = math.sqrt(sum((v - mean_y) ** 2 for v in y))
        if den_x == 0 or den_y == 0:
            return 0.0
        return round(num / (den_x * den_y), 4)
    except Exception:
        return 0.0


def _daily_returns(prices: List[float]) -> List[float]:
    """Convert price series to daily % returns."""
    if len(prices) < 2:
        return []
    return [(prices[i] - prices[i-1]) / prices[i-1] * 100 for i in range(1, len(prices))]


def _get_btc_daily_prices(days: int = 25) -> List[float]:
    """Fetch BTC daily closing prices from CoinGecko."""
    try:
        resp = requests.get(COINGECKO_MARKET_CHART, timeout=12)
        resp.raise_for_status()
        prices_raw = resp.json().get("prices", [])
        # Each entry: [timestamp_ms, price]
        prices = [float(p[1]) for p in prices_raw]
        return prices[-days:] if len(prices) > days else prices
    except Exception as exc:
        log.warning("BTC price fetch failed (correlation): %s", exc)
        return []


def _get_spy_daily_prices(days: int = 25) -> List[float]:
    """Fetch SPY daily closing prices from Alpaca."""
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        from supervisor_settings import ALPACA_API_KEY, ALPACA_SECRET_KEY

        client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
        end    = datetime.now(timezone.utc)
        start  = end - timedelta(days=days + 10)
        req    = StockBarsRequest(
            symbol_or_symbols="SPY",
            timeframe=TimeFrame.Day,
            start=start, end=end,
            feed="iex",
        )
        resp = client.get_stock_bars(req)
        bars = resp.data.get("SPY", [])
        closes = [float(b.close) for b in bars]
        return closes[-days:] if len(closes) > days else closes
    except Exception as exc:
        log.warning("SPY price fetch failed (correlation): %s", exc)
        return []


def _classify(corr: float) -> tuple[str, float, bool]:
    """
    Returns (classification, size_mult_cap, warning).
    """
    if corr >= COLLAPSE_THRESHOLD:
        return "COLLAPSE", COLLAPSE_SIZE_CAP, True
    if corr >= ELEVATED_THRESHOLD:
        return "ELEVATED", 1.0, False
    return "LOW", 1.0, False


def check_correlation() -> CorrelationSnapshot:
    """
    Compute BTC/SPY rolling correlation and classify risk.
    Returns CorrelationSnapshot.
    """
    btc_prices = _get_btc_daily_prices(25)
    spy_prices = _get_spy_daily_prices(25)

    btc_ret = _daily_returns(btc_prices)
    spy_ret = _daily_returns(spy_prices)

    notes = []

    # Align series lengths
    min_len = min(len(btc_ret), len(spy_ret))
    if min_len < MIN_POINTS:
        log.warning("Correlation: insufficient data (btc=%d spy=%d)", len(btc_ret), len(spy_ret))
        notes.append(
            f"Insufficient data for correlation (btc={len(btc_ret)} spy={len(spy_ret)} days)"
        )
        return CorrelationSnapshot(
            correlation=0.0,
            classification="LOW",
            btc_points=len(btc_ret),
            spy_points=len(spy_ret),
            btc_returns=btc_ret,
            spy_returns=spy_ret,
            size_mult_cap=1.0,
            notes=notes,
            warning=False,
        )

    # Use most recent min_len points
    btc_aligned = btc_ret[-min_len:]
    spy_aligned = spy_ret[-min_len:]

    corr = _pearson(btc_aligned, spy_aligned)
    classification, size_cap, warning = _classify(corr)

    notes.append(
        f"BTC/SPY 20-day correlation: {corr:+.3f} -> {classification} "
        f"(using {min_len} data points)"
    )

    if classification == "COLLAPSE":
        notes.append(
            f"CORRELATION COLLAPSE — BTC and SPY moving together ({corr:.2f}). "
            f"Diversification benefit is GONE. Capping size_mult at {size_cap}x across all sleeves."
        )
    elif classification == "ELEVATED":
        notes.append(
            f"Correlation elevated ({corr:.2f}) — monitor closely. "
            f"Diversification weakening."
        )
    else:
        notes.append(
            f"Correlation low ({corr:.2f}) — portfolio diversification intact."
        )

    # Rolling context: last 5-day correlation vs 20-day
    if min_len >= 10:
        recent_corr = _pearson(btc_aligned[-5:], spy_aligned[-5:])
        trend = "rising" if recent_corr > corr else "falling"
        notes.append(
            f"5-day correlation: {recent_corr:+.3f} ({trend} vs 20-day {corr:+.3f})"
        )

    log.info(
        "[CORRELATION] BTC/SPY r=%.3f | %s | size_cap=%.1fx | n=%d",
        corr, classification, size_cap, min_len,
    )

    return CorrelationSnapshot(
        correlation=corr,
        classification=classification,
        btc_points=len(btc_ret),
        spy_points=len(spy_ret),
        btc_returns=btc_aligned,
        spy_returns=spy_aligned,
        size_mult_cap=size_cap,
        notes=notes,
        warning=warning,
    )


def format_correlation_for_prompt(snap: CorrelationSnapshot) -> str:
    lines = []
    for note in snap.notes:
        lines.append(f"  {note}")
    if snap.warning:
        lines.append(
            f"  ACTION REQUIRED: Apply max size_mult={snap.size_mult_cap}x to ALL sleeves."
        )
    return "\n".join(lines)


def apply_correlation_cap(size_mult: float, snap: CorrelationSnapshot) -> float:
    """Enforce correlation-based size cap. Call before writing command files."""
    return round(min(size_mult, snap.size_mult_cap), 2)

"""
supervisor_regime.py — Global market regime classification.

Uses free public data:
  - BTC 7-day return: CoinGecko API (no key)
  - SPY 10-day realized volatility: Alpaca data API (paper key)

Regime outputs:
  RISK_ON   — BTC trending up, SPY vol low -> full allocation, normal operation
  NEUTRAL   — mixed signals -> moderate caution
  RISK_OFF  — BTC dropping OR SPY vol spiking -> tighten all sleeves

This is the macro context layer. Supervisor recommendations scale with regime.
"""
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from supervisor_settings import (
    ALPACA_API_KEY, ALPACA_SECRET_KEY,
    BTC_TREND_RISK_OFF, BTC_TREND_RISK_ON, SPY_VOL_RISK_OFF,
)

log = logging.getLogger("supervisor_regime")


@dataclass
class RegimeSnapshot:
    regime: str              # RISK_ON | NEUTRAL | RISK_OFF
    btc_7d_pct: float        # BTC 7-day return %
    spy_vol_10d: float       # SPY 10-day realized vol %
    btc_price: float
    spy_price: float
    confidence: float        # 0.0–1.0
    notes: list


def _get_btc_7d() -> tuple[float, float]:
    """Returns (btc_price, 7d_return_pct). Uses CoinGecko markets endpoint."""
    try:
        url = "https://api.coingecko.com/api/v3/coins/markets"
        params = {
            "vs_currency": "usd",
            "ids": "bitcoin",
            "price_change_percentage": "7d",
        }
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        items = resp.json()
        if not items:
            return 0.0, 0.0
        data   = items[0]
        price  = float(data.get("current_price", 0))
        chg_7d = float(data.get("price_change_percentage_7d_in_currency", 0) or 0)
        return price, chg_7d
    except Exception as exc:
        log.warning("BTC fetch failed: %s", exc)
        return 0.0, 0.0


def _get_spy_vol() -> tuple[float, float]:
    """Returns (spy_price, 10d_realized_vol_pct). Uses Alpaca free data."""
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
        end   = datetime.now(timezone.utc)
        start = end - timedelta(days=20)
        req   = StockBarsRequest(symbol_or_symbols="SPY", timeframe=TimeFrame.Day,
                                 start=start, end=end, feed="iex")
        resp  = client.get_stock_bars(req)
        bars  = resp.data.get("SPY", [])

        if len(bars) < 5:
            return 0.0, 0.0

        closes  = [float(b.close) for b in bars[-11:]]
        returns = [(closes[i] - closes[i-1]) / closes[i-1] * 100
                   for i in range(1, len(closes))]
        vol = statistics.stdev(returns) if len(returns) > 1 else 0.0
        return closes[-1], vol
    except Exception as exc:
        log.warning("SPY vol fetch failed: %s", exc)
        return 0.0, 0.0


def classify_regime() -> RegimeSnapshot:
    btc_price, btc_7d = _get_btc_7d()
    spy_price, spy_vol = _get_spy_vol()

    notes   = []
    signals = []   # +1 = risk-on signal, -1 = risk-off signal

    # BTC trend signal
    if btc_7d >= BTC_TREND_RISK_ON:
        signals.append(1)
        notes.append(f"BTC +{btc_7d:.1f}% 7d -> risk-on")
    elif btc_7d <= BTC_TREND_RISK_OFF:
        signals.append(-1)
        notes.append(f"BTC {btc_7d:.1f}% 7d -> risk-off")
    else:
        signals.append(0)
        notes.append(f"BTC {btc_7d:.1f}% 7d -> neutral")

    # SPY volatility signal
    if spy_vol > 0:
        if spy_vol >= SPY_VOL_RISK_OFF:
            signals.append(-1)
            notes.append(f"SPY vol {spy_vol:.2f}% -> elevated -> risk-off")
        elif spy_vol < SPY_VOL_RISK_OFF * 0.6:
            signals.append(1)
            notes.append(f"SPY vol {spy_vol:.2f}% -> calm -> risk-on")
        else:
            signals.append(0)
            notes.append(f"SPY vol {spy_vol:.2f}% -> neutral")
    else:
        signals.append(0)
        notes.append("SPY vol unavailable")

    score = sum(signals)
    confidence = abs(score) / len(signals) if signals else 0.0

    if score >= 1:
        regime = "RISK_ON"
    elif score <= -1:
        regime = "RISK_OFF"
    else:
        regime = "NEUTRAL"

    return RegimeSnapshot(
        regime=regime,
        btc_7d_pct=btc_7d,
        spy_vol_10d=spy_vol,
        btc_price=btc_price,
        spy_price=spy_price,
        confidence=confidence,
        notes=notes,
    )

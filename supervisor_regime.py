"""
supervisor_regime.py — Global market regime classification.

Data sources (all free, no API key except Alpaca which we already have):
  - BTC 7-day return:        CoinGecko API
  - SPY 10-day realized vol: Alpaca data API
  - Global indices:          Yahoo Finance via yfinance
      Asia:   Nikkei, Hang Seng, Shanghai, ASX
      Europe: FTSE, DAX, CAC
      US:     S&P futures, Nasdaq futures, VIX

Regime outputs:
  RISK_ON   -> full allocation, normal operation
  NEUTRAL   -> moderate caution
  RISK_OFF  -> tighten all sleeves

Global markets give the brain a forward-looking view:
  If Asia + Europe are red -> US likely opens weak
  If US futures are up >0.5% pre-market -> expect strong open
  VIX > 25 -> defensive posture regardless of other signals
"""
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import requests

from supervisor_settings import (
    ALPACA_API_KEY, ALPACA_SECRET_KEY,
    BTC_TREND_RISK_OFF, BTC_TREND_RISK_ON, SPY_VOL_RISK_OFF,
)

log = logging.getLogger("supervisor_regime")


@dataclass
class RegimeSnapshot:
    regime: str
    btc_7d_pct: float
    spy_vol_10d: float
    btc_price: float
    spy_price: float
    confidence: float
    notes: List[str]
    # Global market additions
    global_sentiment: str = "UNKNOWN"
    us_open_bias: str     = "NEUTRAL"
    vix: float            = 0.0
    asia_pct: float       = 0.0
    europe_pct: float     = 0.0
    us_futures_pct: float = 0.0
    global_notes: List[str] = field(default_factory=list)


def _get_btc_7d() -> tuple[float, float]:
    try:
        url = "https://api.coingecko.com/api/v3/coins/markets"
        params = {"vs_currency": "usd", "ids": "bitcoin",
                  "price_change_percentage": "7d"}
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        items = resp.json()
        if not items:
            return 0.0, 0.0
        data = items[0]
        return float(data.get("current_price", 0)), float(data.get("price_change_percentage_7d_in_currency", 0) or 0)
    except Exception as exc:
        log.warning("BTC fetch failed: %s", exc)
        return 0.0, 0.0


def _get_spy_vol() -> tuple[float, float]:
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
        returns = [(closes[i] - closes[i-1]) / closes[i-1] * 100 for i in range(1, len(closes))]
        vol = statistics.stdev(returns) if len(returns) > 1 else 0.0
        return closes[-1], vol
    except Exception as exc:
        log.warning("SPY vol fetch failed: %s", exc)
        return 0.0, 0.0


def _get_global_markets() -> dict:
    """
    Fetch global indices via yfinance. Returns dict with region scores and VIX.
    Falls back gracefully if yfinance unavailable.
    """
    result = {
        "asia_pct": 0.0, "europe_pct": 0.0, "us_futures_pct": 0.0,
        "vix": 0.0, "sentiment": "UNKNOWN", "open_bias": "NEUTRAL",
        "notes": [], "ticks": {},
    }
    try:
        import yfinance as yf
    except ImportError:
        result["notes"].append("yfinance not installed — global markets unavailable")
        return result

    TARGETS = {
        "Nikkei":    ("^N225",    "asia"),
        "HangSeng":  ("^HSI",     "asia"),
        "Shanghai":  ("000001.SS","asia"),
        "FTSE":      ("^FTSE",    "europe"),
        "DAX":       ("^GDAXI",   "europe"),
        "CAC40":     ("^FCHI",    "europe"),
        "SP500_Fut": ("ES=F",     "us_fut"),
        "NQ_Fut":    ("NQ=F",     "us_fut"),
        "VIX":       ("^VIX",     "vix"),
    }

    region_vals = {"asia": [], "europe": [], "us_fut": []}
    vix = 0.0

    for name, (ticker, region) in TARGETS.items():
        try:
            t     = yf.Ticker(ticker)
            info  = t.fast_info
            price = float(info.last_price or 0)
            prev  = float(info.previous_close or price)
            chg   = (price - prev) / prev * 100 if prev > 0 else 0.0
            result["ticks"][name] = {"price": price, "chg_pct": chg}
            if region == "vix":
                vix = price
            elif region in region_vals:
                region_vals[region].append(chg)
        except Exception:
            pass

    def avg(lst): return sum(lst) / len(lst) if lst else 0.0

    asia_pct   = avg(region_vals["asia"])
    europe_pct = avg(region_vals["europe"])
    us_fut_pct = avg(region_vals["us_fut"])

    # Composite weighted score
    composite = asia_pct * 0.25 + europe_pct * 0.35 + us_fut_pct * 0.40

    # Open bias from US futures (most direct signal)
    if us_fut_pct >= 0.3:    open_bias = "UP"
    elif us_fut_pct <= -0.3: open_bias = "DOWN"
    elif composite > 0.1:    open_bias = "UP"
    elif composite < -0.1:   open_bias = "DOWN"
    else:                    open_bias = "NEUTRAL"

    # Sentiment
    if composite >= 0.5 and vix < 20:       sentiment = "BULLISH"
    elif composite <= -0.5 or vix > 25:     sentiment = "BEARISH"
    elif composite >= 0.2:                   sentiment = "MIXED_POS"
    elif composite <= -0.2:                  sentiment = "MIXED_NEG"
    else:                                    sentiment = "NEUTRAL"

    notes = [
        f"Asia {asia_pct:+.2f}% | Europe {europe_pct:+.2f}% | US futures {us_fut_pct:+.2f}%",
        f"VIX {vix:.1f} ({'HIGH' if vix > 25 else 'elevated' if vix > 20 else 'calm'})",
        f"Composite {composite:+.2f}% -> US open bias: {open_bias}",
    ]
    if vix > 30:
        notes.append("VIX > 30 — panic level — recommend DEFENSE")
    if us_fut_pct <= -1.0:
        notes.append("US futures down >1% — expect weak open")
    if us_fut_pct >= 1.0:
        notes.append("US futures up >1% — expect strong open")

    result.update({
        "asia_pct": asia_pct, "europe_pct": europe_pct,
        "us_futures_pct": us_fut_pct, "vix": vix,
        "sentiment": sentiment, "open_bias": open_bias, "notes": notes,
    })
    return result


def classify_regime() -> RegimeSnapshot:
    btc_price, btc_7d = _get_btc_7d()
    spy_price, spy_vol = _get_spy_vol()
    global_data = _get_global_markets()

    notes   = []
    signals = []

    # BTC signal
    if btc_7d >= BTC_TREND_RISK_ON:
        signals.append(1);  notes.append(f"BTC +{btc_7d:.1f}% 7d -> risk-on")
    elif btc_7d <= BTC_TREND_RISK_OFF:
        signals.append(-1); notes.append(f"BTC {btc_7d:.1f}% 7d -> risk-off")
    else:
        signals.append(0);  notes.append(f"BTC {btc_7d:.1f}% 7d -> neutral")

    # SPY vol signal
    if spy_vol > 0:
        if spy_vol >= SPY_VOL_RISK_OFF:
            signals.append(-1); notes.append(f"SPY vol {spy_vol:.2f}% -> elevated -> risk-off")
        elif spy_vol < SPY_VOL_RISK_OFF * 0.6:
            signals.append(1);  notes.append(f"SPY vol {spy_vol:.2f}% -> calm -> risk-on")
        else:
            signals.append(0);  notes.append(f"SPY vol {spy_vol:.2f}% -> neutral")
    else:
        signals.append(0); notes.append("SPY vol unavailable")

    # Global markets signal
    g_sentiment = global_data.get("sentiment", "UNKNOWN")
    vix         = global_data.get("vix", 0.0)
    if g_sentiment in ("BULLISH",):
        signals.append(1);  notes.append(f"Global markets BULLISH -> risk-on")
    elif g_sentiment in ("BEARISH",) or vix > 25:
        signals.append(-1); notes.append(f"Global markets BEARISH / VIX {vix:.1f} -> risk-off")
    else:
        signals.append(0);  notes.append(f"Global markets {g_sentiment} -> neutral")

    score      = sum(signals)
    confidence = abs(score) / len(signals) if signals else 0.0

    if score >= 2:    regime = "RISK_ON"
    elif score <= -2: regime = "RISK_OFF"
    elif score == 1:  regime = "RISK_ON"
    elif score == -1: regime = "NEUTRAL"
    else:             regime = "NEUTRAL"

    # VIX override — if VIX > 30, always RISK_OFF regardless
    if vix > 30:
        regime = "RISK_OFF"
        confidence = 1.0

    return RegimeSnapshot(
        regime=regime,
        btc_7d_pct=btc_7d,
        spy_vol_10d=spy_vol,
        btc_price=btc_price,
        spy_price=spy_price,
        confidence=confidence,
        notes=notes,
        global_sentiment=g_sentiment,
        us_open_bias=global_data.get("open_bias", "NEUTRAL"),
        vix=vix,
        asia_pct=global_data.get("asia_pct", 0.0),
        europe_pct=global_data.get("europe_pct", 0.0),
        us_futures_pct=global_data.get("us_futures_pct", 0.0),
        global_notes=global_data.get("notes", []),
    )

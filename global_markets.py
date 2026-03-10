"""
global_markets.py — Free global market monitoring via Yahoo Finance.

Tracks key international indices and US futures to give the supervisor
brain an overnight/pre-market view of global sentiment.

Used by supervisor_regime.py to enrich regime classification.

Markets monitored:
  Asia:   Nikkei 225, Hang Seng, Shanghai Composite, ASX 200
  Europe: FTSE 100, DAX, CAC 40
  US:     S&P 500 Futures (ES=F), Nasdaq Futures (NQ=F), VIX

No API key required — Yahoo Finance free tier.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

log = logging.getLogger("global_markets")

# Yahoo Finance tickers for global indices
INDICES = {
    # Asia
    "Nikkei_225":  "^N225",
    "Hang_Seng":   "^HSI",
    "Shanghai":    "000001.SS",
    "ASX_200":     "^AXJO",
    # Europe
    "FTSE_100":    "^FTSE",
    "DAX":         "^GDAXI",
    "CAC_40":      "^FCHI",
    # US Futures (trade 24h — best pre-market signal)
    "SP500_Fut":   "ES=F",
    "Nasdaq_Fut":  "NQ=F",
    "VIX":         "^VIX",
}

REGIONS = {
    "asia":    ["Nikkei_225", "Hang_Seng", "Shanghai", "ASX_200"],
    "europe":  ["FTSE_100", "DAX", "CAC_40"],
    "us_fut":  ["SP500_Fut", "Nasdaq_Fut"],
}


@dataclass
class MarketTick:
    name: str
    ticker: str
    price: float
    change_pct: float      # 1-day % change
    direction: str         # UP | DOWN | FLAT


@dataclass
class GlobalSnapshot:
    ticks: Dict[str, MarketTick]
    asia_score: float       # avg % change for Asian markets
    europe_score: float     # avg % change for European markets
    us_futures_score: float # avg % change for US futures
    vix: float              # current VIX level
    global_sentiment: str   # BULLISH | BEARISH | MIXED | NEUTRAL
    us_open_bias: str       # UP | DOWN | NEUTRAL — predicted US open direction
    confidence: float       # 0.0–1.0
    notes: List[str] = field(default_factory=list)


def _direction(chg: float) -> str:
    if chg > 0.3:  return "UP"
    if chg < -0.3: return "DOWN"
    return "FLAT"


def fetch_global_snapshot() -> Optional[GlobalSnapshot]:
    """
    Fetch all global indices and compute sentiment scores.
    Returns GlobalSnapshot or None on complete failure.
    """
    try:
        import yfinance as yf
    except ImportError:
        log.error("yfinance not installed — run: pip install yfinance")
        return None

    ticks = {}
    for name, ticker in INDICES.items():
        try:
            t    = yf.Ticker(ticker)
            info = t.fast_info
            price = float(info.last_price or 0)
            prev  = float(info.previous_close or price)
            chg   = (price - prev) / prev * 100 if prev > 0 else 0.0
            ticks[name] = MarketTick(
                name=name, ticker=ticker,
                price=price, change_pct=chg,
                direction=_direction(chg),
            )
        except Exception as exc:
            log.warning("Failed to fetch %s (%s): %s", name, ticker, exc)

    if not ticks:
        return None

    def region_avg(keys):
        vals = [ticks[k].change_pct for k in keys if k in ticks]
        return sum(vals) / len(vals) if vals else 0.0

    asia_score    = region_avg(REGIONS["asia"])
    europe_score  = region_avg(REGIONS["europe"])
    us_fut_score  = region_avg(REGIONS["us_fut"])
    vix           = ticks.get("VIX", MarketTick("VIX","^VIX",0,0,"FLAT")).price

    # Composite score — weight US futures highest (most direct signal)
    composite = (asia_score * 0.25) + (europe_score * 0.35) + (us_fut_score * 0.40)

    # Sentiment classification
    if composite >= 0.5 and vix < 20:
        sentiment = "BULLISH"
    elif composite <= -0.5 or vix > 25:
        sentiment = "BEARISH"
    elif composite >= 0.2:
        sentiment = "MIXED_POSITIVE"
    elif composite <= -0.2:
        sentiment = "MIXED_NEGATIVE"
    else:
        sentiment = "NEUTRAL"

    # US open bias
    if us_fut_score >= 0.3:
        open_bias = "UP"
    elif us_fut_score <= -0.3:
        open_bias = "DOWN"
    else:
        # Fall back to global composite
        open_bias = "UP" if composite > 0.1 else ("DOWN" if composite < -0.1 else "NEUTRAL")

    # Confidence: how many signals agree
    signals = []
    if "SP500_Fut" in ticks:  signals.append(1 if ticks["SP500_Fut"].change_pct > 0 else -1)
    if asia_score != 0:       signals.append(1 if asia_score > 0 else -1)
    if europe_score != 0:     signals.append(1 if europe_score > 0 else -1)
    confidence = abs(sum(signals)) / len(signals) if signals else 0.0

    notes = []
    notes.append(f"Asia avg: {asia_score:+.2f}%  Europe avg: {europe_score:+.2f}%  US futures: {us_fut_score:+.2f}%")
    notes.append(f"VIX: {vix:.1f} ({'elevated' if vix > 20 else 'calm'})")
    notes.append(f"Composite: {composite:+.2f}% -> US open bias: {open_bias}")

    if vix > 30:
        notes.append("WARNING: VIX > 30 — high fear, consider defensive posture")
    if us_fut_score < -1.0:
        notes.append("WARNING: US futures down >1% — expect weak open")
    if us_fut_score > 1.0:
        notes.append("OPPORTUNITY: US futures up >1% — expect strong open")

    return GlobalSnapshot(
        ticks=ticks,
        asia_score=asia_score,
        europe_score=europe_score,
        us_futures_score=us_fut_score,
        vix=vix,
        global_sentiment=sentiment,
        us_open_bias=open_bias,
        confidence=confidence,
        notes=notes,
    )


def format_for_log(snap: GlobalSnapshot) -> str:
    lines = [f"Global: {snap.global_sentiment} | US open bias: {snap.us_open_bias} | VIX: {snap.vix:.1f}"]
    key_tickers = ["Nikkei_225", "FTSE_100", "DAX", "SP500_Fut", "Nasdaq_Fut"]
    for name in key_tickers:
        t = snap.ticks.get(name)
        if t:
            lines.append(f"  {name:<14} {t.price:>10,.1f}  {t.change_pct:>+.2f}%  {t.direction}")
    return "\n".join(lines)

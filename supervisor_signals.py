"""
supervisor_signals.py — Sentiment & on-chain signal layer.

Data sources (all free, no API key required):
  - Fear & Greed Index:  alternative.me/fng
      0–24  Extreme Fear  (contrarian BUY zone)
      25–49 Fear
      50–74 Greed
      75–100 Extreme Greed (contrarian SELL zone)

  - BTC on-chain health: blockchain.com/stats
      Hash rate trend (7-day cached delta) — miner confidence proxy
      Rising hash rate = miners investing = medium-term bullish
      Falling hash rate = miners capitulating = bearish

Signals produced:
  fear_greed_value:   0–100
  fear_greed_label:   Extreme Fear | Fear | Neutral | Greed | Extreme Greed
  contrarian_signal:  STRONG_BUY | BUY | NEUTRAL | SELL | STRONG_SELL
  onchain_health:     STRONG | NEUTRAL | WEAK
  composite_signal:   RISK_ON | NEUTRAL | RISK_OFF
  composite_score:    -1.0 to +1.0
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

import requests

log = logging.getLogger("supervisor_signals")

BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
HASHRATE_CACHE  = os.path.join(BASE_DIR, "hashrate_cache.json")

FNG_URL       = "https://api.alternative.me/fng/?limit=7"
BLOCKCHAIN_URL = "https://api.blockchain.info/stats"

REQUEST_TIMEOUT = 10


@dataclass
class SentimentSnapshot:
    # Fear & Greed
    fear_greed_now: int         # 0–100
    fear_greed_label: str
    fear_greed_7d_avg: float
    contrarian_signal: str      # STRONG_BUY | BUY | NEUTRAL | SELL | STRONG_SELL

    # On-chain
    hash_rate_th: float         # current THash/s
    hash_rate_7d_chg_pct: float # vs cached value from last call
    onchain_health: str         # STRONG | NEUTRAL | WEAK

    # Composite
    composite_signal: str       # RISK_ON | NEUTRAL | RISK_OFF
    composite_score: float      # -1.0 to +1.0
    notes: List[str] = field(default_factory=list)


# ── Fear & Greed ────────────────────────────────────────────────────

def _get_fear_greed() -> Optional[dict]:
    try:
        resp = requests.get(FNG_URL, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if not data:
            return None
        current = int(data[0]["value"])
        label   = data[0].get("value_classification", "Unknown")
        avg_7d  = sum(int(d["value"]) for d in data) / len(data)
        return {"current": current, "label": label, "avg_7d": round(avg_7d, 1)}
    except Exception as exc:
        log.warning("Fear & Greed fetch failed: %s", exc)
        return None


def _contrarian_signal(value: int, avg_7d: float) -> tuple[str, float]:
    """
    Contrarian interpretation: crowd extremes are usually wrong.
    Returns (signal, score) where score: +1=strong buy, -1=strong sell.
    """
    if value <= 15:
        return "STRONG_BUY", 1.0    # panic bottom — aggressive buy
    if value <= 30:
        return "BUY", 0.5           # fear — lean long
    if value >= 85:
        return "STRONG_SELL", -1.0  # euphoria — aggressive caution
    if value >= 70:
        return "SELL", -0.5         # greed — reduce exposure
    return "NEUTRAL", 0.0


# ── On-chain: Hash Rate ──────────────────────────────────────────────

def _load_hashrate_cache() -> Optional[dict]:
    try:
        if os.path.exists(HASHRATE_CACHE):
            with open(HASHRATE_CACHE, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return None


def _save_hashrate_cache(hash_rate: float) -> None:
    try:
        with open(HASHRATE_CACHE, "w", encoding="utf-8") as f:
            json.dump({
                "hash_rate": hash_rate,
                "ts": datetime.now(timezone.utc).isoformat(),
            }, f)
    except Exception as exc:
        log.warning("Failed to save hashrate cache: %s", exc)


def _get_onchain() -> tuple[float, float]:
    """
    Returns (current_hash_rate_TH, change_pct_vs_cached).
    """
    try:
        resp = requests.get(BLOCKCHAIN_URL, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data      = resp.json()
        hash_rate = float(data.get("hash_rate", 0))   # EH/s from blockchain.info

        cached = _load_hashrate_cache()
        if cached and cached.get("hash_rate", 0) > 0:
            prev   = cached["hash_rate"]
            chg_pct = (hash_rate - prev) / prev * 100
        else:
            chg_pct = 0.0

        _save_hashrate_cache(hash_rate)
        return hash_rate, chg_pct
    except Exception as exc:
        log.warning("On-chain hash rate fetch failed: %s", exc)
        return 0.0, 0.0


def _onchain_health(chg_pct: float) -> tuple[str, float]:
    """
    Maps hash rate change to health score.
    Returns (label, score) where score: +1=strong, -1=weak.
    """
    if chg_pct >= 3.0:
        return "STRONG", 0.5
    if chg_pct >= 0.5:
        return "STRONG", 0.25
    if chg_pct <= -5.0:
        return "WEAK", -0.75
    if chg_pct <= -2.0:
        return "WEAK", -0.4
    return "NEUTRAL", 0.0


# ── Composite ───────────────────────────────────────────────────────

def _composite(fg_score: float, onchain_score: float) -> tuple[str, float]:
    """
    Weighted composite: Fear & Greed 70%, on-chain 30%.
    Returns (signal, score) where score: -1.0 to +1.0.
    """
    score = fg_score * 0.70 + onchain_score * 0.30
    if score >= 0.4:    return "RISK_ON",  round(score, 3)
    if score <= -0.4:   return "RISK_OFF", round(score, 3)
    return "NEUTRAL", round(score, 3)


# ── Public API ──────────────────────────────────────────────────────

def get_sentiment_signals() -> SentimentSnapshot:
    """Fetch all sentiment + on-chain signals. Returns SentimentSnapshot."""
    notes = []

    # Fear & Greed
    fg_data = _get_fear_greed()
    if fg_data:
        fg_value  = fg_data["current"]
        fg_label  = fg_data["label"]
        fg_avg_7d = fg_data["avg_7d"]
    else:
        fg_value  = 50
        fg_label  = "Neutral (unavailable)"
        fg_avg_7d = 50.0

    contra_signal, fg_score = _contrarian_signal(fg_value, fg_avg_7d)

    # On-chain
    hash_rate, hash_chg = _get_onchain()
    health_label, onchain_score = _onchain_health(hash_chg)

    # Composite
    composite, composite_score = _composite(fg_score, onchain_score)

    # Build notes
    notes.append(
        f"Fear & Greed: {fg_value}/100 ({fg_label}) | 7d avg: {fg_avg_7d:.0f} -> {contra_signal}"
    )
    if hash_rate > 0:
        notes.append(
            f"BTC hash rate: {hash_rate:,.0f} EH/s ({hash_chg:+.1f}% vs last check) -> {health_label}"
        )
    else:
        notes.append("BTC hash rate: unavailable")

    if fg_value <= 20:
        notes.append("EXTREME FEAR — historically strong contrarian buy zone")
    if fg_value >= 80:
        notes.append("EXTREME GREED — historically strong contrarian sell zone")

    notes.append(f"Sentiment composite: {composite} (score {composite_score:+.2f})")

    return SentimentSnapshot(
        fear_greed_now=fg_value,
        fear_greed_label=fg_label,
        fear_greed_7d_avg=fg_avg_7d,
        contrarian_signal=contra_signal,
        hash_rate_th=hash_rate,
        hash_rate_7d_chg_pct=round(hash_chg, 2),
        onchain_health=health_label,
        composite_signal=composite,
        composite_score=composite_score,
        notes=notes,
    )


def format_signals_for_prompt(snap: SentimentSnapshot) -> str:
    lines = []
    for note in snap.notes:
        lines.append(f"  {note}")
    return "\n".join(lines)

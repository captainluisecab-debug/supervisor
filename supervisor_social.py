"""
supervisor_social.py — Social sentiment layer via Reddit community analysis.

Reddit's public JSON API (no auth required) gives access to the most active
trading communities. Post titles and scores reflect real crowd conviction.

Subreddits monitored:
  r/CryptoCurrency  — crypto crowd sentiment
  r/Bitcoin         — BTC-specific community
  r/stocks          — equity market crowd

Method:
  - Fetch hot posts from each subreddit (public JSON endpoint)
  - Score titles using bullish/bearish keywords (same as news module)
  - Weight by post score (upvotes) — high-conviction posts matter more
  - Compute weighted bull ratio per community

Contrarian thresholds (crowd extremes are usually wrong):
  Weighted bull ratio > 0.65 -> crowd too bullish -> CAUTION
  Weighted bull ratio < 0.35 -> crowd too bearish -> OPPORTUNITY

No API key required. Rate limit: ~60 requests/minute (well within our usage).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import requests

log = logging.getLogger("supervisor_social")

REQUEST_TIMEOUT = 12
# Reddit requires a proper User-Agent to avoid 429s
USER_AGENT = "script:supervisor_brain:v1.0 (autonomous trading system)"

SUBREDDITS = {
    "CryptoCurrency": "crypto",
    "Bitcoin":        "crypto",
    "stocks":         "equity",
}

REDDIT_URL = "https://www.reddit.com/r/{sub}/hot.json?limit=25"

BULLISH_WORDS = {
    "rally", "surge", "soar", "gain", "bull", "bullish", "breakout",
    "ath", "all-time high", "buy", "recovery", "jump", "rise", "rising",
    "moon", "pump", "accumulate", "hodl", "strong", "green", "up",
    "beat", "record", "positive", "higher", "support", "bounce",
}
BEARISH_WORDS = {
    "crash", "drop", "fall", "fear", "bear", "bearish", "selloff",
    "sell-off", "collapse", "ban", "hack", "exploit", "liquidation",
    "recession", "inflation", "dump", "panic", "weak", "down", "red",
    "scam", "fraud", "rug", "warning", "lower", "break", "resistance",
    "correction", "bloodbath", "wipe",
}

EXTREME_BULL = 0.65
EXTREME_BEAR = 0.35


@dataclass
class SubredditSentiment:
    subreddit: str
    category: str          # crypto | equity
    bull_score: float      # upvote-weighted bullish score
    bear_score: float
    bull_ratio: float      # bull / (bull + bear)
    signal: str            # CONTRARIAN_SELL | CONTRARIAN_BUY | NEUTRAL
    post_count: int


@dataclass
class SocialSnapshot:
    subreddits: Dict[str, SubredditSentiment]
    overall_signal: str
    crypto_bull_ratio: float
    equity_bull_ratio: float
    notes: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def _score_title(title: str) -> int:
    """Returns +1 (bullish), -1 (bearish), 0 (neutral)."""
    lower = title.lower()
    bull  = sum(1 for w in BULLISH_WORDS if w in lower)
    bear  = sum(1 for w in BEARISH_WORDS if w in lower)
    if bull > bear:  return 1
    if bear > bull:  return -1
    return 0


def _fetch_subreddit(sub: str) -> tuple[Optional[SubredditSentiment], Optional[str]]:
    category = SUBREDDITS.get(sub, "other")
    try:
        url  = REDDIT_URL.format(sub=sub)
        resp = requests.get(
            url, timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        posts = resp.json().get("data", {}).get("children", [])

        bull_score = 0.0
        bear_score = 0.0

        for post in posts:
            d     = post.get("data", {})
            title = d.get("title", "")
            score = max(1, int(d.get("score", 1)))   # upvotes, min 1
            sent  = _score_title(title)
            if sent == 1:    bull_score += score
            elif sent == -1: bear_score += score

        total = bull_score + bear_score
        bull_ratio = bull_score / total if total > 0 else 0.5

        if bull_ratio >= EXTREME_BULL:   signal = "CONTRARIAN_SELL"
        elif bull_ratio <= EXTREME_BEAR: signal = "CONTRARIAN_BUY"
        else:                            signal = "NEUTRAL"

        log.info(
            "[SOCIAL] r/%-16s bull=%.0f%% (weighted) -> %s",
            sub, bull_ratio * 100, signal,
        )

        return SubredditSentiment(
            subreddit=sub, category=category,
            bull_score=round(bull_score, 0),
            bear_score=round(bear_score, 0),
            bull_ratio=round(bull_ratio, 3),
            signal=signal,
            post_count=len(posts),
        ), None

    except Exception as exc:
        return None, f"r/{sub}: {exc}"


def fetch_social() -> SocialSnapshot:
    results = {}
    errors  = []

    for sub in SUBREDDITS:
        sent, err = _fetch_subreddit(sub)
        if err:
            log.warning("[SOCIAL] %s", err)
            errors.append(err)
        if sent:
            results[sub] = sent

    crypto_subs = [s for s in results.values() if s.category == "crypto"]
    equity_subs = [s for s in results.values() if s.category == "equity"]

    crypto_bull = (sum(s.bull_ratio for s in crypto_subs) / len(crypto_subs)
                   if crypto_subs else 0.5)
    equity_bull = (sum(s.bull_ratio for s in equity_subs) / len(equity_subs)
                   if equity_subs else 0.5)

    signals = [s.signal for s in results.values() if s.signal != "NEUTRAL"]
    if not signals:                                    overall = "NEUTRAL"
    elif all(s == "CONTRARIAN_BUY" for s in signals):  overall = "CONTRARIAN_BUY"
    elif all(s == "CONTRARIAN_SELL" for s in signals): overall = "CONTRARIAN_SELL"
    else:                                              overall = "MIXED"

    notes = []
    if crypto_bull >= EXTREME_BULL:
        notes.append(
            f"Crypto Reddit very bullish ({crypto_bull:.0%} weighted) — "
            f"euphoria signal, contrarian caution advised"
        )
    elif crypto_bull <= EXTREME_BEAR:
        notes.append(
            f"Crypto Reddit very bearish ({crypto_bull:.0%} weighted) — "
            f"capitulation signal, contrarian opportunity"
        )
    if equity_bull >= EXTREME_BULL:
        notes.append(f"Equity Reddit very bullish ({equity_bull:.0%}) — trim exposure")
    elif equity_bull <= EXTREME_BEAR:
        notes.append(f"Equity Reddit very bearish ({equity_bull:.0%}) — buy signal")

    return SocialSnapshot(
        subreddits=results,
        overall_signal=overall,
        crypto_bull_ratio=round(crypto_bull, 3),
        equity_bull_ratio=round(equity_bull, 3),
        notes=notes,
        errors=errors,
    )


def format_social_for_prompt(snap: SocialSnapshot) -> str:
    if not snap.subreddits and snap.errors:
        return "  Social sentiment: unavailable"

    lines = [
        f"  Overall signal: {snap.overall_signal}",
        f"  Crypto Reddit:  {snap.crypto_bull_ratio:.0%} bullish (upvote-weighted)",
        f"  Equity Reddit:  {snap.equity_bull_ratio:.0%} bullish (upvote-weighted)",
        "",
    ]
    for sub, s in snap.subreddits.items():
        lines.append(
            f"  r/{sub:<18} {s.bull_ratio:.0%} bull -> {s.signal}"
        )
    for note in snap.notes:
        lines.append(f"  !! {note}")

    return "\n".join(lines)

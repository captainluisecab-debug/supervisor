"""
supervisor_news.py — Real-time news feed aggregator.

Sources (all free, no API key required — RSS feeds):
  - CoinDesk:       crypto market news
  - CoinTelegraph:  crypto analysis + breaking news
  - Reuters:        macro/global business news

Headlines are extracted, deduplicated, and scored for market sentiment.
Claude receives the top headlines as context — it interprets them natively,
the way a trader reads the morning tape.

Sentiment scoring uses keyword matching:
  Bullish keywords:  rally, surge, gains, bullish, breakout, ATH, buy...
  Bearish keywords:  crash, drop, fear, selloff, bear, collapse, ban...
  Neutral:           everything else

Output:
  NewsSnapshot with top headlines, sentiment score, and a formatted
  block ready for Claude's prompt.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional
import re

import requests

log = logging.getLogger("supervisor_news")

REQUEST_TIMEOUT = 10
MAX_HEADLINES   = 6   # per source
USER_AGENT      = "Mozilla/5.0 (compatible; SupervisorBot/1.0)"

RSS_FEEDS = {
    "CoinDesk":     "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "CoinTelegraph": "https://cointelegraph.com/rss",
    "BBC_Business": "https://feeds.bbci.co.uk/news/business/rss.xml",
    "MarketWatch":  "https://feeds.marketwatch.com/marketwatch/topstories/",
}

BULLISH_KEYWORDS = {
    "rally", "surge", "soar", "gain", "bullish", "breakout", "ath",
    "all-time high", "buy", "recovery", "jump", "rise", "rising",
    "institutional", "adoption", "approval", "etf approved", "strong",
    "positive", "beat", "outperform", "record", "green",
}
BEARISH_KEYWORDS = {
    "crash", "drop", "fall", "fear", "bearish", "selloff", "sell-off",
    "collapse", "ban", "hack", "exploit", "liquidation", "warning",
    "recession", "inflation", "hawkish", "tighten", "red", "plunge",
    "dump", "rug", "scam", "fraud", "down", "weak", "miss", "underperform",
}


@dataclass
class Headline:
    source: str
    title: str
    sentiment: str    # BULLISH | BEARISH | NEUTRAL
    score: int        # +1 | -1 | 0


@dataclass
class NewsSnapshot:
    headlines: List[Headline]
    bullish_ct: int
    bearish_ct: int
    neutral_ct: int
    sentiment_score: float      # -1.0 to +1.0
    sentiment_label: str        # BULLISH | BEARISH | NEUTRAL | MIXED
    fetch_ts: str
    errors: List[str] = field(default_factory=list)


def _score_headline(title: str) -> tuple[str, int]:
    """Keyword-based sentiment score for a headline."""
    lower = title.lower()
    bull  = sum(1 for kw in BULLISH_KEYWORDS if kw in lower)
    bear  = sum(1 for kw in BEARISH_KEYWORDS if kw in lower)
    if bull > bear:   return "BULLISH", 1
    if bear > bull:   return "BEARISH", -1
    return "NEUTRAL", 0


def _clean(text: str) -> str:
    """Strip HTML tags and excessive whitespace."""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:180]


def _fetch_rss(name: str, url: str) -> tuple[List[Headline], Optional[str]]:
    """Fetch and parse one RSS feed. Returns (headlines, error_or_None)."""
    try:
        resp = requests.get(
            url, timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        root     = ET.fromstring(resp.content)
        items    = root.findall(".//item")
        results  = []
        seen     = set()

        for item in items[:MAX_HEADLINES]:
            title = _clean(item.findtext("title", ""))
            if not title or title in seen:
                continue
            seen.add(title)
            sentiment, score = _score_headline(title)
            results.append(Headline(source=name, title=title,
                                    sentiment=sentiment, score=score))

        return results, None

    except ET.ParseError as exc:
        return [], f"{name}: XML parse error ({exc})"
    except Exception as exc:
        return [], f"{name}: {exc}"


def fetch_news() -> NewsSnapshot:
    """Fetch all RSS feeds and return a NewsSnapshot."""
    all_headlines = []
    errors        = []

    for name, url in RSS_FEEDS.items():
        headlines, err = _fetch_rss(name, url)
        if err:
            log.warning("[NEWS] %s", err)
            errors.append(err)
        all_headlines.extend(headlines)

    bullish = sum(1 for h in all_headlines if h.sentiment == "BULLISH")
    bearish = sum(1 for h in all_headlines if h.sentiment == "BEARISH")
    neutral = sum(1 for h in all_headlines if h.sentiment == "NEUTRAL")
    total   = len(all_headlines)

    if total > 0:
        raw_score = (bullish - bearish) / total
    else:
        raw_score = 0.0

    if raw_score >= 0.3:      label = "BULLISH"
    elif raw_score <= -0.3:   label = "BEARISH"
    elif bullish > 0 and bearish > 0: label = "MIXED"
    else:                     label = "NEUTRAL"

    log.info(
        "[NEWS] %d headlines | bull=%d bear=%d neutral=%d | score=%.2f %s",
        total, bullish, bearish, neutral, raw_score, label,
    )

    return NewsSnapshot(
        headlines=all_headlines,
        bullish_ct=bullish,
        bearish_ct=bearish,
        neutral_ct=neutral,
        sentiment_score=round(raw_score, 3),
        sentiment_label=label,
        fetch_ts=datetime.now(timezone.utc).isoformat(),
        errors=errors,
    )


def format_news_for_prompt(snap: NewsSnapshot, max_headlines: int = 10) -> str:
    """Format news for Claude's prompt."""
    if not snap.headlines:
        return "  No news headlines available."

    lines = [
        f"  Sentiment: {snap.sentiment_label} "
        f"(bull={snap.bullish_ct} bear={snap.bearish_ct} neutral={snap.neutral_ct} "
        f"score={snap.sentiment_score:+.2f})",
        "",
    ]

    # Show bearish first (most important for risk management), then bullish
    sorted_headlines = (
        [h for h in snap.headlines if h.sentiment == "BEARISH"] +
        [h for h in snap.headlines if h.sentiment == "BULLISH"] +
        [h for h in snap.headlines if h.sentiment == "NEUTRAL"]
    )

    for h in sorted_headlines[:max_headlines]:
        tag = "[-]" if h.sentiment == "BEARISH" else ("[+]" if h.sentiment == "BULLISH" else "[ ]")
        lines.append(f"  {tag} [{h.source}] {h.title}")

    return "\n".join(lines)

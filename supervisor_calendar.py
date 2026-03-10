"""
supervisor_calendar.py — Economic event calendar & high-impact day detector.

Knows about:
  - FOMC meetings (Fed rate decisions) — hardcoded for 2026
  - Non-Farm Payrolls (NFP) — first Friday of each month
  - CPI release — approximately 10th–13th of each month
  - Earnings season — peak weeks in Jan/Apr/Jul/Oct
  - Options expiration — 3rd Friday of each month (OpEx)

When a high-impact event is today or tomorrow:
  - Claude is warned to hold positions, avoid new entries
  - SCOUT mode recommended for crypto; DEFENSE before major Fed decisions
  - Reduces false signals from news-driven volatility

This is one of the most underused edges in retail trading:
knowing WHEN not to trade is as valuable as knowing when to trade.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional, Tuple

log = logging.getLogger("supervisor_calendar")

# ── FOMC 2026 meeting dates (final day = decision day) ───────────────
# Source: Federal Reserve official schedule
FOMC_2026 = [
    date(2026, 1, 29),
    date(2026, 3, 19),
    date(2026, 5, 7),
    date(2026, 6, 18),
    date(2026, 7, 30),
    date(2026, 9, 17),
    date(2026, 10, 29),
    date(2026, 12, 17),
]

# FOMC 2027 (approximate — Fed announces these ~1 year ahead)
FOMC_2027 = [
    date(2027, 1, 28),
    date(2027, 3, 18),
    date(2027, 5, 6),
    date(2027, 6, 17),
    date(2027, 7, 29),
    date(2027, 9, 16),
    date(2027, 10, 28),
    date(2027, 12, 16),
]

ALL_FOMC = FOMC_2026 + FOMC_2027

# Impact levels
HIGH   = "HIGH"
MEDIUM = "MEDIUM"
LOW    = "LOW"


@dataclass
class CalendarEvent:
    name: str
    date: date
    impact: str          # HIGH | MEDIUM | LOW
    description: str
    action: str          # what the brain should do


@dataclass
class CalendarSnapshot:
    today_events: List[CalendarEvent]
    tomorrow_events: List[CalendarEvent]
    upcoming_events: List[CalendarEvent]   # next 7 days (excluding today/tomorrow)
    risk_level: str                        # HIGH | MEDIUM | LOW
    recommendation: str                   # pre-built instruction for Claude
    notes: List[str] = field(default_factory=list)


# ── Event detection helpers ──────────────────────────────────────────

def _first_friday(year: int, month: int) -> date:
    """First Friday of the given month."""
    d = date(year, month, 1)
    while d.weekday() != 4:   # 4 = Friday
        d += timedelta(days=1)
    return d


def _third_friday(year: int, month: int) -> date:
    """Third Friday of the given month (OpEx)."""
    count = 0
    d = date(year, month, 1)
    while True:
        if d.weekday() == 4:
            count += 1
            if count == 3:
                return d
        d += timedelta(days=1)


def _cpi_date(year: int, month: int) -> date:
    """
    CPI is typically released the 2nd or 3rd Wednesday of the month.
    Approximate: use the 12th, adjusted to nearest Wednesday.
    """
    d = date(year, month, 12)
    # Find nearest Wednesday
    offset = (2 - d.weekday()) % 7   # 2 = Wednesday
    return d + timedelta(days=offset)


def _is_earnings_season(d: date) -> bool:
    """
    Earnings season: peak weeks ~2-5 weeks after quarter end.
    Q1 ends Mar 31 -> peak Apr 14 – May 7
    Q2 ends Jun 30 -> peak Jul 14 – Aug 7
    Q3 ends Sep 30 -> peak Oct 14 – Nov 7
    Q4 ends Dec 31 -> peak Jan 14 – Feb 7
    """
    month, day = d.month, d.day
    if month == 4 and day >= 14:  return True
    if month == 5 and day <= 7:   return True
    if month == 7 and day >= 14:  return True
    if month == 8 and day <= 7:   return True
    if month == 10 and day >= 14: return True
    if month == 11 and day <= 7:  return True
    if month == 1 and day >= 14:  return True
    if month == 2 and day <= 7:   return True
    return False


def _generate_events(start: date, end: date) -> List[CalendarEvent]:
    """Generate all known events between start and end (inclusive)."""
    events = []
    d = start
    while d <= end:
        # FOMC
        if d in ALL_FOMC:
            events.append(CalendarEvent(
                name="FOMC Rate Decision",
                date=d,
                impact=HIGH,
                description="Federal Reserve interest rate decision — major market mover",
                action="Avoid new entries 24h before and after. SCOUT or DEFENSE for all sleeves.",
            ))
            # Also flag the day before
        if d + timedelta(days=1) in ALL_FOMC:
            events.append(CalendarEvent(
                name="FOMC Eve",
                date=d,
                impact=HIGH,
                description="Federal Reserve decision tomorrow — pre-FOMC volatility likely",
                action="Reduce size, no new large positions. Markets historically choppy.",
            ))

        # NFP (Non-Farm Payrolls) — first Friday of month
        nfp = _first_friday(d.year, d.month)
        if d == nfp:
            events.append(CalendarEvent(
                name="NFP Release",
                date=d,
                impact=HIGH,
                description="Non-Farm Payrolls — major USD and equity market mover",
                action="Alpaca stocks: wait for data before new entries. Gap risk is real.",
            ))

        # CPI
        cpi = _cpi_date(d.year, d.month)
        if d == cpi:
            events.append(CalendarEvent(
                name="CPI Release (approx)",
                date=d,
                impact=HIGH,
                description="Consumer Price Index — key inflation print, moves rate expectations",
                action="SCOUT for crypto and stocks until print digested. Hot CPI = risk-off.",
            ))

        # OpEx (options expiration) — 3rd Friday
        opex = _third_friday(d.year, d.month)
        if d == opex:
            events.append(CalendarEvent(
                name="Monthly OpEx",
                date=d,
                impact=MEDIUM,
                description="Monthly options expiration — increased volatility, potential pinning",
                action="Watch for unusual moves. Reduce size on Alpaca during afternoon session.",
            ))

        # Earnings season
        if _is_earnings_season(d) and d.weekday() < 5:
            # Only flag the first occurrence per season start
            pass   # We handle this in snapshot notes instead

        d += timedelta(days=1)

    return events


# ── Public API ──────────────────────────────────────────────────────

def get_calendar() -> CalendarSnapshot:
    """
    Build a calendar snapshot for today and the next 7 days.
    Returns CalendarSnapshot with risk level and Claude instruction.
    """
    today    = datetime.now(timezone.utc).date()
    tomorrow = today + timedelta(days=1)
    week_end = today + timedelta(days=7)

    all_events = _generate_events(today, week_end)

    today_events    = [e for e in all_events if e.date == today]
    tomorrow_events = [e for e in all_events if e.date == tomorrow]
    upcoming_events = [e for e in all_events if today < e.date <= week_end
                       and e.date != tomorrow]

    # Risk level = highest impact of today + tomorrow
    combined = today_events + tomorrow_events
    if any(e.impact == HIGH for e in combined):
        risk_level = HIGH
    elif any(e.impact == MEDIUM for e in combined):
        risk_level = MEDIUM
    else:
        risk_level = LOW

    # Build recommendation
    notes = []
    if _is_earnings_season(today):
        notes.append("Earnings season active — individual stock gaps are elevated")

    if risk_level == HIGH:
        recommendation = (
            "HIGH IMPACT EVENT today or tomorrow. "
            "Reduce all size_mults. Avoid new Alpaca entries until data is released. "
            "Crypto entries at 0.3x only. Preserve capital."
        )
    elif risk_level == MEDIUM:
        recommendation = (
            "Medium impact event nearby. Slight caution advised. "
            "No change to crypto. Trim Alpaca new entries to 0.7x."
        )
    else:
        recommendation = "No major events today or tomorrow. Normal operation."

    log.info(
        "[CALENDAR] Risk=%s | today=%d events | tomorrow=%d events | upcoming=%d",
        risk_level, len(today_events), len(tomorrow_events), len(upcoming_events),
    )

    return CalendarSnapshot(
        today_events=today_events,
        tomorrow_events=tomorrow_events,
        upcoming_events=upcoming_events,
        risk_level=risk_level,
        recommendation=recommendation,
        notes=notes,
    )


def format_calendar_for_prompt(snap: CalendarSnapshot) -> str:
    """Format calendar for Claude's prompt."""
    lines = [f"  Risk level: {snap.risk_level}"]

    if snap.today_events:
        lines.append("  TODAY:")
        for e in snap.today_events:
            lines.append(f"    [{e.impact}] {e.name} — {e.description}")
            lines.append(f"           -> {e.action}")

    if snap.tomorrow_events:
        lines.append("  TOMORROW:")
        for e in snap.tomorrow_events:
            lines.append(f"    [{e.impact}] {e.name} — {e.description}")
            lines.append(f"           -> {e.action}")

    if snap.upcoming_events:
        lines.append("  THIS WEEK:")
        for e in snap.upcoming_events:
            lines.append(f"    {e.date.strftime('%a %b %d')} [{e.impact}] {e.name}")

    for note in snap.notes:
        lines.append(f"  Note: {note}")

    lines.append(f"  Instruction: {snap.recommendation}")

    return "\n".join(lines)

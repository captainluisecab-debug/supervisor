"""
time_fmt.py — canonical time/date rendering for the entire system.

ALL human-readable time output across supervisor briefs, review packets,
release notes, TTL expiry messages, escalation reports MUST go through
this module. Eliminates the class of bugs where:
  - Weekday shown ("Saturday") doesn't match the date ("2026-04-26 is Sunday")
  - UTC and ET labels get mixed without declaration
  - Narrative labels ("morning", "pre-market") attach to wrong times
  - Release times shown without indicating default-TTL vs operator-set

Canonical rendering:
    "2026-04-25 Fri 14:30 ET (18:30 UTC)"

Everything else — weekday, date, local label, UTC cross-reference — is
derived from ONE datetime object via zoneinfo (DST-aware).
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional


# US/Eastern DST handled by picking the correct fixed-offset timezone per call.
# Avoids zoneinfo's tzdata dependency (Windows Python lacks DST database by
# default) and avoids a custom tzinfo class (which has Python-contract quirks
# around astimezone re-entering utcoffset).
# US DST rules (stable since 2007):
#   Start: 2nd Sunday of March  @ 02:00 local (→ 07:00 UTC from 06:00 UTC)
#   End:   1st Sunday of November @ 02:00 local (→ 06:00 UTC from 06:00 UTC)

_EDT = timezone(timedelta(hours=-4), name="EDT")
_EST = timezone(timedelta(hours=-5), name="EST")


def _is_edt_active(dt_utc: datetime) -> bool:
    """Is DST (EDT) in effect at this UTC moment?"""
    year = dt_utc.year
    march_first = datetime(year, 3, 1, tzinfo=timezone.utc)
    days_to_sun = (6 - march_first.weekday()) % 7
    dst_start_utc = march_first + timedelta(days=days_to_sun + 7, hours=7)
    nov_first = datetime(year, 11, 1, tzinfo=timezone.utc)
    days_to_sun = (6 - nov_first.weekday()) % 7
    dst_end_utc = nov_first + timedelta(days=days_to_sun, hours=6)
    return dst_start_utc <= dt_utc < dst_end_utc


def _et_tz_for(dt_utc: datetime):
    """Return the correct ET fixed-offset timezone for the given UTC moment."""
    return _EDT if _is_edt_active(dt_utc) else _EST


# ── Canonical "now" ──────────────────────────────────────────────────

def now_utc() -> datetime:
    """The ONE authoritative 'now' — timezone-aware UTC datetime.
    All other time functions in this module derive from this (or an
    explicit input datetime). Never use naive datetime.now() for display.
    """
    return datetime.now(timezone.utc)


def to_et(dt: Optional[datetime] = None) -> datetime:
    """Convert any aware datetime (or now) to US/Eastern. DST-correct."""
    dt = dt or now_utc()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.astimezone(_et_tz_for(dt_utc))


def to_utc(dt: Optional[datetime] = None) -> datetime:
    """Convert any aware datetime (or now) to UTC."""
    dt = dt or now_utc()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ── Rendering functions ──────────────────────────────────────────────

def fmt_full(dt: Optional[datetime] = None) -> str:
    """Canonical full format: '2026-04-25 Fri 14:30 ET (18:30 UTC)'

    Weekday, date, ET time, UTC time all derived from the SAME datetime.
    No mismatch possible.
    """
    dt = dt or now_utc()
    et = to_et(dt)
    utc = to_utc(dt)
    return f"{et.strftime('%Y-%m-%d %a %H:%M')} ET ({utc.strftime('%H:%M')} UTC)"


def fmt_short(dt: Optional[datetime] = None) -> str:
    """Short: '2026-04-25 14:30 ET' — for tight tables."""
    dt = dt or now_utc()
    et = to_et(dt)
    return f"{et.strftime('%Y-%m-%d %H:%M')} ET"


def fmt_iso_utc(dt: Optional[datetime] = None) -> str:
    """ISO8601 UTC for machine-readable logs / files.
    Format: 2026-04-25T18:30:00+00:00
    """
    dt = dt or now_utc()
    return to_utc(dt).isoformat(timespec="seconds")


def fmt_countdown(target: datetime, base: Optional[datetime] = None) -> str:
    """'14h 22m until 2026-04-25 Fri 16:00 ET (20:00 UTC)'.
    Negative = expired: '-2h 5m (2026-04-25 Fri 14:00 ET expired)'.
    """
    base = base or now_utc()
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    delta = target - base
    sec = int(delta.total_seconds())
    target_str = fmt_full(target)
    if sec < 0:
        # Expired
        abs_sec = -sec
        h, rem = divmod(abs_sec, 3600)
        m = rem // 60
        return f"expired {h}h {m}m ago ({target_str})"
    h, rem = divmod(sec, 3600)
    m = rem // 60
    return f"{h}h {m}m until {target_str}"


# ── Release / TTL messaging (operator-consistency-critical) ──────────

_VALID_RELEASE_TYPES = {
    "default_ttl",          # TTL expiry set by the original writer (e.g., sentinel auto-2h)
    "operator_approved",    # operator explicitly released
    "extended",             # TTL pushed later (same release semantics)
    "delayed",              # operator held release past default
}


def render_ttl(ttl_iso: str, release_type: str = "default_ttl",
               base: Optional[datetime] = None) -> str:
    """Render a TTL timestamp with unambiguous release-type label.

    release_type must be one of: default_ttl | operator_approved | extended | delayed

    Example:
        "expires 2026-04-25 Fri 16:00 ET (20:00 UTC) — default_ttl
         (14h 22m from 2026-04-25 Fri 01:38 ET)"
    """
    if release_type not in _VALID_RELEASE_TYPES:
        raise ValueError(
            f"release_type must be one of {sorted(_VALID_RELEASE_TYPES)}, got {release_type!r}"
        )
    try:
        if ttl_iso.endswith("Z"):
            ttl_iso = ttl_iso.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ttl_iso)
    except Exception as e:
        return f"[invalid ttl: {ttl_iso!r} — {e}]"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    base = base or now_utc()
    return (
        f"expires {fmt_full(dt)} — {release_type}  "
        f"({fmt_countdown(dt, base)})"
    )


def release_time_description(ttl_iso: str, release_type: str = "default_ttl",
                              subject: str = "",
                              base: Optional[datetime] = None) -> str:
    """Multi-line standardized block for operator-facing release messages.

    subject (optional) — e.g., "Kraken pause"

    Example:
        ─ Kraken pause ─
        Release type:   operator_approved
        Release time:   2026-04-25 Fri 16:00 ET (20:00 UTC)
        Current time:   2026-04-25 Fri 01:38 ET (05:38 UTC)
        Countdown:      14h 22m until release
    """
    if release_type not in _VALID_RELEASE_TYPES:
        raise ValueError(
            f"release_type must be one of {sorted(_VALID_RELEASE_TYPES)}, got {release_type!r}"
        )
    try:
        if ttl_iso.endswith("Z"):
            ttl_iso = ttl_iso.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ttl_iso)
    except Exception as e:
        return f"[invalid ttl: {ttl_iso!r} — {e}]"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    base = base or now_utc()
    delta_sec = int((dt - base).total_seconds())
    h, rem = divmod(abs(delta_sec), 3600)
    m = rem // 60
    direction = "until release" if delta_sec >= 0 else "past release time (expired)"
    subject_line = f"─ {subject} ─\n" if subject else ""
    return (
        f"{subject_line}"
        f"Release type:   {release_type}\n"
        f"Release time:   {fmt_full(dt)}\n"
        f"Current time:   {fmt_full(base)}\n"
        f"Countdown:      {h}h {m}m {direction}"
    )


# ── Narrative label validation ───────────────────────────────────────

# Mapping: label → set of ET-hours-of-day when it's TRUE
_TIME_LABELS = {
    "pre_market":    set(range(4, 10)),       # 04:00-09:59 ET
    "pre-market":    set(range(4, 10)),       # alias with hyphen
    "open_bell":     {9, 10},                 # 09:00-10:59 (opening hour)
    "morning":       set(range(6, 12)),       # 06:00-11:59 ET
    "midday":        set(range(11, 14)),      # 11:00-13:59
    "lunch":         {11, 12, 13},            # 11-13 ET
    "afternoon":     set(range(12, 17)),      # 12:00-16:59
    "closing_hour":  {15},                    # 15:00-15:59 (last hour)
    "after_close":   set(range(16, 20)),      # 16:00-19:59
    "evening":       set(range(17, 22)),      # 17:00-21:59
    "overnight":     set(range(22, 24)) | set(range(0, 4)),  # 22-03 ET
}


def validate_time_label(label: str, dt: Optional[datetime] = None) -> bool:
    """True iff the label matches the actual ET-hour of dt.

    Use in report templates before rendering narrative labels:
        if not validate_time_label("morning", now_utc()):
            label = "evening"  # or raise, or skip
    """
    dt = dt or now_utc()
    et = to_et(dt)
    hour = et.hour
    expected = _TIME_LABELS.get(label.lower())
    if expected is None:
        # Unknown label — don't vouch for it
        return False
    return hour in expected


def active_time_labels(dt: Optional[datetime] = None) -> list[str]:
    """List of all narrative labels currently TRUE for given dt.
    Useful for selecting the right label programmatically:
        label = (active_time_labels() or ['unknown'])[0]
    """
    dt = dt or now_utc()
    et = to_et(dt)
    hour = et.hour
    return sorted([lbl for lbl, hours in _TIME_LABELS.items() if hour in hours])


# ── Self-check smoke test ────────────────────────────────────────────

if __name__ == "__main__":
    print("=== time_fmt self-check ===")
    print(f"now_utc:         {now_utc().isoformat()}")
    print(f"fmt_full:        {fmt_full()}")
    print(f"fmt_short:       {fmt_short()}")
    print(f"fmt_iso_utc:     {fmt_iso_utc()}")
    print(f"active labels:   {active_time_labels()}")

    # Known date sanity: 2026-04-25 is a Saturday
    known = datetime(2026, 4, 25, 12, 0, tzinfo=timezone.utc)
    print(f"2026-04-25 12:00Z: {fmt_full(known)}")
    assert "Sat" in fmt_full(known), f"KNOWN WEEKDAY FAILURE: {fmt_full(known)}"

    # Countdown
    target = now_utc() + timedelta(hours=14, minutes=22)
    print(f"countdown +14h22m: {fmt_countdown(target)}")

    # Release-time block
    print("\n" + release_time_description(
        (now_utc() + timedelta(hours=14)).isoformat(),
        release_type="operator_approved",
        subject="Kraken pause",
    ))

    # Label validation
    print(f"\nIs it 'morning' now? {validate_time_label('morning')}")
    print(f"Is it 'overnight' now? {validate_time_label('overnight')}")

    # Validate release_type error path
    try:
        release_time_description("2026-04-25T20:00:00Z", release_type="bogus")
        print("FAIL — should have raised")
    except ValueError as e:
        print(f"\nrelease_type validation OK: {e}")

    print("\n=== self-check passed ===")

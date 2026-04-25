"""
autonomy_guard.py — Safety guards for autonomous parameter tuning.

Every autonomous write (sentinel override, brain override, pair_status
transition) funnels through pre_write_check() BEFORE writing and
record_write() AFTER writing. This gives:

    pre-write:   change budget, oscillation detector, regime gate,
                 attribution lock, expectancy floor, circuit breaker freeze
    post-write:  tuning_outcomes.jsonl entry with hypothesis + expected
                 impact; snapshot_outcomes() fills t+6h / t+24h realized
                 PnL later.

Files owned by this module (under C:/Projects/supervisor/):
    tuning_outcomes.jsonl       — per-write record, backfilled with pnl deltas
    autonomy_frozen_params.json — {bot: {param: {frozen_until_ts, reason}}}
    autonomy_rate_state.json    — rolling counts for change-budget
    autonomy_baseline.json      — weekly operator-anchor snapshots
"""
from __future__ import annotations
import json, os, time, logging
from datetime import datetime, timezone, timedelta
from typing import Any, Tuple

log = logging.getLogger("autonomy_guard")

SUP_DIR             = os.path.dirname(os.path.abspath(__file__))
OUTCOMES_FILE       = os.path.join(SUP_DIR, "tuning_outcomes.jsonl")
FROZEN_FILE         = os.path.join(SUP_DIR, "autonomy_frozen_params.json")
RATE_FILE           = os.path.join(SUP_DIR, "autonomy_rate_state.json")
BASELINE_FILE       = os.path.join(SUP_DIR, "autonomy_baseline.json")

# Rate limits
MAX_WRITES_PER_BOT_PER_HOUR = 6
MAX_CHANGES_PER_PARAM_PER_DAY = 3
OSCILLATION_WINDOW = 5            # last-N changes for flap detection
OSCILLATION_BAND_PCT = 0.02       # net-average within ±2% = flapping
REGIME_STABLE_HOURS = 2.0
ATTRIBUTION_LOCK_HOURS = 24.0
EXPECTANCY_FLOOR_BPS = 10         # minimum expected impact to bother writing

# Circuit breaker thresholds
L1_HURT_STREAK = 2
L1_FREEZE_HOURS = 48
L2_HURT_COUNT_7D = 5
L2_FREEZE_HOURS = 72

# Verdict thresholds (realized_pnl delta over forward window)
VERDICT_HELPED_USD = 5.0
VERDICT_HURT_USD   = -5.0

# Forward-PnL snapshot schedule
SNAPSHOT_T6H_SEC  = 6 * 3600
SNAPSHOT_T24H_SEC = 24 * 3600


# ─── json helpers ──────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _now_ts() -> float:
    return time.time()


def is_alpaca_trading_hours(dt: datetime | None = None) -> bool:
    """Phase A A8: clock-aware helper for stock-market-only checks.

    Returns True iff dt is inside US equity regular session (9:30-16:00 ET,
    Mon-Fri). Currently used by callers that need to distinguish trading-time
    elapsed from wall-clock elapsed when scoring 'no profit in N hours' style
    triggers on Alpaca.

    Approximate ET via fixed offset (EDT Mar-Nov, EST Dec-Feb). Acceptable for
    hour-level gating; not used for sub-minute scheduling.
    """
    dt = dt or datetime.now(timezone.utc)
    month = dt.month
    offset_h = -4 if 3 <= month <= 11 else -5
    et = dt + timedelta(hours=offset_h) if dt.tzinfo else dt
    if et.weekday() >= 5:
        return False
    mod = et.hour * 60 + et.minute
    return 9 * 60 + 30 <= mod < 16 * 60


def alpaca_trading_seconds_between(t_start: float, t_end: float) -> float:
    """Approximate trading-time seconds between two epochs (Alpaca clock).

    For rough "N trading hours elapsed" calculations. Skips weekends in whole-
    day chunks; partial market-hour calculation handled at boundaries. Used
    by triggers that want to avoid counting closed hours in their windows.
    """
    if t_end <= t_start:
        return 0.0
    # Cheap implementation: walk hour by hour, count those that are inside
    # alpaca trading hours. Caller can use this for low-precision windows.
    cursor = t_start
    seconds = 0.0
    while cursor < t_end:
        chunk = min(3600.0, t_end - cursor)
        dt = datetime.fromtimestamp(cursor, timezone.utc)
        if is_alpaca_trading_hours(dt):
            seconds += chunk
        cursor += chunk
    return seconds

def _read_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        log.warning("autonomy_guard: failed to read %s: %s", path, exc)
        return default

def _write_json_atomic(path: str, data: Any) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp, path)


# ─── pre-write guards ──────────────────────────────────────────────

def _is_frozen(bot: str, param: str) -> tuple[bool, str]:
    frozen = _read_json(FROZEN_FILE, {})
    entry = frozen.get(bot, {}).get(param)
    if not entry:
        return False, ""
    until = entry.get("frozen_until_ts", 0)
    if _now_ts() >= until:
        # expired — clean up lazily
        frozen[bot].pop(param, None)
        if not frozen[bot]:
            frozen.pop(bot, None)
        _write_json_atomic(FROZEN_FILE, frozen)
        return False, ""
    remaining_h = (until - _now_ts()) / 3600
    return True, f"param frozen {remaining_h:.1f}h more: {entry.get('reason','')}"

def _is_bot_frozen(bot: str) -> tuple[bool, str]:
    frozen = _read_json(FROZEN_FILE, {})
    entry = frozen.get(bot, {}).get("__ALL__")
    if not entry:
        return False, ""
    until = entry.get("frozen_until_ts", 0)
    if _now_ts() >= until:
        frozen[bot].pop("__ALL__", None)
        if not frozen[bot]:
            frozen.pop(bot, None)
        _write_json_atomic(FROZEN_FILE, frozen)
        return False, ""
    remaining_h = (until - _now_ts()) / 3600
    return True, f"bot autonomy frozen {remaining_h:.1f}h more: {entry.get('reason','')}"

def _change_budget_ok(bot: str, param: str) -> tuple[bool, str]:
    rates = _read_json(RATE_FILE, {})
    bot_rates = rates.get(bot, {"writes": [], "param_writes": {}})
    now = _now_ts()

    # prune old entries
    one_hour_ago = now - 3600
    one_day_ago  = now - 86400
    bot_rates["writes"] = [t for t in bot_rates.get("writes", []) if t > one_hour_ago]
    param_writes = bot_rates.get("param_writes", {})
    param_writes[param] = [t for t in param_writes.get(param, []) if t > one_day_ago]
    bot_rates["param_writes"] = param_writes

    if len(bot_rates["writes"]) >= MAX_WRITES_PER_BOT_PER_HOUR:
        rates[bot] = bot_rates
        _write_json_atomic(RATE_FILE, rates)
        return False, f"rate limit: {MAX_WRITES_PER_BOT_PER_HOUR} writes/hour exceeded"

    if len(param_writes[param]) >= MAX_CHANGES_PER_PARAM_PER_DAY:
        rates[bot] = bot_rates
        _write_json_atomic(RATE_FILE, rates)
        return False, f"param change limit: {MAX_CHANGES_PER_PARAM_PER_DAY}/day exceeded"

    rates[bot] = bot_rates
    _write_json_atomic(RATE_FILE, rates)
    return True, ""

def _oscillation_ok(bot: str, param: str, new_value: float) -> tuple[bool, str]:
    """Look at last N writes for this (bot,param). If the new value is within
    OSCILLATION_BAND_PCT of the mean of the last OSCILLATION_WINDOW, we're flapping."""
    if not os.path.exists(OUTCOMES_FILE):
        return True, ""
    recent = []
    try:
        with open(OUTCOMES_FILE, encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if row.get("bot") == bot and row.get("param") == param:
                    recent.append(row)
    except Exception as exc:
        log.warning("autonomy_guard: oscillation read failed: %s", exc)
        return True, ""

    recent = recent[-OSCILLATION_WINDOW:]
    if len(recent) < OSCILLATION_WINDOW:
        return True, ""

    values = [float(r.get("after", 0)) for r in recent]
    mean = sum(values) / len(values) if values else 0
    if mean == 0:
        return True, ""
    band = abs(mean) * OSCILLATION_BAND_PCT
    if abs(float(new_value) - mean) <= band:
        return False, f"flapping: last {OSCILLATION_WINDOW} writes average {mean:.3f}, new {new_value:.3f} within ±{OSCILLATION_BAND_PCT*100:.0f}%"
    return True, ""

def _regime_stable(bot: str, current_regime: str | None) -> tuple[bool, str]:
    """Check if regime has been stable for REGIME_STABLE_HOURS.
    current_regime must be passed in by caller (who reads it from bot state)."""
    if current_regime is None:
        return True, ""  # caller didn't care
    if not os.path.exists(OUTCOMES_FILE):
        return True, ""
    cutoff = _now_ts() - REGIME_STABLE_HOURS * 3600
    try:
        with open(OUTCOMES_FILE, encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if row.get("bot") != bot:
                    continue
                ts = row.get("ts_epoch", 0)
                if ts < cutoff:
                    continue
                past_regime = row.get("regime_t0")
                if past_regime and past_regime != current_regime:
                    return False, f"regime flipped from {past_regime} to {current_regime} within last {REGIME_STABLE_HOURS}h"
    except Exception as exc:
        log.warning("autonomy_guard: regime check failed: %s", exc)
    return True, ""

def _attribution_clear(bot: str, param: str) -> tuple[bool, str]:
    """Only one param family can be actively tuned per 24h on a bot.
    Exception: sentinel emergency triggers (B1/B2/B4/B6) bypass this."""
    if not os.path.exists(OUTCOMES_FILE):
        return True, ""
    cutoff = _now_ts() - ATTRIBUTION_LOCK_HOURS * 3600
    other_params = set()
    try:
        with open(OUTCOMES_FILE, encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if row.get("bot") != bot:
                    continue
                ts = row.get("ts_epoch", 0)
                if ts < cutoff:
                    continue
                p = row.get("param")
                if p and p != param:
                    other_params.add(p)
    except Exception as exc:
        log.warning("autonomy_guard: attribution check failed: %s", exc)
        return True, ""
    if other_params:
        return False, f"attribution lock: {sorted(other_params)} changed in last {ATTRIBUTION_LOCK_HOURS}h"
    return True, ""

def _expectancy_worthwhile(expected_impact_usd: float, equity_usd: float) -> tuple[bool, str]:
    if equity_usd <= 0:
        return True, ""
    bps = abs(expected_impact_usd) / equity_usd * 10000
    if bps < EXPECTANCY_FLOOR_BPS:
        return False, f"expected impact {bps:.1f}bps < floor {EXPECTANCY_FLOOR_BPS}bps — noise"
    return True, ""


# ─── public API ────────────────────────────────────────────────────

def pre_write_check(
    *,
    bot: str,
    param: str,
    before: float,
    after: float,
    hypothesis: str,
    expected_impact_usd: float,
    equity_usd: float,
    regime: str | None = None,
    trigger: str = "",
    bypass_attribution: bool = False,
) -> tuple[bool, str]:
    """Apply all pre-write guards. Returns (allow, reason_if_denied).

    bypass_attribution=True is for sentinel emergency triggers (B1/B2/B4/B6)
    which may co-change with other adjustments."""
    # hard kill switches first
    for killf in ("OPUS_SENTINEL_PAUSE.txt", "full_mode_lockout.active"):
        if os.path.exists(os.path.join(SUP_DIR, killf)):
            return False, f"kill switch present: {killf}"
    if os.path.exists(r"C:\Projects\memory\.locks\full_mode_lockout.active"):
        return False, "full_mode_lockout.active present"

    ok, why = _is_bot_frozen(bot)
    if ok: return False, why

    ok, why = _is_frozen(bot, param)
    if ok: return False, why

    ok, why = _change_budget_ok(bot, param)
    if not ok: return False, why

    ok, why = _oscillation_ok(bot, param, after)
    if not ok: return False, why

    ok, why = _regime_stable(bot, regime)
    if not ok: return False, why

    if not bypass_attribution:
        ok, why = _attribution_clear(bot, param)
        if not ok: return False, why

    ok, why = _expectancy_worthwhile(expected_impact_usd, equity_usd)
    if not ok: return False, why

    return True, "OK"


def record_write(
    *,
    bot: str,
    param: str,
    before: float,
    after: float,
    hypothesis: str,
    expected_impact_usd: float,
    equity_usd: float,
    regime: str | None = None,
    trigger: str = "",
    realized_pnl_t0: float | None = None,
    ttl_sec: int | None = None,
) -> None:
    """Append an entry to tuning_outcomes.jsonl. Updates rate state."""
    entry = {
        "ts": _now_iso(),
        "ts_epoch": _now_ts(),
        "bot": bot,
        "param": param,
        "before": before,
        "after": after,
        "hypothesis": hypothesis,
        "expected_impact_usd": expected_impact_usd,
        "equity_t0": equity_usd,
        "regime_t0": regime,
        "trigger": trigger,
        "ttl_sec": ttl_sec,
        "realized_pnl_t0": realized_pnl_t0,
        "realized_pnl_t6h": None,
        "realized_pnl_t24h": None,
        "verdict_t6h": None,
        "verdict_t24h": None,
    }
    try:
        with open(OUTCOMES_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as exc:
        log.error("autonomy_guard: could not record_write: %s", exc)
        return

    # update rate state
    rates = _read_json(RATE_FILE, {})
    bot_rates = rates.get(bot, {"writes": [], "param_writes": {}})
    bot_rates["writes"] = bot_rates.get("writes", []) + [_now_ts()]
    param_writes = bot_rates.get("param_writes", {})
    param_writes[param] = param_writes.get(param, []) + [_now_ts()]
    bot_rates["param_writes"] = param_writes
    rates[bot] = bot_rates
    _write_json_atomic(RATE_FILE, rates)


# ─── forward-pnl snapshot job ──────────────────────────────────────

def _verdict(delta_usd: float) -> str:
    if delta_usd >= VERDICT_HELPED_USD: return "HELPED"
    if delta_usd <= VERDICT_HURT_USD:   return "HURT"
    return "NEUTRAL"

def snapshot_outcomes(pnl_readers: dict) -> int:
    """For each row in tuning_outcomes.jsonl with missing t6h/t24h snapshots
    whose age has reached SNAPSHOT_T6H_SEC / SNAPSHOT_T24H_SEC, fill them.

    pnl_readers: {bot_name: callable() -> float}   returns realized_pnl_usd.

    Returns count of rows updated.
    """
    if not os.path.exists(OUTCOMES_FILE):
        return 0
    updated = 0
    now = _now_ts()
    rows = []
    try:
        with open(OUTCOMES_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    rows.append(None)  # preserve shape
    except Exception as exc:
        log.warning("autonomy_guard.snapshot: read failed: %s", exc)
        return 0

    dirty = False
    for row in rows:
        if not row: continue
        bot = row.get("bot")
        ts0 = row.get("ts_epoch", 0)
        if not bot or not ts0: continue
        reader = pnl_readers.get(bot)
        if not reader: continue
        age = now - ts0
        t0 = row.get("realized_pnl_t0")
        # t+6h
        if age >= SNAPSHOT_T6H_SEC and row.get("realized_pnl_t6h") is None:
            try:
                pnl_now = reader()
                row["realized_pnl_t6h"] = pnl_now
                if t0 is not None:
                    row["verdict_t6h"] = _verdict(pnl_now - t0)
                dirty = True; updated += 1
            except Exception as exc:
                log.warning("autonomy_guard.snapshot: reader(%s) failed: %s", bot, exc)
        # t+24h
        if age >= SNAPSHOT_T24H_SEC and row.get("realized_pnl_t24h") is None:
            try:
                pnl_now = reader()
                row["realized_pnl_t24h"] = pnl_now
                if t0 is not None:
                    row["verdict_t24h"] = _verdict(pnl_now - t0)
                dirty = True; updated += 1
            except Exception as exc:
                log.warning("autonomy_guard.snapshot: reader(%s) failed: %s", bot, exc)

    if dirty:
        tmp = OUTCOMES_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for row in rows:
                if row is None: continue
                f.write(json.dumps(row) + "\n")
        os.replace(tmp, OUTCOMES_FILE)
        _evaluate_circuit_breakers()

    return updated


# ─── circuit breakers ──────────────────────────────────────────────

def _freeze_param(bot: str, param: str, hours: float, reason: str) -> None:
    frozen = _read_json(FROZEN_FILE, {})
    frozen.setdefault(bot, {})[param] = {
        "frozen_until_ts": _now_ts() + hours * 3600,
        "reason": reason,
        "frozen_at": _now_iso(),
    }
    _write_json_atomic(FROZEN_FILE, frozen)
    log.warning("autonomy_guard: FROZE %s/%s for %.1fh: %s", bot, param, hours, reason)

def _freeze_bot(bot: str, hours: float, reason: str) -> None:
    frozen = _read_json(FROZEN_FILE, {})
    frozen.setdefault(bot, {})["__ALL__"] = {
        "frozen_until_ts": _now_ts() + hours * 3600,
        "reason": reason,
        "frozen_at": _now_iso(),
    }
    _write_json_atomic(FROZEN_FILE, frozen)
    log.warning("autonomy_guard: FROZE bot=%s for %.1fh: %s", bot, hours, reason)

def _evaluate_circuit_breakers() -> None:
    """Walk tuning_outcomes.jsonl. Apply L1 (2-HURT-streak per param)
    and L2 (5-HURT-in-7d per bot) freezes."""
    if not os.path.exists(OUTCOMES_FILE):
        return
    rows = []
    try:
        with open(OUTCOMES_FILE, encoding="utf-8") as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return

    # L1: 2 HURT streak on same (bot, param) within last 7d (ignore PENDING)
    now = _now_ts()
    cutoff_7d = now - 7 * 86400
    by_pair: dict[tuple[str,str], list[dict]] = {}
    for r in rows:
        if r.get("ts_epoch", 0) < cutoff_7d: continue
        bot = r.get("bot"); param = r.get("param")
        if not bot or not param: continue
        by_pair.setdefault((bot, param), []).append(r)

    for (bot, param), lst in by_pair.items():
        # use verdict_t6h if filled, else t24h — skip still-pending
        verdicts = []
        for r in lst:
            v = r.get("verdict_t6h") or r.get("verdict_t24h")
            if v: verdicts.append(v)
        if len(verdicts) >= L1_HURT_STREAK and all(v == "HURT" for v in verdicts[-L1_HURT_STREAK:]):
            frozen = _read_json(FROZEN_FILE, {})
            if param in frozen.get(bot, {}):
                continue  # already frozen
            _freeze_param(bot, param, L1_FREEZE_HOURS, f"L1: {L1_HURT_STREAK} consecutive HURT verdicts")

    # L2: >=5 HURT across any params on same bot within 7d
    by_bot: dict[str, list[str]] = {}
    for r in rows:
        if r.get("ts_epoch", 0) < cutoff_7d: continue
        bot = r.get("bot")
        if not bot: continue
        v = r.get("verdict_t6h") or r.get("verdict_t24h")
        if v: by_bot.setdefault(bot, []).append(v)

    for bot, verdicts in by_bot.items():
        hurts = sum(1 for v in verdicts if v == "HURT")
        if hurts >= L2_HURT_COUNT_7D:
            frozen = _read_json(FROZEN_FILE, {})
            if "__ALL__" in frozen.get(bot, {}):
                continue
            _freeze_bot(bot, L2_FREEZE_HOURS, f"L2: {hurts} HURT verdicts in last 7d")


# ─── reporting helpers (for opus_review.py) ────────────────────────

def autonomy_summary(hours: float = 12.0) -> dict:
    """Build a dict summary of autonomous activity in the last N hours."""
    summary = {
        "window_hours": hours,
        "total_writes": 0,
        "by_bot": {},
        "verdicts": {"HELPED": 0, "NEUTRAL": 0, "HURT": 0, "PENDING": 0},
        "frozen": _read_json(FROZEN_FILE, {}),
    }
    if not os.path.exists(OUTCOMES_FILE):
        return summary
    cutoff = _now_ts() - hours * 3600
    try:
        with open(OUTCOMES_FILE, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("ts_epoch", 0) < cutoff: continue
                summary["total_writes"] += 1
                bot = r.get("bot", "?")
                b = summary["by_bot"].setdefault(bot, {"writes": 0, "params": {}})
                b["writes"] += 1
                p = r.get("param", "?")
                b["params"][p] = b["params"].get(p, 0) + 1
                v = r.get("verdict_t6h") or r.get("verdict_t24h") or "PENDING"
                summary["verdicts"][v] = summary["verdicts"].get(v, 0) + 1
    except Exception:
        pass
    return summary


if __name__ == "__main__":
    import pprint
    pprint.pprint(autonomy_summary(12))

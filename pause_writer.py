"""
pause_writer.py — single-source pause coordination for Kraken/enzobot.

ALL pauses (sentinel B12/B6, operator directive, opus 2h watch, future
autonomous triggers) write through this module. Eliminates the class of
bugs where:
  - Autonomous trigger overwrites operator's explicit pause
  - Same trigger files duplicate "new" pause incidents
  - TTLs fight (a 2h trigger replacing a 24h operator pause)
  - Audit trail fragments across multiple files

Coordination rules:

  1. OPERATOR_DIRECTIVE IS SACROSANCT
     If existing override has source='operator_directive' AND not expired,
     autonomous writers REFUSE to overwrite. Logged + appended to pause_history
     as 'autonomous_blocked_by_operator'.

  2. SAME-TRIGGER EXTEND
     If existing override has same trigger as the new write, extend the TTL
     (keep latest blocked_pairs and changes), increment extension_count. No
     new "incident" — same incident, longer life.

  3. DIFFERENT-TRIGGER MERGE
     If existing override has a DIFFERENT trigger from the new write
     (autonomous), MERGE: union blocked_pairs, take stricter values per
     change key (lower TARGET_DEPLOY, higher MIN_SCORE_TO_TRADE, lower
     SCORE_DROP_EXIT). New TTL = max(existing, proposed).

  4. EXPIRED OVERRIDE = SAFE TO OVERWRITE
     Existing override with ttl_expiry < now is treated as no override.

  5. AUDIT IN ONE FILE
     pause_history.jsonl receives one row per call, including refused writes.
     Operator-readable.

File path: enzobot/sentinel_override.json (the canonical pause file).
History:   supervisor/pause_history.jsonl
"""
from __future__ import annotations
import json
import os
import logging
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger("pause_writer")

ENZOBOT_DIR = r"C:\Projects\enzobot"
SUPERVISOR_DIR = r"C:\Projects\supervisor"

PAUSE_FILE   = os.path.join(ENZOBOT_DIR, "sentinel_override.json")
HISTORY_FILE = os.path.join(SUPERVISOR_DIR, "pause_history.jsonl")

# Source tag conventions:
SOURCE_OPERATOR = "operator_directive"  # sacred — only operator/Opus-on-direct-direction
SOURCE_OPUS_WATCH = "opus_2h_watch"     # Opus's 2h cron audit
SOURCE_OPUS_SENTINEL = "opus_sentinel"  # autonomous B-trigger fires
SOURCE_BRAIN = "supervisor_brain"       # brain rule-engine

# Stricter-direction map for merge: which way is "more conservative" per param
_STRICTER_HIGHER = {"MIN_SCORE_TO_TRADE", "MIN_HOLD_SEC", "SCORE_DROP_EXIT"}
# These params: stricter = lower (less deployment, faster exit)
_STRICTER_LOWER  = {"TARGET_DEPLOY_PCT", "MAX_OPEN_POSITIONS", "TIME_STOP_SEC",
                    "ROTATE_MIN_PNL_PCT"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def _read_existing_pause() -> Optional[dict]:
    if not os.path.exists(PAUSE_FILE):
        return None
    try:
        with open(PAUSE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        log.warning("pause_writer: existing pause read failed: %s", exc)
        return None


def _is_expired(pause: dict) -> bool:
    ttl = pause.get("ttl_expiry", "")
    try:
        if ttl.endswith("Z"):
            ttl = ttl.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ttl)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp() < _now_ts()
    except Exception:
        return True  # malformed → treat as expired (safe to overwrite)


def _stricter(key: str, a, b):
    """Return the stricter of two values for a given param key."""
    try:
        a_f, b_f = float(a), float(b)
    except (TypeError, ValueError):
        return a if a is not None else b
    if key in _STRICTER_HIGHER:
        return a_f if a_f >= b_f else b_f
    if key in _STRICTER_LOWER:
        return a_f if a_f <= b_f else b_f
    # Unknown key — prefer existing
    return a_f


def _audit(record: dict) -> None:
    record.setdefault("ts", _now_iso())
    try:
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as exc:
        log.warning("pause_writer: audit append failed: %s", exc)


def write_pause(*,
                source: str,
                trigger: str,
                ttl_sec: int,
                changes: Optional[dict] = None,
                blocked_pairs: Optional[list] = None,
                reason: str = "") -> dict:
    """Coordinated pause write. Returns dict describing outcome.

    outcome.action ∈ {
        'created'              — no prior, fresh write
        'extended_same_trigger' — same trigger fired again, TTL extended
        'merged_different_trigger' — different trigger, merged conservatively
        'blocked_by_operator'  — refused to overwrite operator pause
        'replaced_expired'     — prior pause expired, new one took over
    }
    """
    changes = changes or {}
    blocked_pairs = sorted(set(blocked_pairs or []))
    new_ttl_dt = datetime.fromtimestamp(_now_ts() + ttl_sec, timezone.utc)
    new_ttl_iso = new_ttl_dt.isoformat()

    existing = _read_existing_pause()
    audit_base = {
        "ts": _now_iso(),
        "writer_source": source,
        "writer_trigger": trigger,
        "writer_ttl_sec": ttl_sec,
        "writer_reason": reason[:200],
        "writer_changes": changes,
        "writer_blocked_count": len(blocked_pairs),
    }

    # Rule 1: operator override is sacred
    if (existing
        and existing.get("source") == SOURCE_OPERATOR
        and not _is_expired(existing)):
        if source != SOURCE_OPERATOR:
            outcome = {
                "action": "blocked_by_operator",
                "existing_source": existing.get("source"),
                "existing_trigger": existing.get("trigger"),
                "existing_ttl_expiry": existing.get("ttl_expiry"),
            }
            _audit({**audit_base, **outcome})
            log.warning(
                "pause_writer: REFUSED autonomous write (source=%s trigger=%s) — "
                "operator pause active until %s",
                source, trigger, existing.get("ttl_expiry"))
            return outcome
        # operator overwriting their own pause is fine — fall through

    # Rule 4: expired existing → safe overwrite
    if existing and _is_expired(existing):
        _audit({**audit_base, "action": "replaced_expired",
                "expired_trigger": existing.get("trigger")})
        return _do_write(source, trigger, ttl_sec, new_ttl_iso, changes,
                         blocked_pairs, reason, action="replaced_expired",
                         extension_count=1)

    # Rule 2: same trigger → extend
    if existing and existing.get("trigger") == trigger:
        prior_ext = int(existing.get("extension_count", 1))
        # TTL: take the LATER of existing and new
        existing_ttl_str = existing.get("ttl_expiry", "")
        try:
            ex_ttl_dt = datetime.fromisoformat(existing_ttl_str.replace("Z","+00:00"))
            if ex_ttl_dt.tzinfo is None:
                ex_ttl_dt = ex_ttl_dt.replace(tzinfo=timezone.utc)
        except Exception:
            ex_ttl_dt = new_ttl_dt
        kept_ttl_dt = max(ex_ttl_dt, new_ttl_dt)
        # blocked_pairs union, changes — new wins (latest tuning)
        merged_blocked = sorted(set(existing.get("blocked_pairs", [])) | set(blocked_pairs))
        merged_changes = {**(existing.get("changes", {})), **changes}
        outcome = _do_write(source, trigger, ttl_sec, kept_ttl_dt.isoformat(),
                            merged_changes, merged_blocked, reason,
                            action="extended_same_trigger",
                            extension_count=prior_ext + 1,
                            first_fire_ts=existing.get("first_fire_ts", _now_iso()))
        _audit({**audit_base, **outcome})
        return outcome

    # Rule 3: different trigger from autonomous source → merge conservatively
    if existing and source != SOURCE_OPERATOR:
        ex_changes = existing.get("changes", {})
        merged_changes = {**ex_changes}
        for k, v in changes.items():
            if k in merged_changes:
                merged_changes[k] = _stricter(k, merged_changes[k], v)
            else:
                merged_changes[k] = v
        merged_blocked = sorted(set(existing.get("blocked_pairs", [])) | set(blocked_pairs))
        existing_ttl_str = existing.get("ttl_expiry", "")
        try:
            ex_ttl_dt = datetime.fromisoformat(existing_ttl_str.replace("Z","+00:00"))
            if ex_ttl_dt.tzinfo is None:
                ex_ttl_dt = ex_ttl_dt.replace(tzinfo=timezone.utc)
        except Exception:
            ex_ttl_dt = new_ttl_dt
        kept_ttl_dt = max(ex_ttl_dt, new_ttl_dt)
        # New trigger key for tracking — concatenate
        merged_trigger = f"{existing.get('trigger','?')}+{trigger}"
        outcome = _do_write(source, merged_trigger, ttl_sec,
                            kept_ttl_dt.isoformat(),
                            merged_changes, merged_blocked, reason,
                            action="merged_different_trigger",
                            extension_count=1)
        _audit({**audit_base, **outcome,
                "merged_with_trigger": existing.get('trigger')})
        return outcome

    # Operator directive over expired/none/operator → fresh write
    return _do_write(source, trigger, ttl_sec, new_ttl_iso, changes,
                     blocked_pairs, reason, action="created",
                     extension_count=1)


def _do_write(source, trigger, ttl_sec, ttl_iso, changes, blocked_pairs,
              reason, *, action, extension_count, first_fire_ts=None) -> dict:
    """Atomic pause file write."""
    now_iso = _now_iso()
    payload = {
        "ts": now_iso,
        "ttl_expiry": ttl_iso,
        "source": source,
        "trigger": trigger,
        "first_fire_ts": first_fire_ts or now_iso,
        "extension_count": extension_count,
        "changes": changes,
        "blocked_pairs": blocked_pairs,
        "reason": reason,
    }
    try:
        tmp = PAUSE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, default=str)
        os.replace(tmp, PAUSE_FILE)
    except Exception as exc:
        log.error("pause_writer: file write failed: %s", exc)
        return {"action": "write_failed", "error": str(exc)}
    log.warning("pause_writer: %s — source=%s trigger=%s ttl_until=%s blocked=%d ext=%d",
                action, source, trigger, ttl_iso, len(blocked_pairs), extension_count)
    return {
        "action": action,
        "source": source,
        "trigger": trigger,
        "ttl_expiry": ttl_iso,
        "blocked_pairs_count": len(blocked_pairs),
        "extension_count": extension_count,
        "first_fire_ts": payload["first_fire_ts"],
    }


def status() -> dict:
    """Return current pause status — for cron / brief consumers."""
    p = _read_existing_pause()
    if not p:
        return {"active": False}
    return {
        "active": not _is_expired(p),
        "source": p.get("source"),
        "trigger": p.get("trigger"),
        "ttl_expiry": p.get("ttl_expiry"),
        "first_fire_ts": p.get("first_fire_ts"),
        "extension_count": p.get("extension_count", 1),
        "blocked_pairs_count": len(p.get("blocked_pairs", [])),
        "changes": p.get("changes", {}),
    }


# ── CLI / smoke test ─────────────────────────────────────────────────

if __name__ == "__main__":
    import json as _j
    print("=== current pause status ===")
    print(_j.dumps(status(), indent=2))

"""
autonomy_schedule.py — Persistent upgrade schedule reader/updater.

Source of truth: autonomy_schedule.json in this directory.
Consumers: opus_review.py (packet rendering), Opus (status updates).

Update operations always append to the upgrade's history[] for audit trail.
"""
from __future__ import annotations
import json, os, logging
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger("autonomy_schedule")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCHEDULE_FILE = os.path.join(BASE_DIR, "autonomy_schedule.json")
MARKDOWN_FILE = os.path.join(BASE_DIR, "UPGRADE_SCHEDULE.md")

STATUS_ORDER = [
    "approved", "in_progress", "built_awaiting_restart", "live",
    "pending_approval", "validated", "reverted", "deferred",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load() -> dict:
    if not os.path.exists(SCHEDULE_FILE):
        return {"_meta": {}, "upgrades": []}
    try:
        with open(SCHEDULE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        log.warning("schedule load failed: %s", exc)
        return {"_meta": {}, "upgrades": []}


def save(data: dict) -> None:
    data["_meta"]["last_update"] = _now_iso()
    tmp = SCHEDULE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp, SCHEDULE_FILE)


def update_status(upgrade_id: str, new_status: str, note: str = "",
                  by: str = "Opus") -> bool:
    """Transition an upgrade to new_status; append history entry."""
    data = load()
    for up in data.get("upgrades", []):
        if up.get("id") == upgrade_id:
            old_status = up.get("status")
            up["status"] = new_status
            up.setdefault("history", []).append({
                "ts": _now_iso(),
                "event": f"status_change:{old_status}->{new_status}",
                "by": by,
                "note": note,
            })
            save(data)
            log.info("schedule: %s %s -> %s", upgrade_id, old_status, new_status)
            return True
    log.warning("schedule: upgrade_id=%s not found", upgrade_id)
    return False


def add_history(upgrade_id: str, event: str, note: str = "",
                by: str = "Opus") -> bool:
    data = load()
    for up in data.get("upgrades", []):
        if up.get("id") == upgrade_id:
            up.setdefault("history", []).append({
                "ts": _now_iso(),
                "event": event,
                "by": by,
                "note": note,
            })
            save(data)
            return True
    return False


def next_up() -> Optional[dict]:
    """Return the highest-priority upgrade whose dependencies are all
    validated or live, and whose status is pending_approval or approved."""
    data = load()
    upgrades = data.get("upgrades", [])
    validated_or_live = {
        up.get("id") for up in upgrades
        if up.get("status") in ("validated", "live")
    }
    candidates = []
    for up in upgrades:
        if up.get("status") not in ("pending_approval", "approved"):
            continue
        deps = set(up.get("depends_on", []) or [])
        if deps - validated_or_live:
            continue  # unmet deps
        candidates.append(up)
    if not candidates:
        return None
    candidates.sort(key=lambda u: u.get("priority", 99))
    return candidates[0]


def _sort_key(up: dict) -> tuple:
    status = up.get("status", "deferred")
    try:
        status_idx = STATUS_ORDER.index(status)
    except ValueError:
        status_idx = 99
    return (status_idx, up.get("priority", 99))


def render_markdown() -> str:
    """Human-readable full schedule. Written to UPGRADE_SCHEDULE.md."""
    data = load()
    meta = data.get("_meta", {})
    upgrades = sorted(data.get("upgrades", []), key=_sort_key)

    lines = [
        "# Upgrade Schedule",
        "",
        f"_Last update: {meta.get('last_update','unknown')}_",
        "",
        "Source of truth: `autonomy_schedule.json`. Updated by Opus on ship/revert, "
        "surfaced in 08:00 AM / 08:00 PM operator packets.",
        "",
    ]

    by_status: dict[str, list] = {}
    for up in upgrades:
        by_status.setdefault(up.get("status", "deferred"), []).append(up)

    display_groups = [
        ("in_progress", "🔨 In progress"),
        ("approved", "✅ Approved (awaiting build)"),
        ("built_awaiting_restart", "⏳ Built (awaiting restart)"),
        ("live", "🟢 Live (measuring outcomes)"),
        ("validated", "📊 Validated"),
        ("pending_approval", "⏸ Pending approval"),
        ("deferred", "🗂 Deferred"),
        ("reverted", "❌ Reverted"),
    ]

    for status_key, label in display_groups:
        items = by_status.get(status_key, [])
        if not items:
            continue
        lines.append(f"## {label}")
        lines.append("")
        for up in items:
            protection = up.get("expected_protection_usd_per_week", [0, 0])
            pnl_impr = up.get("expected_pnl_improvement_usd_per_week", [0, 0])
            lines.append(f"### {up.get('id')} · {up.get('title')} (priority {up.get('priority')})")
            lines.append("")
            lines.append(f"- **Gate:** {up.get('gate','—')}")
            lines.append(f"- **Target window:** {up.get('target_window','—')}")
            lines.append(f"- **Est build time:** {up.get('est_build_time','—')}")
            if protection != [0, 0]:
                lines.append(f"- **Expected protection:** ~${protection[0]}-{protection[1]}/week")
            if pnl_impr != [0, 0]:
                lines.append(f"- **Expected PnL lift:** ~${pnl_impr[0]}-{pnl_impr[1]}/week")
            lines.append(f"- **Exit condition:** {up.get('exit_condition','—')}")
            lines.append(f"- **Files:** {', '.join(up.get('files_touched', []) or ['—'])}")
            deps = up.get("depends_on", [])
            if deps:
                lines.append(f"- **Depends on:** {', '.join(deps)}")
            if up.get("mechanism"):
                lines.append(f"- **Mechanism:** {up['mechanism']}")
            lines.append("")
        lines.append("")

    nxt = next_up()
    lines.append("---")
    lines.append("")
    if nxt:
        lines.append(f"**Next up:** `{nxt.get('id')}` — {nxt.get('title')}")
    else:
        lines.append("_No upgrades unblocked for next action._")

    return "\n".join(lines)


def write_markdown() -> str:
    md = render_markdown()
    tmp = MARKDOWN_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(md)
    os.replace(tmp, MARKDOWN_FILE)
    return MARKDOWN_FILE


def packet_section() -> str:
    """Compact packet-format section (for opus_review.py). Shorter than MD."""
    data = load()
    upgrades = sorted(data.get("upgrades", []), key=_sort_key)
    active = [u for u in upgrades if u.get("status") in (
        "in_progress", "approved", "built_awaiting_restart", "live", "pending_approval"
    )]

    lines = ["## Upgrade schedule", ""]
    if not active:
        lines.append("_No upgrades in active track. All items validated, deferred, or reverted._")
        return "\n".join(lines)

    lines.append("| ID | Title | Status | Gate / next action |")
    lines.append("|---|---|---|---|")
    for up in active:
        iid = up.get("id","")
        title = up.get("title","")
        status = up.get("status","")
        gate = up.get("gate","") or up.get("target_window","")
        # truncate gate for table
        if len(gate) > 55:
            gate = gate[:52] + "..."
        lines.append(f"| {iid} | {title} | {status} | {gate} |")

    nxt = next_up()
    if nxt:
        lines.append("")
        lines.append(f"**Next up:** `{nxt.get('id')}` — {nxt.get('title')} "
                     f"(target {nxt.get('target_window','—')})")

    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "md":
        path = write_markdown()
        print(f"wrote {path}")
    elif len(sys.argv) > 1 and sys.argv[1] == "next":
        nxt = next_up()
        if nxt:
            print(f"{nxt['id']}: {nxt['title']} (priority {nxt['priority']})")
        else:
            print("no upgrades unblocked")
    else:
        print(packet_section())

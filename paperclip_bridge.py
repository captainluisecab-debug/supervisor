"""
paperclip_bridge.py — Automated Paperclip integration bridge.

Runs every supervisor cycle (called from supervisor.py). Reads runtime state,
creates/updates Paperclip issues for anomalies, violations, and events.
NEVER writes to bot files or command files. Only writes to Paperclip API.

This is the operational spine that makes Paperclip a live loop-closure system.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone

log = logging.getLogger("paperclip_bridge")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BRIDGE_STATE_FILE = os.path.join(BASE_DIR, "paperclip_bridge_state.json")
ESCALATION_ARCHIVE = os.path.join(BASE_DIR, "escalation_archive.jsonl")

# Paperclip API
API_BASE = "http://127.0.0.1:3100/api"
COMPANY_ID = "f1f333d3-ad5b-48a9-8d7f-c600761d9aae"

# Agent IDs
AGENTS = {
    "luis": "78e06d06-07b8-45c5-8ab6-1ab35e723488",
    "opus": "ac91fe14-83c3-4e53-97d4-00b14d71cdd2",
    "hermes": "f5f2e179-ab74-4bdd-b421-89585c9870cf",
    "supervisor": "bf5f6c80-176f-4801-a908-a394d7501aca",
    "paperclip": "34193093-ecf0-456e-86e5-2e75a22c81cb",
    "kernel": "1710b68b-e4a5-458c-be9b-02c03038810e",
    "botops": "4176fae8-0375-434a-8a53-4f6f522eee5e",
}

# Project ID
PROJECT_ID = "304d91af-d5fc-48ab-8873-a3f8806add4f"


def _api_post(path: str, data: dict) -> dict:
    """POST to Paperclip API. Returns response dict or empty on failure."""
    try:
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            f"{API_BASE}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        log.debug("[PAPERCLIP] API error: %s", exc)
        return {}


def _api_patch(path: str, data: dict) -> dict:
    """PATCH to Paperclip API."""
    try:
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            f"{API_BASE}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="PATCH",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        log.debug("[PAPERCLIP] API error: %s", exc)
        return {}


def _api_get(path: str) -> dict | list:
    """GET from Paperclip API."""
    try:
        req = urllib.request.Request(f"{API_BASE}{path}", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return {}


def _read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _read_jsonl_tail(path: str, n: int) -> list:
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        return [json.loads(l) for l in lines[-n:] if l.strip()]
    except Exception:
        return []


def _load_bridge_state() -> dict:
    try:
        with open(BRIDGE_STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"tracked_issues": {}, "last_cycle": 0}


def _save_bridge_state(state: dict):
    try:
        with open(BRIDGE_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


def _create_issue(title: str, description: str, priority: str,
                  assignee_key: str, tag: str) -> str | None:
    """Create a Paperclip issue. Returns issue ID or None."""
    result = _api_post(f"/companies/{COMPANY_ID}/issues", {
        "title": title,
        "description": description,
        "status": "todo",
        "priority": priority,
        "projectId": PROJECT_ID,
        "assigneeAgentId": AGENTS.get(assignee_key, AGENTS["supervisor"]),
    })
    issue_id = result.get("id")
    if issue_id:
        log.info("[PAPERCLIP] Created issue: %s — %s", result.get("identifier", "?"), title)
    return issue_id


def _close_issue(issue_id: str, reason: str):
    """Close a Paperclip issue with a comment."""
    _api_post(f"/issues/{issue_id}/comments", {"body": f"AUTO-CLOSED: {reason}"})
    _api_patch(f"/issues/{issue_id}", {"status": "done"})
    log.info("[PAPERCLIP] Closed issue %s: %s", issue_id, reason)


def _comment_issue(issue_id: str, body: str):
    """Add a comment to an existing issue."""
    _api_post(f"/issues/{issue_id}/comments", {"body": body})


def run_bridge(cycle: int):
    """Main bridge function. Called once per supervisor cycle."""
    state = _load_bridge_state()
    tracked = state.get("tracked_issues", {})
    now_iso = datetime.now(timezone.utc).isoformat()

    # ── Read current system state ────────────────────────────────
    hermes = _read_json(os.path.join(BASE_DIR, "hermes_context.json"))
    kernel_entries = _read_jsonl_tail(os.path.join(BASE_DIR, "kernel_audit.jsonl"), 5)
    gov_decisions = _read_jsonl_tail(os.path.join(BASE_DIR, "governor_decisions.jsonl"), 10)
    escalations = _read_jsonl_tail(os.path.join(BASE_DIR, "hermes_escalations.jsonl"), 10)

    kraken = hermes.get("kraken", {})
    sfm = hermes.get("sfm", {})
    alpaca = hermes.get("alpaca", {})

    # ── Check 1: Kernel HALT → issue for Kernel agent ────────────
    kernel_tag = "kernel_halt"
    last_kernel = kernel_entries[-1] if kernel_entries else {}
    if last_kernel.get("status") == "HALT":
        if kernel_tag not in tracked:
            violations = last_kernel.get("violations", [])
            iid = _create_issue(
                f"Kernel HALT: {violations[0][:60] if violations else 'unknown'}",
                f"Kernel halted at cycle {last_kernel.get('cycle')}.\n\nViolations:\n" +
                "\n".join(f"- {v}" for v in violations),
                "critical",
                "kernel",
                kernel_tag,
            )
            if iid:
                tracked[kernel_tag] = {"id": iid, "opened_at": now_iso}
    elif kernel_tag in tracked:
        _close_issue(tracked[kernel_tag]["id"], "Kernel PASS resumed — violation cleared")
        del tracked[kernel_tag]

    # ── Check 2: Sleeve DD critical (< -10%) → issue for Supervisor ──
    for sleeve_name, sleeve_data in [("kraken", kraken), ("sfm", sfm), ("alpaca", alpaca)]:
        dd = sleeve_data.get("dd_pct", 0)
        tag = f"dd_critical_{sleeve_name}"
        if dd < -10:
            if tag not in tracked:
                iid = _create_issue(
                    f"{sleeve_name.upper()} DD critical: {dd:.1f}%",
                    f"{sleeve_name.upper()} drawdown at {dd:.1f}%, below -10% threshold.\n"
                    f"Equity: ${sleeve_data.get('equity', 0):.2f}",
                    "critical",
                    "supervisor",
                    tag,
                )
                if iid:
                    tracked[tag] = {"id": iid, "opened_at": now_iso}
        elif tag in tracked:
            _close_issue(tracked[tag]["id"], f"{sleeve_name.upper()} DD recovered to {dd:.1f}%")
            del tracked[tag]

    # ── Check 3: Hermes escalations → issue for Opus ─────────────
    # Track last-archived timestamp to avoid re-archiving same entries every cycle
    _last_archived_ts = tracked.get("_esc_archive_cursor", {}).get("ts", "")
    _new_max_ts = _last_archived_ts
    for esc in escalations:
        esc_ts = esc.get("ts", "")
        if esc_ts and esc_ts <= _last_archived_ts:
            continue  # Already archived in a prior cycle
        esc_type = esc.get("type", "unknown")
        tag = f"hermes_esc_{esc_type}"
        # Archive permanently before creating issue
        try:
            with open(ESCALATION_ARCHIVE, "a", encoding="utf-8") as _af:
                _af.write(json.dumps({**esc, "paperclip_tag": tag, "cycle": cycle}) + "\n")
        except Exception:
            pass
        if esc_ts and esc_ts > _new_max_ts:
            _new_max_ts = esc_ts
        if tag not in tracked:
            iid = _create_issue(
                f"Hermes escalation: {esc.get('detail', esc_type)[:60]}",
                f"Severity: {esc.get('severity', '?')}\n"
                f"Type: {esc_type}\n"
                f"Detail: {esc.get('detail', '')}\n"
                f"Detected: {esc.get('ts', '?')}",
                "high",
                "opus",
                tag,
            )
            if iid:
                tracked[tag] = {"id": iid, "opened_at": now_iso}
    # Persist archive cursor to avoid re-archiving on next cycle
    if _new_max_ts != _last_archived_ts:
        tracked["_esc_archive_cursor"] = {"ts": _new_max_ts}

    # ── Check 4: Regime change → informational issue for Hermes ──
    regime_tag = "regime_current"
    current_regime = hermes.get("regime", {}).get("label", "?")
    if regime_tag in tracked:
        prev_regime = tracked[regime_tag].get("regime")
        if prev_regime and prev_regime != current_regime:
            # Close old, open new
            _close_issue(tracked[regime_tag]["id"],
                         f"Regime changed: {prev_regime} -> {current_regime}")
            del tracked[regime_tag]

    if regime_tag not in tracked:
        # Get dominant regime from governor
        truth = _read_json(os.path.join(BASE_DIR, "kraken_state_truth.json"))
        gov_regime = truth.get("regime", {}).get("dominant", "?")
        iid = _create_issue(
            f"Regime: {gov_regime} (Hermes: {current_regime})",
            f"Governor regime: {gov_regime}\nHermes regime: {current_regime}\n"
            f"All sleeves should be classified accordingly.",
            "medium",
            "hermes",
            regime_tag,
        )
        if iid:
            tracked[regime_tag] = {"id": iid, "opened_at": now_iso, "regime": current_regime}

    # ── Check 5: Classification summary → update BotOps ──────────
    cls_counts = {}
    for d in gov_decisions:
        cls = d.get("classification", "")
        if cls:
            cls_counts[cls] = cls_counts.get(cls, 0) + 1
    botops_tag = "classification_summary"
    if cls_counts and botops_tag in tracked:
        _comment_issue(tracked[botops_tag]["id"],
                       f"Cycle {cycle}: classifications = {json.dumps(cls_counts)}")
    elif cls_counts and botops_tag not in tracked:
        iid = _create_issue(
            "Governor classification tracking",
            "Tracking 6-level classifications (ALLOW/DELAY/REDUCE/OVERRIDE/BLOCK/ESCALATE) "
            "across all sleeves. Updated each cycle.",
            "low",
            "botops",
            botops_tag,
        )
        if iid:
            tracked[botops_tag] = {"id": iid, "opened_at": now_iso}
            _comment_issue(iid, f"Cycle {cycle}: classifications = {json.dumps(cls_counts)}")

    # ── Check 6: Authority violations → issue for Supervisor ─────
    exec_truth = hermes.get("execution_truth", {})
    violations = exec_truth.get("authority_violations", [])
    auth_tag = "authority_violation_active"
    if violations:
        if auth_tag not in tracked:
            detail = "\n".join(
                f"- {v.get('ts','?')[:19]} {v.get('symbol','?')} BUY ${v.get('size_usd',0):.2f} while entry_allowed=false"
                for v in violations[:5]
            )
            iid = _create_issue(
                f"AUTHORITY VIOLATION: {len(violations)} BUY(s) while entry blocked",
                f"Execution truth shows BUY fills while Governor had entry_allowed=false.\n\n{detail}",
                "critical",
                "supervisor",
                auth_tag,
            )
            if iid:
                tracked[auth_tag] = {"id": iid, "opened_at": now_iso, "count": len(violations)}
        else:
            # Append new evidence to existing issue
            prev_count = tracked[auth_tag].get("count", 0)
            if len(violations) > prev_count:
                _comment_issue(tracked[auth_tag]["id"],
                               f"Cycle {cycle}: {len(violations)} violations detected (was {prev_count})")
                tracked[auth_tag]["count"] = len(violations)
    elif auth_tag in tracked:
        _close_issue(tracked[auth_tag]["id"], "Zero authority violations — execution matches command intent")
        del tracked[auth_tag]

    # ── Check 7: Churn detection (time-window based) → issue for Opus ──
    recon = exec_truth.get("reconciliation_summary", {})
    churn_windows = recon.get("churn_windows", {})
    churn_tag = "churn_detected"
    # Use 6h window as primary churn signal
    w6h = churn_windows.get("6h", {})
    ff_6h = w6h.get("force_flattens", 0)
    loops_6h = w6h.get("repeated_entry_loops", 0)
    drain_6h = w6h.get("churn_pnl_drain", 0)
    if loops_6h >= 3 or ff_6h >= 3:
        w1h = churn_windows.get("1h", {})
        w24h = churn_windows.get("24h", {})
        detail = (f"Time-window churn:\n"
                  f"  1h:  buys={w1h.get('buys',0)} ff={w1h.get('force_flattens',0)} loops={w1h.get('repeated_entry_loops',0)} drain=${w1h.get('churn_pnl_drain',0):.2f}\n"
                  f"  6h:  buys={w6h.get('buys',0)} ff={ff_6h} loops={loops_6h} drain=${drain_6h:.2f}\n"
                  f"  24h: buys={w24h.get('buys',0)} ff={w24h.get('force_flattens',0)} loops={w24h.get('repeated_entry_loops',0)} drain=${w24h.get('churn_pnl_drain',0):.2f}")
        if churn_tag not in tracked:
            iid = _create_issue(
                f"Churn: {loops_6h} loops in 6h, ${abs(drain_6h):.2f} drain",
                detail,
                "high",
                "opus",
                churn_tag,
            )
            if iid:
                tracked[churn_tag] = {"id": iid, "opened_at": now_iso}
        else:
            _comment_issue(tracked[churn_tag]["id"], f"Cycle {cycle}: {detail}")
    elif churn_tag in tracked and ff_6h == 0 and loops_6h == 0:
        _close_issue(tracked[churn_tag]["id"], "Churn stopped: 0 force_flattens and 0 loops in 6h window")
        del tracked[churn_tag]

    # ── Save state ───────────────────────────────────────────────
    state["tracked_issues"] = tracked
    state["last_cycle"] = cycle
    _save_bridge_state(state)

    open_count = len(tracked)
    log.info("[PAPERCLIP] Bridge cycle %d: %d tracked issues", cycle, open_count)

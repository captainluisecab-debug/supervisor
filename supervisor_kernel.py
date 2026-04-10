"""
supervisor_kernel.py — KERNEL: Invariant Validation Layer.

ROLE: Smallest, most trusted layer. Validates safety invariants once per
cycle BEFORE Governor acts. Returns PASS or HALT. Never writes command
files. Never decides posture. Never replaces Governor or Hermes.

INVARIANTS:
  1. Force flatten consistency  — no force_flatten + entry_allowed contradiction
  2. DD override respected      — Hermes entry block reflected in command files
  3. Regime behavior respected  — FLAT/REDUCE regime = no entries in command files
  4. Expectancy freeze respected — below threshold = no entries (Kraken only)
  5. Lane integrity             — all command files written by Governor

GOAL: Increase positive PnL by catching invariant violations before they
propagate to bot behavior.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List

log = logging.getLogger("kernel")

# ── Paths ────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KERNEL_AUDIT_FILE = os.path.join(BASE_DIR, "kernel_audit.jsonl")
KERNEL_BYPASS_FILE = os.path.join(BASE_DIR, "KERNEL_BYPASS.txt")

HERMES_CONTEXT_FILE = os.path.join(BASE_DIR, "hermes_context.json")
KRAKEN_TRUTH_FILE = os.path.join(BASE_DIR, "kraken_state_truth.json")

# Import constants and paths from Governor (single source of truth)
from supervisor_governor import (
    CMD_KRAKEN, CMD_SFM, CMD_ALPACA,
    REGIME_BEHAVIOR, DEFAULT_BEHAVIOR,
    EXPECTANCY_FREEZE_THRESHOLD,
    ENZOBOT_DIR,
    compute_rolling_expectancy,
)

EXIT_LOG = os.path.join(ENZOBOT_DIR, "logs", "exit_counterfactuals.jsonl")

SLEEVE_CMD_MAP = {
    "kraken": CMD_KRAKEN,
    "sfm": CMD_SFM,
    "alpaca": CMD_ALPACA,
}


# ── Result ───────────────────────────────────────────────────────────
@dataclass
class KernelResult:
    status: str                    # "PASS" or "HALT"
    violations: List[str] = field(default_factory=list)
    checked_at: str = ""
    duration_ms: int = 0


# ── Helpers ──────────────────────────────────────────────────────────
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
        return [json.loads(line) for line in lines[-n:] if line.strip()]
    except Exception:
        return []


# ── Invariant checks ────────────────────────────────────────────────
def _check_force_flatten_consistency() -> List[str]:
    """INV-1: No command file may have force_flatten=true AND entry_allowed=true."""
    violations = []
    for sleeve, path in SLEEVE_CMD_MAP.items():
        cmd = _read_json(path)
        if not cmd:
            continue
        if cmd.get("force_flatten") is True and cmd.get("entry_allowed") is True:
            violations.append(
                f"INV-1: {sleeve}_cmd has force_flatten=true AND entry_allowed=true"
            )
    return violations


def _check_dd_override_respected() -> List[str]:
    """INV-2: If Hermes says entry_allowed=false, command file must not say true."""
    violations = []
    hermes = _read_json(HERMES_CONTEXT_FILE)
    advisory = hermes.get("advisory", {})
    for sleeve, path in SLEEVE_CMD_MAP.items():
        adv = advisory.get(sleeve, {})
        if adv.get("entry_allowed") is False:
            cmd = _read_json(path)
            if cmd.get("entry_allowed") is True:
                violations.append(
                    f"INV-2: Hermes blocks {sleeve} entries but {sleeve}_cmd has entry_allowed=true"
                )
    return violations


def _check_regime_behavior_respected() -> List[str]:
    """INV-3: If regime maps to no-entry behavior, no command file allows entries.
    Exception: Kraken pair_scout_override with mode=SCOUT and open_positions <= 1."""
    violations = []
    truth = _read_json(KRAKEN_TRUTH_FILE)
    dominant = truth.get("regime", {}).get("dominant", "RANGING")
    behavior = REGIME_BEHAVIOR.get(dominant, DEFAULT_BEHAVIOR)
    if behavior.get("entries_allowed") is False:
        for sleeve, path in SLEEVE_CMD_MAP.items():
            cmd = _read_json(path)
            if cmd.get("entry_allowed") is True:
                # Pair-scout exemption: Kraken only, SCOUT mode, flag present, <= 1 open position
                if (sleeve == "kraken"
                        and cmd.get("pair_scout_override") is True
                        and cmd.get("mode") == "SCOUT"):
                    open_pos = truth.get("portfolio", {}).get("open_positions", 0)
                    if open_pos <= 1:
                        log.info("[KERNEL] INV-3 EXEMPTED: pair_scout_override active "
                                 "(sleeve=kraken, mode=SCOUT, open_pos=%d)", open_pos)
                        continue
                violations.append(
                    f"INV-3: regime={dominant} (no entries) but {sleeve}_cmd has entry_allowed=true"
                )
    return violations


def _check_expectancy_freeze_respected() -> List[str]:
    """INV-4: If Kraken expectancy < threshold, entries must be blocked.
    Exception: pair_scout_override with mode=SCOUT and open_positions <= 1."""
    violations = []
    exits = _read_jsonl_tail(EXIT_LOG, 40)
    if not exits:
        return []
    expectancy = compute_rolling_expectancy(exits, n=20)
    if expectancy < EXPECTANCY_FREEZE_THRESHOLD:
        cmd = _read_json(CMD_KRAKEN)
        if cmd.get("entry_allowed") is True:
            # Pair-scout exemption: flag present, SCOUT mode, <= 1 open position
            if (cmd.get("pair_scout_override") is True
                    and cmd.get("mode") == "SCOUT"):
                truth = _read_json(KRAKEN_TRUTH_FILE)
                open_pos = truth.get("portfolio", {}).get("open_positions", 0)
                if open_pos <= 1:
                    log.info("[KERNEL] INV-4 EXEMPTED: pair_scout_override active "
                             "(expectancy=%.2f, open_pos=%d)", expectancy, open_pos)
                    return violations
            violations.append(
                f"INV-4: expectancy={expectancy:.2f} < {EXPECTANCY_FREEZE_THRESHOLD} "
                f"but kraken_cmd has entry_allowed=true"
            )
    return violations


def _check_lane_integrity() -> List[str]:
    """INV-5: All command files must have source='governor'."""
    violations = []
    for sleeve, path in SLEEVE_CMD_MAP.items():
        cmd = _read_json(path)
        if not cmd:
            continue
        source = cmd.get("source")
        if source not in ("governor", "operator_override"):
            violations.append(
                f"INV-5: {sleeve}_cmd source='{source}' (expected 'governor')"
            )
    return violations


# ── Main entry point ────────────────────────────────────────────────
def run_kernel(cycle: int) -> KernelResult:
    """Run all invariant checks. Returns PASS or HALT."""
    t0 = time.monotonic()
    now = datetime.now(timezone.utc).isoformat()

    # Emergency bypass
    if os.path.exists(KERNEL_BYPASS_FILE):
        log.warning("[KERNEL] BYPASS active — returning PASS unconditionally")
        return KernelResult(status="PASS", checked_at=now, duration_ms=0)

    # Run all five invariant checks
    violations = []
    violations.extend(_check_force_flatten_consistency())
    violations.extend(_check_dd_override_respected())
    violations.extend(_check_regime_behavior_respected())
    violations.extend(_check_expectancy_freeze_respected())
    violations.extend(_check_lane_integrity())

    duration_ms = int((time.monotonic() - t0) * 1000)
    status = "HALT" if violations else "PASS"

    result = KernelResult(
        status=status,
        violations=violations,
        checked_at=now,
        duration_ms=duration_ms,
    )

    # Log
    if status == "PASS":
        log.info("[KERNEL] PASS - 5/5 invariants clean (cycle %d)", cycle)
    else:
        log.warning("[KERNEL] HALT - %d violation(s) detected (cycle %d)",
                     len(violations), cycle)
        for v in violations:
            log.warning("[KERNEL] VIOLATION %s", v)

    # Audit trail
    try:
        audit = {
            "ts": now,
            "cycle": cycle,
            "status": status,
            "violations": violations,
            "duration_ms": duration_ms,
        }
        with open(KERNEL_AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(audit) + "\n")
    except Exception as exc:
        log.error("[KERNEL] Failed to write audit: %s", exc)

    return result

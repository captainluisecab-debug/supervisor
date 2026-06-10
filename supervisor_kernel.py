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
  6. Strategic directive freshness — opus_strategic_directive.json <14h old
                                    (Option A: log-only [ANOMALY], does NOT halt kernel)

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
    CMD_KRAKEN, CMD_ALPACA, CMD_ZEROBOT, CMD_DRIFTBOT,  # CMD_SFM dropped — sfm de-wired (D-038)
    REGIME_BEHAVIOR, DEFAULT_BEHAVIOR,
    EXPECTANCY_FREEZE_THRESHOLD,
    ENZOBOT_DIR, ALPACA_DIR,
    compute_rolling_expectancy,
    classify_dominant_regime,
)

EXIT_LOG = os.path.join(ENZOBOT_DIR, "logs", "exit_counterfactuals.jsonl")

SLEEVE_CMD_MAP = {
    "kraken":  CMD_KRAKEN,
    # "sfm" REMOVED — retired/de-wired D-038 (lockstep with governor: no sfm_cmd written -> INV-5 clean)
    "alpaca":  CMD_ALPACA,
    "zerobot": CMD_ZEROBOT,
    "driftbot": CMD_DRIFTBOT,  # PAPER (D-035)
}

# INV-3 (regime behavior) skip-list. ZeroBot has its OWN SMA-50 macro filter
# baked into strategy.entry_allowed — applying governor's regime gate would
# create double-gating that BLOCKS contrarian Donchian-20 breakouts during
# crypto bear markets (the trades the rule is designed to catch).
# Per Opus plan §4 + D-010.
INV3_SKIP_SLEEVES = frozenset({"zerobot", "driftbot"})  # both have their own SMA-50 macro filter (D-035)


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

    Per-sleeve regime source (NOT the cmd file -- cmd files can be stale
    when governor is skipped, creating a self-lock where kernel keeps
    halting on the stale value it needs governor to rewrite):
      - kraken : crypto dominant from kraken_state_truth.json
      - sfm    : crypto dominant (SFM is also a crypto sleeve)
      - alpaca : classify_dominant_regime(alpaca_state.pair_regime)
    """
    violations = []
    crypto_truth = _read_json(KRAKEN_TRUTH_FILE)
    crypto_dominant = crypto_truth.get("regime", {}).get("dominant", "RANGING")

    alpaca_state = _read_json(os.path.join(ALPACA_DIR, "alpaca_state.json"))
    alpaca_pair_regime = alpaca_state.get("pair_regime", {})
    alpaca_dominant = classify_dominant_regime(alpaca_pair_regime) if alpaca_pair_regime else "RANGING"

    sleeve_regimes = {
        "kraken":  crypto_dominant,
        # "sfm" REMOVED — de-wired D-038
        "alpaca":  alpaca_dominant,
        "zerobot": crypto_dominant,  # listed for completeness; skipped via INV3_SKIP_SLEEVES below
        "driftbot": crypto_dominant,  # PAPER; skipped via INV3_SKIP_SLEEVES (D-035)
    }

    for sleeve, path in SLEEVE_CMD_MAP.items():
        if sleeve in INV3_SKIP_SLEEVES:
            continue  # strategy.entry_allowed gates internally (Opus plan §4)
        sleeve_regime = sleeve_regimes.get(sleeve, crypto_dominant)
        behavior = REGIME_BEHAVIOR.get(sleeve_regime, DEFAULT_BEHAVIOR)
        if behavior.get("entries_allowed") is False:
            cmd = _read_json(path)
            if cmd.get("source") == "operator_override":
                continue
            if cmd.get("entry_allowed") is True:
                violations.append(
                    f"INV-3: {sleeve} regime={sleeve_regime} (no entries) "
                    f"but {sleeve}_cmd has entry_allowed=true"
                )
    return violations


def _check_expectancy_freeze_respected() -> List[str]:
    """INV-4: If Kraken expectancy < threshold, entries must be blocked."""
    violations = []
    exits = _read_jsonl_tail(EXIT_LOG, 40)
    if not exits:
        return []
    expectancy = compute_rolling_expectancy(exits, n=20)
    if expectancy < EXPECTANCY_FREEZE_THRESHOLD:
        cmd = _read_json(CMD_KRAKEN)
        if cmd.get("entry_allowed") is True:
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


def _check_strategic_directive_freshness() -> List[str]:
    """INV-6: opus_strategic_directive.json must be <14h old (Option A: log-only).

    Rationale: scheduled strategic review runs every 12h. 14h = one missed
    cycle + 2h grace. Staler than 14h means the strategic review pipeline
    is broken (missing API key, API call failure, schedule misfire) and
    governor's strategic_size_mult adjustments are reading stale state.
    Governor's own consumption sites at supervisor_governor.py:524 and
    :1157 already gate on 14h via _parse_ts; INV-6 makes that staleness
    LOUD at the KERNEL level so anomalies.py picks it up.

    Option A behavior (per L-007 + operator decision 2026-05-17):
      - Emits [ANOMALY] STRATEGIC_DIRECTIVE_* via log.warning when stale,
        missing, or in the future.
      - Returns [] always — does NOT contribute to KERNEL halt count.
      - Preserves the 8-day operating tolerance: governor cycles continue
        regardless of directive freshness, but the failure is now visible.
    """
    path = os.path.join(BASE_DIR, "opus_strategic_directive.json")
    if not os.path.exists(path):
        log.warning(
            "[ANOMALY] STRATEGIC_DIRECTIVE_MISSING — "
            "opus_strategic_directive.json does not exist; "
            "strategic review never produced output"
        )
        return []
    age_h = (time.time() - os.path.getmtime(path)) / 3600.0
    if age_h < 0:
        log.warning(
            "[ANOMALY] STRATEGIC_DIRECTIVE_FUTURE_MTIME — "
            "opus_strategic_directive.json mtime IN FUTURE by %.1fh "
            "(clock skew or manual touch)",
            -age_h,
        )
    elif age_h > 14:
        log.warning(
            "[ANOMALY] STRATEGIC_DIRECTIVE_STALE — "
            "opus_strategic_directive.json age=%.1fh > 14h threshold "
            "(strategic review pipeline failed; see [STRATEGIC]/[ANOMALY] "
            "lines in supervisor.log)",
            age_h,
        )
    return []


# ── Main entry point ────────────────────────────────────────────────
def run_kernel(cycle: int) -> KernelResult:
    """Run all invariant checks. Returns PASS or HALT."""
    t0 = time.monotonic()
    now = datetime.now(timezone.utc).isoformat()

    # Emergency bypass
    if os.path.exists(KERNEL_BYPASS_FILE):
        log.warning("[KERNEL] BYPASS active — returning PASS unconditionally")
        return KernelResult(status="PASS", checked_at=now, duration_ms=0)

    # Run all six invariant checks
    violations = []
    violations.extend(_check_force_flatten_consistency())
    violations.extend(_check_dd_override_respected())
    violations.extend(_check_regime_behavior_respected())
    violations.extend(_check_expectancy_freeze_respected())
    violations.extend(_check_lane_integrity())
    violations.extend(_check_strategic_directive_freshness())  # INV-6 Option A: log-only

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
        log.info("[KERNEL] PASS - 6/6 invariants clean (cycle %d)", cycle)
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

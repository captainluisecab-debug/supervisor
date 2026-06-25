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
    CMD_ALPACA, CMD_ZEROBOT,  # CMD_KRAKEN dropped — enzobot retired (D-063); CMD_SFM (D-038), CMD_DRIFTBOT (D-062)
    REGIME_BEHAVIOR, DEFAULT_BEHAVIOR,
    ALPACA_DIR,
    classify_dominant_regime,
    # ENZOBOT_DIR, EXPECTANCY_FREEZE_THRESHOLD, compute_rolling_expectancy dropped — INV-4 removed (D-063)
)

# EXIT_LOG removed — INV-4 (Kraken expectancy) removed with enzobot (D-063)

SLEEVE_CMD_MAP = {
    # "kraken" REMOVED — enzobot retired/de-wired D-063 (lockstep with governor: no kraken_cmd written)
    # "sfm" REMOVED — retired/de-wired D-038
    "alpaca":  CMD_ALPACA,
    "zerobot": CMD_ZEROBOT,
    # "driftbot" REMOVED — retired/de-wired D-062
}

# INV-3 (regime behavior) skip-list. ZeroBot has its OWN SMA-50 macro filter
# baked into strategy.entry_allowed — applying governor's regime gate would
# create double-gating that BLOCKS contrarian Donchian-20 breakouts during
# crypto bear markets (the trades the rule is designed to catch).
# Per Opus plan §4 + D-010.
INV3_SKIP_SLEEVES = frozenset({"zerobot"})  # zerobot has its own SMA-50 macro filter (driftbot retired D-062)


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
        # "kraken" REMOVED — enzobot retired/de-wired D-063 (no kraken trading sleeve; the account
        #   regime is still written to kraken_state_truth.json for zerobot's check below)
        # "sfm" REMOVED — de-wired D-038
        "alpaca":  alpaca_dominant,
        "zerobot": crypto_dominant,  # listed for completeness; skipped via INV3_SKIP_SLEEVES below
        # "driftbot" REMOVED — retired/de-wired D-062
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


# INV-4 (_check_expectancy_freeze_respected) REMOVED — enzobot retired/de-wired (D-063): it froze the
# Kraken trader's entries on poor expectancy, but there is no live Kraken trader anymore. The kernel now
# runs 4 hard invariants (INV-1/2/3/5) + INV-6 (advisory, log-only). Proven by _kernel_invariant_harness.py.


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

    # Run the invariant checks (INV-4 Kraken-expectancy REMOVED with enzobot, D-063)
    violations = []
    violations.extend(_check_force_flatten_consistency())      # INV-1
    violations.extend(_check_dd_override_respected())          # INV-2
    violations.extend(_check_regime_behavior_respected())      # INV-3
    violations.extend(_check_lane_integrity())                 # INV-5
    violations.extend(_check_strategic_directive_freshness())  # INV-6 Option A: log-only (advisory)

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
        log.info("[KERNEL] PASS - 5/5 invariants clean [4 hard + INV-6 advisory] (cycle %d)", cycle)
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

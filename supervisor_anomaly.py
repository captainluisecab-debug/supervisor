"""
supervisor_anomaly.py — Anomaly detection across all bots.

Runs every supervisor cycle. Tracks rolling counters and detects:
- Entry drought (no new positions for extended period)
- ADX blocking everything (threshold too aggressive for market)
- attack_max_dd too tight (DD > threshold for many cycles, bot frozen)
- Stale lock files
- Excessive brain parameter churn
- Score saturation
- Frozen cycle counters
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, time as dtime, timezone
from dataclasses import dataclass, field
from typing import List, Optional

log = logging.getLogger("supervisor_anomaly")

# Paths
ENZOBOT_DIR    = r"C:\Projects\enzobot"
SFMBOT_DIR     = r"C:\Projects\sfmbot"
ALPACA_DIR     = r"C:\Projects\alpacabot"
SUPERVISOR_DIR = os.path.dirname(os.path.abspath(__file__))

LOCK_FILES = [
    os.path.join(ENZOBOT_DIR,  "enzobot.lock"),
    os.path.join(SFMBOT_DIR,   "sfmbot.lock"),
    os.path.join(ALPACA_DIR,   "alpacabot.lock"),
]

# Thresholds
ENTRY_DROUGHT_CYCLES   = 60    # supervisor cycles (~5h at 5min) with no new entry → anomaly
ADX_BLOCK_CYCLES       = 80    # supervisor cycles where ADX blocks everything → lower threshold
ATTACK_DD_BLOCK_CYCLES = 40    # supervisor cycles where DD > attack_max_dd → loosen threshold
LOCK_STALE_SEC         = 600   # 10 minutes — lock file older than this = stale
MAX_CHANGES_PER_DAY    = 20    # brain parameter changes per day before flagging churn
CYCLE_FROZEN_SEC       = 600   # bot cycle hasn't advanced in 10 min = frozen


@dataclass
class Anomaly:
    code: str
    severity: str          # HIGH / MEDIUM / LOW
    description: str
    data: dict = field(default_factory=dict)


@dataclass
class AnomalyReport:
    anomalies: List[Anomaly]
    cycle: int
    ts: str

    @property
    def has_critical(self) -> bool:
        return any(a.severity == "HIGH" for a in self.anomalies)

    def summary(self) -> str:
        if not self.anomalies:
            return "No anomalies detected."
        lines = [f"[{a.severity}] {a.code}: {a.description}" for a in self.anomalies]
        return "\n".join(lines)


class AnomalyDetector:
    """
    Stateful detector — must persist across supervisor cycles to track rolling counters.
    Instantiate once in supervisor.py and call .check() every cycle.
    """

    def __init__(self):
        # Rolling counters
        self._entry_drought_cycles    = 0
        self._adx_block_cycles        = 0
        self._attack_dd_block_cycles  = 0

        # Last known values for change detection
        self._last_enzobot_trade_ts   = 0
        self._last_sfm_trade_ts       = 0
        self._last_enzobot_cycle      = 0
        self._last_enzobot_cycle_seen = 0.0   # wall clock time
        self._last_sfm_cycle          = 0
        self._last_sfm_cycle_seen     = 0.0
        self._last_alpaca_cycle       = 0
        self._last_alpaca_cycle_seen  = 0.0

    # ── State readers ─────────────────────────────────────────────────

    def _read_json(self, path: str) -> dict:
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _enzobot_state(self) -> dict:
        return self._read_json(os.path.join(ENZOBOT_DIR, "state.json"))

    def _enzobot_brain_state(self) -> dict:
        return self._read_json(os.path.join(ENZOBOT_DIR, "brain_state.json"))

    def _enzobot_policy(self) -> dict:
        return self._read_json(os.path.join(ENZOBOT_DIR, "policy.json"))

    def _sfm_state(self) -> dict:
        return self._read_json(os.path.join(SFMBOT_DIR, "sfm_state.json"))

    def _alpaca_state(self) -> dict:
        return self._read_json(os.path.join(ALPACA_DIR, "alpaca_state.json"))

    # ── Individual checks ──────────────────────────────────────────────

    def _check_entry_drought(self, enzobot: dict, sfm: dict) -> Optional[Anomaly]:
        """No new trade opened across crypto bots for too long."""
        ez_ts  = int(enzobot.get("last_cycle_ts", 0))
        sfm_ts = int((sfm.get("position") or {}).get("entry_ts", 0))

        latest_trade = max(ez_ts, sfm_ts)

        # If last trade timestamp advanced, reset counter
        if latest_trade > self._last_enzobot_trade_ts:
            self._last_enzobot_trade_ts = latest_trade
            self._entry_drought_cycles  = 0
            return None

        self._entry_drought_cycles += 1

        if self._entry_drought_cycles >= ENTRY_DROUGHT_CYCLES:
            return Anomaly(
                code="ENTRY_DROUGHT",
                severity="MEDIUM",
                description=f"No new entry in {self._entry_drought_cycles} supervisor cycles (~{self._entry_drought_cycles*5//60}h)",
                data={"drought_cycles": self._entry_drought_cycles},
            )
        return None

    def _check_adx_blocking(self, enzobot_log_tail: str) -> Optional[Anomaly]:
        """All candidates blocked by ADX threshold for extended period."""
        # Detect by checking if last 5 gate lines all say adx_too_low
        adx_blocks = enzobot_log_tail.count("adx_too_low")
        total_gates = enzobot_log_tail.count("[GATE]")

        if total_gates >= 3 and adx_blocks == total_gates:
            self._adx_block_cycles += 1
        else:
            self._adx_block_cycles = max(0, self._adx_block_cycles - 1)

        if self._adx_block_cycles >= ADX_BLOCK_CYCLES:
            return Anomaly(
                code="ADX_THRESHOLD_TOO_HIGH",
                severity="HIGH",
                description=f"All pairs ADX-blocked for {self._adx_block_cycles} cycles — threshold may be too aggressive for current choppy market",
                data={"adx_block_cycles": self._adx_block_cycles, "gate_sample": enzobot_log_tail[-300:]},
            )
        return None

    def _check_attack_dd_blocked(self, enzobot: dict, policy: dict) -> Optional[Anomaly]:
        """DD consistently above attack_max_dd — bot can't enter ATTACK, frozen in HOLD."""
        positions = {k: v for k, v in enzobot.get("positions", {}).items()
                     if v.get("qty", 0) > 0}
        cash = float(enzobot.get("cash", 0))
        peak = float(enzobot.get("equity_peak", 1))

        # Estimate equity (cash + open position value at last known prices)
        pos_value = sum(
            v.get("qty", 0) * (v.get("last_price") or v.get("avg_price") or 0)
            for v in positions.values()
        )
        equity = cash + pos_value
        dd_pct = ((peak - equity) / peak * 100) if peak > 0 else 0

        attack_max_dd = float((policy.get("attack_rules") or {}).get("max_dd_pct", 3.0))

        if dd_pct > attack_max_dd:
            self._attack_dd_block_cycles += 1
        else:
            self._attack_dd_block_cycles = max(0, self._attack_dd_block_cycles - 2)

        if self._attack_dd_block_cycles >= ATTACK_DD_BLOCK_CYCLES:
            # Cross-validate against trusted supervisor_report.json before raising.
            # If this DD disagrees materially with the trusted source, suppress and log
            # locally — do NOT raise an anomaly (any anomaly triggers Opus/selfheal).
            trusted_dd = self._get_trusted_sleeve_dd("kraken_crypto")
            if trusted_dd is not None and dd_pct > 2 * abs(trusted_dd):
                log.warning(
                    "[ANOMALY] INCONSISTENT_DD_DATA: computed DD %.1f%% vs trusted "
                    "sleeve DD %.1f%% — suppressing ATTACK_DD_TOO_TIGHT (position "
                    "price data mismatch, not a real threshold breach)",
                    dd_pct, trusted_dd,
                )
                return None
            return Anomaly(
                code="ATTACK_DD_TOO_TIGHT",
                severity="HIGH",
                description=(
                    f"DD {dd_pct:.1f}% > attack_max_dd {attack_max_dd}% for "
                    f"{self._attack_dd_block_cycles} cycles — bot in restricted mode, "
                    f"entries blocked. Trusted sleeve DD: {trusted_dd:.1f}%."
                ),
                data={
                    "dd_pct": round(dd_pct, 2),
                    "trusted_dd_pct": round(trusted_dd, 2) if trusted_dd is not None else None,
                    "attack_max_dd": attack_max_dd,
                    "block_cycles": self._attack_dd_block_cycles,
                },
            )
        return None

    def _check_lock_files(self) -> List[Anomaly]:
        """Stale lock files prevent bot from starting."""
        anomalies = []
        now = time.time()
        for path in LOCK_FILES:
            if os.path.exists(path):
                age = now - os.path.getmtime(path)
                if age > LOCK_STALE_SEC:
                    anomalies.append(Anomaly(
                        code="STALE_LOCK_FILE",
                        severity="HIGH",
                        description=f"Lock file {os.path.basename(path)} is {age/60:.0f} min old — bot may be crashed",
                        data={"path": path, "age_sec": round(age)},
                    ))
        return anomalies

    def _check_brain_churn(self, brain_state: dict) -> Optional[Anomaly]:
        """Excessive parameter changes — brain is thrashing."""
        changes_today = int(brain_state.get("changes_today", 0))
        if changes_today > MAX_CHANGES_PER_DAY:
            return Anomaly(
                code="BRAIN_CHURN",
                severity="MEDIUM",
                description=f"Brain made {changes_today} parameter changes today (limit {MAX_CHANGES_PER_DAY}) — thrashing",
                data={"changes_today": changes_today},
            )
        return None

    def _check_frozen_cycle(self, state: dict, bot: str) -> Optional[Anomaly]:
        """Bot cycle counter hasn't advanced — process may be frozen."""
        now = time.time()
        cycle = int(state.get("cycle", 0))

        # Enzobot state.json has no 'cycle' field — use last_cycle_ts instead
        if bot == "enzobot":
            last_ts = int(state.get("last_cycle_ts", 0))
            # If last_cycle_ts is 0 or never set, bot hasn't started yet — skip
            if last_ts == 0:
                self._last_enzobot_cycle_seen = now
                return None
            if last_ts != self._last_enzobot_cycle:
                self._last_enzobot_cycle      = last_ts
                self._last_enzobot_cycle_seen = now
            elif now - self._last_enzobot_cycle_seen > CYCLE_FROZEN_SEC:
                age_min = (now - self._last_enzobot_cycle_seen) / 60
                return Anomaly(
                    code="CYCLE_FROZEN_ENZOBOT",
                    severity="HIGH",
                    description=f"Enzobot last_cycle_ts unchanged for {age_min:.0f} min — process may be frozen",
                    data={"last_cycle_ts": last_ts, "frozen_min": round(age_min)},
                )
        elif bot == "sfm":
            if cycle != self._last_sfm_cycle:
                self._last_sfm_cycle      = cycle
                self._last_sfm_cycle_seen = now
            elif now - self._last_sfm_cycle_seen > CYCLE_FROZEN_SEC:
                return Anomaly(
                    code="CYCLE_FROZEN_SFMBOT",
                    severity="HIGH",
                    description=f"SFMbot cycle stuck at {cycle} for {(now - self._last_sfm_cycle_seen)/60:.0f} min",
                    data={"cycle": cycle, "frozen_sec": round(now - self._last_sfm_cycle_seen)},
                )
        elif bot == "alpaca":
            if cycle != self._last_alpaca_cycle:
                self._last_alpaca_cycle      = cycle
                self._last_alpaca_cycle_seen = now
            elif now - self._last_alpaca_cycle_seen > CYCLE_FROZEN_SEC:
                # Suppress during NYSE closed hours — alpacabot sleeps by design
                utc_now = datetime.now(timezone.utc)
                weekday = utc_now.weekday()  # 0=Mon ... 6=Sun
                in_hours = (
                    weekday < 5
                    and dtime(14, 30) <= utc_now.time() <= dtime(21, 0)
                )
                if not in_hours:
                    log.debug(
                        "[ANOMALY] CYCLE_FROZEN_ALPACA suppressed — NYSE closed "
                        "(weekday=%d, utc=%s)", weekday, utc_now.strftime("%H:%M")
                    )
                    return None
                return Anomaly(
                    code="CYCLE_FROZEN_ALPACA",
                    severity="HIGH",
                    description=f"Alpacabot cycle stuck at {cycle} for {(now - self._last_alpaca_cycle_seen)/60:.0f} min",
                    data={"cycle": cycle, "frozen_sec": round(now - self._last_alpaca_cycle_seen)},
                )
        return None

    def _read_enzobot_log_tail(self) -> str:
        """Read last 50 lines of latest enzobot log."""
        log_dir = os.path.join(ENZOBOT_DIR, "logs")
        try:
            logs = sorted(
                [f for f in os.listdir(log_dir) if f.startswith("run_")],
                reverse=True,
            )
            if not logs:
                return ""
            with open(os.path.join(log_dir, logs[0]), encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            return "".join(lines[-50:])
        except Exception:
            return ""

    def _get_trusted_sleeve_dd(self, sleeve_name: str) -> Optional[float]:
        """Read trusted DD from supervisor_report.json (written by supervisor_portfolio.py).
        Returns None if file is missing or field is absent."""
        report_path = os.path.join(SUPERVISOR_DIR, "supervisor_report.json")
        report = self._read_json(report_path)
        sleeve = report.get("sleeves", {}).get(sleeve_name, {})
        dd = sleeve.get("drawdown_pct")
        if dd is not None:
            try:
                return float(dd)
            except (TypeError, ValueError):
                return None
        return None

    # ── Main check ────────────────────────────────────────────────────

    def check(self, supervisor_cycle: int) -> AnomalyReport:
        """Run all anomaly checks. Returns AnomalyReport."""
        from datetime import datetime, timezone

        anomalies: List[Anomaly] = []

        enzobot     = self._enzobot_state()
        brain_state = self._enzobot_brain_state()
        policy      = self._enzobot_policy()
        sfm         = self._sfm_state()
        alpaca      = self._alpaca_state()
        log_tail    = self._read_enzobot_log_tail()

        # Run all checks
        checks = [
            self._check_entry_drought(enzobot, sfm),
            self._check_adx_blocking(log_tail),
            self._check_attack_dd_blocked(enzobot, policy),
            self._check_brain_churn(brain_state),
            self._check_frozen_cycle(enzobot, "enzobot"),
            self._check_frozen_cycle(sfm, "sfm"),
            self._check_frozen_cycle(alpaca, "alpaca"),
        ]

        for result in checks:
            if result:
                anomalies.append(result)

        anomalies.extend(self._check_lock_files())

        # Deduplicated anomaly logging: only log on state change
        current_codes = frozenset(a.code for a in anomalies)
        if not hasattr(self, "_prev_anomaly_codes"):
            self._prev_anomaly_codes = frozenset()

        new_codes = current_codes - self._prev_anomaly_codes
        cleared_codes = self._prev_anomaly_codes - current_codes

        if new_codes:
            log.warning("[ANOMALY] NEW: %s", ", ".join(sorted(new_codes)))
        if cleared_codes:
            log.info("[ANOMALY] CLEARED: %s", ", ".join(sorted(cleared_codes)))
        if not new_codes and not cleared_codes and anomalies:
            log.debug("[ANOMALY] Unchanged: %s (suppressed — no state change)",
                      ", ".join(sorted(current_codes)))

        self._prev_anomaly_codes = current_codes

        return AnomalyReport(
            anomalies=anomalies,
            cycle=supervisor_cycle,
            ts=datetime.now(timezone.utc).isoformat(),
        )

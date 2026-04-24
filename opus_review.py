"""
opus_review.py — Scheduled operator-packet generator.

Wakes at 07:50 and 19:50 local time, builds a consolidated markdown
report of the 12h window ending at the wake time, writes it to
operator_packet.md (latest) and operator_packets/YYYY-MM-DD_HHMM.md
(archive). Operator reads this at 08:00 and 20:00.

Invocation modes:
  python opus_review.py           → scheduler loop (used by watchdog)
  python opus_review.py --now     → generate one packet immediately and exit

Source files (authoritative state only):
  - Enzobot:     state.json, supervisor_feedback.json,
                 exit_counterfactuals.jsonl, brain_decisions.jsonl
  - Alpaca:      alpaca_state.json
  - Solana:      solana_state.json
  - Supervisor:  kernel_audit.jsonl, opus_sentinel_audit.jsonl,
                 commands/*.json
  - Memory:      issues.jsonl

No external API calls. No LLM synthesis in v1 — deterministic report.
Opus synthesis header can be added as a follow-up when we observe
what data operator actually uses.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s][REVIEW] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("opus_review")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENZOBOT_DIR = r"C:\Projects\enzobot"
ALPACA_DIR = r"C:\Projects\alpacabot"
SFMBOT_DIR = r"C:\Projects\sfmbot"

# Input files
ENZO_STATE = os.path.join(ENZOBOT_DIR, "state.json")
ENZO_FEEDBACK = os.path.join(ENZOBOT_DIR, "supervisor_feedback.json")
ENZO_EXITS = os.path.join(ENZOBOT_DIR, "logs", "exit_counterfactuals.jsonl")
ENZO_BRAIN = os.path.join(ENZOBOT_DIR, "brain_decisions.jsonl")
ALPACA_STATE = os.path.join(ALPACA_DIR, "alpaca_state.json")
SOLANA_STATE = os.path.join(SFMBOT_DIR, "solana_state.json")

KERNEL_AUDIT = os.path.join(BASE_DIR, "kernel_audit.jsonl")
SENTINEL_AUDIT = os.path.join(BASE_DIR, "opus_sentinel_audit.jsonl")
CMD_KRAKEN = os.path.join(BASE_DIR, "commands", "kraken_cmd.json")
CMD_SFM = os.path.join(BASE_DIR, "commands", "sfm_cmd.json")
CMD_ALPACA = os.path.join(BASE_DIR, "commands", "alpaca_cmd.json")
ISSUES_FILE = r"C:\Projects\memory\openclaw\openclaw_workspace\issues.jsonl"

# Output
LATEST_PACKET = os.path.join(BASE_DIR, "operator_packet.md")
ARCHIVE_DIR = os.path.join(BASE_DIR, "operator_packets")

# Schedule: 07:50 and 19:50 local time
SCHEDULE_HHMM = [(7, 50), (19, 50)]
WINDOW_HOURS = 12  # look-back window


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _read_jsonl_tail(path: str, n: int = 200) -> list:
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        return [json.loads(ln) for ln in lines[-n:] if ln.strip()]
    except Exception:
        return []


def _file_age_sec(path: str) -> float:
    try:
        return time.time() - os.path.getmtime(path)
    except Exception:
        return 1e9


def _cutoff_ts(hours: float = WINDOW_HOURS) -> float:
    return time.time() - hours * 3600


def _fmt_age(age_sec: float) -> str:
    if age_sec < 120:
        return f"{int(age_sec)}s"
    if age_sec < 7200:
        return f"{int(age_sec / 60)}m"
    return f"{age_sec / 3600:.1f}h"


# ──────────────────────────────────────────────────────────────────────
# Section builders
# ──────────────────────────────────────────────────────────────────────

def section_header(now_local: datetime) -> str:
    which = "8:00 AM" if now_local.hour < 12 else "8:00 PM"
    return (
        f"# Operator Brief — {now_local.strftime('%Y-%m-%d %H:%M %Z')}\n\n"
        f"**Target read time: {which} local**\n"
        f"**Look-back window: {WINDOW_HOURS}h** (from "
        f"{(now_local - timedelta(hours=WINDOW_HOURS)).strftime('%H:%M')} "
        f"to {now_local.strftime('%H:%M')})\n"
    )


def section_posture() -> str:
    """Regime + mode per sleeve from cmd files."""
    k = _read_json(CMD_KRAKEN)
    s = _read_json(CMD_SFM)
    a = _read_json(CMD_ALPACA)
    lines = ["## Posture by sleeve\n"]
    lines.append("| Sleeve | Mode | Entry | Force-flat | Regime | cmd age |")
    lines.append("|---|---|---|---|---|---|")
    for name, d, path in [("Kraken", k, CMD_KRAKEN),
                          ("SFM",    s, CMD_SFM),
                          ("Alpaca", a, CMD_ALPACA)]:
        age = _file_age_sec(path)
        stale_flag = " ⚠️ STALE" if age > 600 else ""
        lines.append(
            f"| {name} | {d.get('mode', '?')} | "
            f"{d.get('entry_allowed', '?')} | "
            f"{d.get('force_flatten', '?')} | "
            f"{d.get('dominant_regime', '?')} | "
            f"{_fmt_age(age)}{stale_flag} |"
        )
    return "\n".join(lines) + "\n"


def section_equity_and_positions() -> str:
    """Per-sleeve equity, cash, open positions, dd."""
    enzo = _read_json(ENZO_STATE)
    enzo_fb = _read_json(ENZO_FEEDBACK)
    alpaca = _read_json(ALPACA_STATE)
    solana = _read_json(SOLANA_STATE)

    lines = ["## Equity / positions\n"]

    # Kraken
    ek_cash = enzo.get("cash", 0)
    ek_peak = enzo.get("equity_peak", 0)
    ek_realized = enzo.get("realized_pnl", 0)
    ek_positions = {p: d for p, d in enzo.get("positions", {}).items()
                    if d.get("qty", 0) > 0}
    ek_equity_from_fb = enzo_fb.get("portfolio", {}).get("equity", ek_cash)
    ek_dd = enzo_fb.get("portfolio", {}).get("dd_pct", 0)
    lines.append("### Kraken (enzobot)")
    lines.append(f"- Equity: **${ek_equity_from_fb:.2f}** (peak ${ek_peak:.2f}, "
                 f"dd {ek_dd:.2f}%)")
    lines.append(f"- Cash: ${ek_cash:.2f}")
    lines.append(f"- Realized PnL (account-lifetime): ${ek_realized:.2f}")
    lines.append(f"- Open positions: {len(ek_positions)}")
    for p, d in sorted(ek_positions.items()):
        qty = d.get("qty", 0)
        avg = d.get("avg_price", 0)
        last = d.get("last_price", 0)
        unrealized = (last - avg) * qty if avg > 0 else 0
        lines.append(f"  - {p}: qty={qty:.4f} @ avg=${avg:.4f} last=${last:.4f} "
                     f"unrealized=${unrealized:+.2f}")

    # Alpaca
    a_realized = alpaca.get("realized_pnl_usd", 0)
    a_trades = alpaca.get("total_trades", 0)
    a_wins = alpaca.get("winning_trades", 0)
    a_peak = alpaca.get("peak_equity", 500)
    a_positions = alpaca.get("positions", {})
    lines.append("\n### Alpaca")
    lines.append(f"- Realized PnL: ${a_realized:.2f} (peak ${a_peak:.2f})")
    lines.append(f"- Trades: {a_trades} | Wins: {a_wins} | "
                 f"Win rate: {(a_wins/max(a_trades,1))*100:.0f}%")
    lines.append(f"- Open positions: {len(a_positions)}")

    # Solana
    sl_usdc = solana.get("usdc_balance", 0)
    sl_sol = solana.get("sol_usd", 0)
    sl_realized = solana.get("realized_pnl_usd", 0)
    sl_trades = solana.get("total_trades", 0)
    sl_peak = solana.get("peak_equity", 0)
    lines.append("\n### Solana (sfmbot)")
    lines.append(f"- Equity: USDC ${sl_usdc:.2f} + SOL ${sl_sol:.2f} "
                 f"= ${sl_usdc + sl_sol:.2f} (peak ${sl_peak:.2f})")
    lines.append(f"- Realized PnL: ${sl_realized:.2f} | "
                 f"Trades: {sl_trades}")

    total_equity = ek_equity_from_fb + a_realized + 500 + sl_usdc + sl_sol
    lines.append(f"\n### Total universe equity: **${total_equity:.2f}**")
    return "\n".join(lines) + "\n"


def section_kernel_status() -> str:
    """Kernel audit — last 10 cycles."""
    tail = _read_jsonl_tail(KERNEL_AUDIT, 10)
    if not tail:
        return "## Kernel\n\n_no audit entries_\n"
    lines = ["## Kernel status (last 10 cycles)\n"]
    pass_count = sum(1 for e in tail if e.get("status") == "PASS")
    halt_count = sum(1 for e in tail if e.get("status") == "HALT")
    lines.append(f"- PASS: {pass_count} | HALT: {halt_count}")
    last = tail[-1]
    lines.append(f"- Last entry: cycle={last.get('cycle')} "
                 f"status={last.get('status')} "
                 f"violations={last.get('violations', [])}")
    if halt_count > 0:
        lines.append("- Recent HALTs:")
        for e in tail[-5:]:
            if e.get("status") == "HALT":
                lines.append(f"  - cycle {e.get('cycle')}: "
                             f"{e.get('violations', [])}")
    return "\n".join(lines) + "\n"


def section_activity() -> str:
    """Kraken fills + exits in last 12h."""
    exits = _read_jsonl_tail(ENZO_EXITS, 100)
    cutoff = _cutoff_ts(WINDOW_HOURS)
    recent = [e for e in exits
              if isinstance(e, dict)
              and e.get("type") == "exit"
              and float(e.get("ts", 0) or 0) >= cutoff]

    lines = [f"## Kraken activity (last {WINDOW_HOURS}h)\n"]
    lines.append(f"- Total exits: {len(recent)}")
    if recent:
        wins = [e for e in recent if float(e.get("pnl_usd", 0) or 0) > 0]
        losses = [e for e in recent if float(e.get("pnl_usd", 0) or 0) < 0]
        total_pnl = sum(float(e.get("pnl_usd", 0) or 0) for e in recent)
        lines.append(f"- Wins: {len(wins)} | Losses: {len(losses)}")
        lines.append(f"- Net PnL (window): ${total_pnl:+.2f}")
        # Exit reasons breakdown
        reasons = {}
        for e in recent:
            r = e.get("exit_reason", "?")
            reasons[r] = reasons.get(r, 0) + 1
        lines.append("- Exit reasons:")
        for r, c in sorted(reasons.items(), key=lambda x: -x[1]):
            lines.append(f"  - {r}: {c}")
        # Pair breakdown
        pairs = {}
        for e in recent:
            p = e.get("pair", "?")
            if p not in pairs:
                pairs[p] = {"count": 0, "pnl": 0.0}
            pairs[p]["count"] += 1
            pairs[p]["pnl"] += float(e.get("pnl_usd", 0) or 0)
        lines.append("- Per-pair activity:")
        for p, d in sorted(pairs.items(), key=lambda x: -x[1]["count"]):
            lines.append(f"  - {p}: {d['count']} trades, ${d['pnl']:+.2f}")
    return "\n".join(lines) + "\n"


def section_sentinel_fires() -> str:
    """Sentinel audit — fires within window."""
    tail = _read_jsonl_tail(SENTINEL_AUDIT, 50)
    cutoff = _cutoff_ts(WINDOW_HOURS)

    # Parse ts strings
    def _ts(entry):
        ts_str = entry.get("ts", "")
        try:
            return datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
        except Exception:
            return 0

    recent = [e for e in tail if _ts(e) >= cutoff]
    lines = [f"## Sentinel fires (last {WINDOW_HOURS}h)\n"]
    if not recent:
        lines.append("_No triggers fired in window. System healthy per sentinel view._")
        return "\n".join(lines) + "\n"
    lines.append(f"- Total fires: {len(recent)}")
    for entry in recent[-15:]:
        ts = entry.get("ts", "")[:19]
        trigger = entry.get("trigger", "?")
        mode = entry.get("mode", "?")
        action = entry.get("action_taken", "?")
        iid = entry.get("issue_id", "")
        lines.append(f"- `{ts}` {trigger} [{mode}] → {action}"
                     f"{' (' + iid + ')' if iid else ''}")
        lines.append(f"  rationale: {entry.get('rationale', '')[:150]}")
    return "\n".join(lines) + "\n"


def section_open_issues() -> str:
    """Open issues from registry."""
    lines_file = _read_jsonl_tail(ISSUES_FILE, 200)
    open_issues = [e for e in lines_file
                   if isinstance(e, dict)
                   and e.get("issue_state") not in ("closed",)
                   and e.get("classification") not in ("closed",)
                   and e.get("closed_at") is None]
    lines = ["## Open issues\n"]
    if not open_issues:
        lines.append("_None._")
        return "\n".join(lines) + "\n"
    lines.append(f"- Count: {len(open_issues)}")
    for iss in open_issues[-10:]:
        iid = iss.get("issue_id", "?")
        sev = iss.get("severity", "?")
        typ = iss.get("anomaly_type", "?")
        src = iss.get("source", iss.get("owner", "?"))
        summary = str(iss.get("evidence_summary", ""))[:120]
        lines.append(f"- **{iid}** [{sev}] {typ} ({src})")
        lines.append(f"  {summary}")
    return "\n".join(lines) + "\n"


def section_brain_activity() -> str:
    """Enzobot brain decisions + Opus recs in window."""
    tail = _read_jsonl_tail(ENZO_BRAIN, 100)

    def _ts(entry):
        ts_str = str(entry.get("ts", ""))
        try:
            return datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
        except Exception:
            return 0

    cutoff = _cutoff_ts(WINDOW_HOURS)
    recent = [e for e in tail if _ts(e) >= cutoff]
    lines = [f"## Brain activity — Kraken (last {WINDOW_HOURS}h)\n"]
    if not recent:
        lines.append("_No brain decisions in window._")
        return "\n".join(lines) + "\n"
    lines.append(f"- Decisions: {len(recent)}")
    modes = {}
    for e in recent:
        m = e.get("final_mode", "?")
        modes[m] = modes.get(m, 0) + 1
    lines.append(f"- Mode distribution: " +
                 ", ".join(f"{m}={c}" for m, c in modes.items()))
    # Most recent decision
    last = recent[-1]
    lines.append(f"- Last decision: mode={last.get('final_mode')} "
                 f"reason={last.get('reasoning', '')[:120]}")
    return "\n".join(lines) + "\n"


def section_next_actions(packet_body: str) -> str:
    """Derive next actions from scanning the body for flags. Patterns must
    be specific enough to avoid matching their own section headers or counters."""
    lines = ["## Recommended next actions\n"]
    # Match only real HALT events (from kernel audit dump), not the HALT counter line
    if "status=HALT" in packet_body or "cycle " in packet_body and "violations=[" in packet_body and "violations=[]" not in packet_body.split("Last entry")[-1][:500]:
        # simpler: look for entries with non-empty violations
        import re
        if re.search(r"violations=\[['\"]", packet_body):
            lines.append("- ⚠️ Kernel HALT with violations detected — investigate invariants.")
    if "⚠️ STALE" in packet_body:
        lines.append("- ⚠️ At least one cmd file is stale — verify governor/supervisor running.")
    if "[CRITICAL]" in packet_body:
        lines.append("- 🚨 CRITICAL severity issue in window — review immediately.")
    if "B10_phantom_fill" in packet_body:
        lines.append("- 🚨 Phantom fill detected — verify ISSUE-011 fix still live.")
    if "B6_no_profit_12h" in packet_body:
        lines.append("- Strategy review: zero winning exits across 3+ trades.")
    if "B3_fill_failures" in packet_body:
        lines.append("- Fill reliability: per-pair offset or disable candidate.")
    if "B11_allowlist_miss" in packet_body:
        lines.append("- Allowlist expansion candidate: new Opus recommendation class.")
    if "B2_expectancy_below_floor" in packet_body:
        lines.append("- Expectancy structural breach — strategy review needed.")
    if "B4_same_pair_churn" in packet_body:
        lines.append("- Same-pair churn flagged — consider per-pair cooldown or disable.")
    if "B7_regime_disagreement" in packet_body:
        lines.append("- Brain vs Governor regime disagreement — audit regime inputs.")
    if "B9_orphan_position" in packet_body:
        lines.append("- Position mismatch detected — verify Kraken vs bot state.")
    if len(lines) == 1:
        lines.append("- System stable. No operator action required this window.")
    return "\n".join(lines) + "\n"


# ──────────────────────────────────────────────────────────────────────
# Packet assembly
# ──────────────────────────────────────────────────────────────────────

def section_autonomy_activity() -> str:
    """Autonomous tuning activity summary: writes, verdicts, frozen params."""
    lines = [f"## Autonomy activity (last {WINDOW_HOURS}h)\n"]
    try:
        from autonomy_guard import autonomy_summary
        s = autonomy_summary(WINDOW_HOURS)
    except Exception as exc:
        lines.append(f"_autonomy_guard unavailable: {exc}_\n")
        return "\n".join(lines)

    total = s.get("total_writes", 0)
    verdicts = s.get("verdicts", {})
    frozen = s.get("frozen", {})

    if total == 0 and not frozen:
        lines.append("_No autonomous writes in window. No frozen params._\n")
        return "\n".join(lines)

    lines.append(f"- Writes: {total}")
    lines.append(f"- Verdicts: HELPED={verdicts.get('HELPED',0)} "
                 f"NEUTRAL={verdicts.get('NEUTRAL',0)} "
                 f"HURT={verdicts.get('HURT',0)} "
                 f"PENDING={verdicts.get('PENDING',0)}")

    by_bot = s.get("by_bot", {})
    for bot, info in by_bot.items():
        params_str = ", ".join(f"{p}×{n}" for p, n in sorted(info.get("params", {}).items()))
        lines.append(f"  - {bot}: {info.get('writes',0)} writes ({params_str})")

    if frozen:
        lines.append("")
        lines.append("**Frozen (circuit breaker):**")
        for bot, params in frozen.items():
            for p, info in params.items():
                import time as _time
                remain_h = (info.get("frozen_until_ts", 0) - _time.time()) / 3600
                if remain_h > 0:
                    tag = "BOT-WIDE" if p == "__ALL__" else p
                    lines.append(f"  - {bot}/{tag}: {remain_h:.1f}h left — {info.get('reason','')}")

    return "\n".join(lines)


def build_packet() -> str:
    now_local = datetime.now()
    parts = [section_header(now_local),
             section_posture(),
             section_equity_and_positions(),
             section_kernel_status(),
             section_activity(),
             section_brain_activity(),
             section_sentinel_fires(),
             section_autonomy_activity(),
             section_open_issues()]
    body = "\n---\n\n".join(parts)
    # Derive next actions by scanning the body for signal strings
    next_actions = section_next_actions(body)
    return body + "\n---\n\n" + next_actions


def write_packet() -> str:
    packet = build_packet()
    # Ensure archive dir
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    now = datetime.now()
    archive_name = now.strftime("%Y-%m-%d_%H%M.md")
    archive_path = os.path.join(ARCHIVE_DIR, archive_name)
    # Atomic write for latest
    tmp = LATEST_PACKET + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(packet)
    os.replace(tmp, LATEST_PACKET)
    # Archive
    with open(archive_path, "w", encoding="utf-8") as f:
        f.write(packet)
    log.info("packet written: %s (archive: %s)", LATEST_PACKET, archive_name)
    return packet


# ──────────────────────────────────────────────────────────────────────
# Scheduler
# ──────────────────────────────────────────────────────────────────────

def _seconds_until_next_schedule() -> float:
    """Seconds until next 07:50 or 19:50 local."""
    now = datetime.now()
    candidates = []
    for h, m in SCHEDULE_HHMM:
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        candidates.append(target)
    next_target = min(candidates)
    return (next_target - now).total_seconds()


def main_loop() -> None:
    log.info("=" * 60)
    log.info("OPUS REVIEW — scheduled packet generator")
    log.info("Schedule: 07:50 and 19:50 local")
    log.info("Output: %s", LATEST_PACKET)
    log.info("Archive: %s", ARCHIVE_DIR)
    log.info("=" * 60)
    while True:
        sleep_s = _seconds_until_next_schedule()
        target = datetime.now() + timedelta(seconds=sleep_s)
        log.info("sleeping %.0fs until %s", sleep_s, target.strftime("%Y-%m-%d %H:%M"))
        time.sleep(sleep_s)
        try:
            write_packet()
        except Exception as exc:
            log.error("packet build failed: %s", exc, exc_info=True)
        # Sleep a minute to avoid re-firing on the same minute tick
        time.sleep(60)


def main() -> int:
    if "--now" in sys.argv:
        log.info("one-shot mode (--now)")
        write_packet()
        print("\nPacket written. Preview:")
        with open(LATEST_PACKET, encoding="utf-8") as f:
            print(f.read())
        return 0
    main_loop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

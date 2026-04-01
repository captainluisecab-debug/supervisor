"""
opus_12h_review.py — Scheduled Opus 12-hour review at 9:00 AM and 9:00 PM.

AUTHORITY MODEL:
- Governor = live command authority during the 12-hour operating period
- Opus = strategic reviewer who works in his own field (code, config, bugs)
- Opus does NOT write to governor command files
- Opus does NOT replace or override governor's live control
- Opus CAN fix minor bugs, adjust non-live config, improve code quality
- Opus reports all fixes and recommendations to the operator
- MAJOR strategy/architecture changes require operator approval
- Default on failure: HOLD / no change

Schedule: 09:00 and 21:00 local time via Windows Task Scheduler.
Cost: ~$0.10-0.30 per call. 2 calls/day max.
"""
import json
import os
import subprocess
import time
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BRIEF_FILE     = os.path.join(BASE_DIR, "governor_universe_brief.json")
REPORT_FILE    = os.path.join(BASE_DIR, "opus_12h_report.md")
DECISIONS_LOG  = os.path.join(BASE_DIR, "governor_decisions.jsonl")
OUTCOMES_LOG   = os.path.join(BASE_DIR, "brain_outcomes.jsonl")
FIX_LOG        = os.path.join(BASE_DIR, "opus_fix_log.jsonl")

# Opus fix authority: can fix minor issues in his own lane
# Does NOT touch: governor command files, live runtime, .env, policy.json
OPUS_FIX_SCOPE = {
    "allowed": [
        "code bug fixes in non-live paths",
        "log format improvements",
        "threshold adjustments within existing bounds",
        "dead code cleanup",
        "documentation updates",
    ],
    "forbidden": [
        "governor command file writes",
        "live .env changes",
        "policy.json changes",
        "strategy logic changes",
        "architecture changes",
        "position sizing changes",
        "entry/exit rule changes",
    ],
}


def read_brief():
    try:
        with open(BRIEF_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def read_recent_decisions(n=100):
    try:
        with open(DECISIONS_LOG, encoding="utf-8") as f:
            lines = f.readlines()
        return [json.loads(l.strip()) for l in lines[-n:] if l.strip()]
    except Exception:
        return []


def read_recent_outcomes(n=10):
    try:
        with open(OUTCOMES_LOG, encoding="utf-8") as f:
            lines = f.readlines()
        return [json.loads(l.strip()) for l in lines[-n:] if l.strip()]
    except Exception:
        return []


def log_fix(fix_record):
    """Log every Opus fix action for audit."""
    try:
        with open(FIX_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(fix_record) + "\n")
    except Exception:
        pass


def build_prompt(brief, decisions, outcomes):
    now = datetime.now(timezone.utc).isoformat()

    # Summarize decisions from last 12h
    twelve_h_ago = time.time() - 43200
    action_counts = {}
    for d in decisions:
        a = d.get("action", "?")
        action_counts[a] = action_counts.get(a, 0) + 1

    return f"""You are Opus, the strategic reviewer for an autonomous multi-bot trading system.
This is your scheduled 12-hour review. You receive this exactly twice daily at 9:00 AM and 9:00 PM.

AUTHORITY MODEL:
- Governor handles ALL live command decisions during the 12-hour operating period.
- You do NOT write to governor command files or override governor's live control.
- You work in YOUR OWN FIELD: code quality, bug fixes, threshold corrections, documentation.
- You may fix MINOR issues (bugs, log cleanup, threshold tweaks within bounds) and report them.
- MAJOR changes (strategy logic, architecture, config/policy rewrites) require operator approval.
- Default on uncertainty: HOLD / no change.

YOUR ALLOWED FIX SCOPE:
{json.dumps(OPUS_FIX_SCOPE["allowed"], indent=2)}

YOUR FORBIDDEN SCOPE:
{json.dumps(OPUS_FIX_SCOPE["forbidden"], indent=2)}

CURRENT UNIVERSE STATE:
{json.dumps(brief, indent=2)}

GOVERNOR DECISION SUMMARY (last 12h):
{json.dumps(action_counts, indent=2)}

RECENT BRAIN OUTCOMES:
{json.dumps(outcomes[-5:], indent=2) if outcomes else "No recent outcomes."}

BRAIN ADVISORY (last cycle):
{brief.get("brain_advisory", "none")}

YOUR TASK:
1. Review the last 12 hours of governor and system behavior.
2. Identify any loopholes, bugs, communication issues, or missed opportunities that are blocking positive trend.
3. For each issue, classify as:
   - MINOR: you may fix it now in your own lane and report the fix
   - MAJOR: requires operator approval — describe the fix but do not execute
4. Focus on what would improve the system's ability to capture positive PnL trend.
5. Produce a clear operator status report.

If nothing materially changed: report "No material change. System operating as designed."

RESPOND IN THIS EXACT FORMAT:

## UNIVERSE STATUS
(2-3 sentences: current state, direction, main risk)

## ISSUES FOUND
(numbered list, or "None")

## FIXES APPLIED (MINOR — in my lane)
(numbered list with: what was wrong, what I fixed, expected benefit, rollback path — or "None")

## FIXES RECOMMENDED (MAJOR — needs operator approval)
(numbered list with: what is wrong, what should change, expected benefit, risk — or "None")

## OPERATOR ACTION NEEDED
(yes/no + specific action items if yes)

## NEXT 12H OUTLOOK
(1-2 sentences: what to expect, what to watch)
"""


def call_opus(prompt):
    """Call Opus via claude CLI."""
    try:
        result = subprocess.run(
            ["claude", "-p", "--bare", "--model", "opus"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        else:
            return f"ERROR: claude returned code {result.returncode}\n{result.stderr[:500]}"
    except FileNotFoundError:
        return "ERROR: claude CLI not found in PATH"
    except subprocess.TimeoutExpired:
        return "ERROR: claude call timed out after 180s"
    except Exception as exc:
        return f"ERROR: {exc}"


def write_report(response, brief):
    """Write the Opus report as markdown for operator review."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    regime = brief.get("dominant_regime", "?")
    posture = brief.get("effective_posture", {})
    k_eq = brief.get("kraken", {}).get("equity", 0)
    k_dd = brief.get("kraken", {}).get("dd_pct", 0)
    s_eq = brief.get("sfm", {}).get("equity", 0)
    a_eq = brief.get("alpaca", {}).get("equity", 0)

    report = f"""# Opus 12-Hour Review - {now}

## Snapshot
| Metric | Value |
|--------|-------|
| Regime | {regime} |
| Posture | {json.dumps(posture)} |
| Kraken | ${k_eq:.2f} (DD {k_dd:.1f}%) |
| SFM | ${s_eq:.2f} |
| Alpaca | ${a_eq:.2f} |

---

{response}

---
*Generated by opus_12h_review.py*
*Authority: Governor = live control. Opus = strategic review + minor fixes.*
*Next review in 12 hours.*
"""
    try:
        with open(REPORT_FILE, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"Report written to {REPORT_FILE}")
    except Exception as exc:
        print(f"Failed to write report: {exc}")


def main():
    ts = datetime.now(timezone.utc).isoformat()
    print(f"[OPUS 12H REVIEW] Starting at {ts}")

    brief = read_brief()
    if not brief:
        print("[OPUS 12H REVIEW] No universe brief found. Governor may not be running.")
        write_report("ERROR: No governor universe brief available. Cannot review.", {})
        return

    decisions = read_recent_decisions(100)
    outcomes = read_recent_outcomes(10)

    prompt = build_prompt(brief, decisions, outcomes)
    print(f"[OPUS 12H REVIEW] Prompt built ({len(prompt)} chars). Calling Opus...")

    response = call_opus(prompt)
    print(f"[OPUS 12H REVIEW] Response received ({len(response)} chars)")

    # Log the review event
    log_fix({
        "ts": ts,
        "type": "12h_review",
        "prompt_chars": len(prompt),
        "response_chars": len(response),
        "brief_regime": brief.get("dominant_regime", "?"),
    })

    write_report(response, brief)
    print(f"[OPUS 12H REVIEW] Complete. Report at {REPORT_FILE}")


if __name__ == "__main__":
    main()

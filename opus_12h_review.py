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
PNL_SNAPSHOT   = os.path.join(BASE_DIR, "opus_pnl_snapshot.json")
REVIEW_MEMORY  = os.path.join(BASE_DIR, "opus_review_memory.json")
REVIEW_WINDOW  = r"C:\Projects\memory\.locks\opus_review_window.active"

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


def read_review_memory():
    """Read persistent memory from the last 12h review."""
    try:
        if os.path.exists(REVIEW_MEMORY):
            with open(REVIEW_MEMORY, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"issues_identified": [], "issues_fixed": [], "issues_deferred": [],
            "issues_active": [], "last_regime": None, "last_pnl": None, "cycle_count": 0}


def save_review_memory(memory):
    """Save persistent memory for the next 12h review."""
    try:
        with open(REVIEW_MEMORY, "w", encoding="utf-8") as f:
            json.dump(memory, f, indent=2)
    except Exception:
        pass


def read_previous_pnl():
    """Read the PnL snapshot from the last 12h review."""
    try:
        if os.path.exists(PNL_SNAPSHOT):
            with open(PNL_SNAPSHOT, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return None


def save_pnl_snapshot(brief):
    """Save current PnL for comparison in the next 12h review."""
    snapshot = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "universe_equity": (
            brief.get("kraken", {}).get("equity", 0) +
            brief.get("sfm", {}).get("equity", 0) +
            brief.get("alpaca", {}).get("equity", 0)
        ),
        "kraken_equity": brief.get("kraken", {}).get("equity", 0),
        "sfm_equity": brief.get("sfm", {}).get("equity", 0),
        "alpaca_equity": brief.get("alpaca", {}).get("equity", 0),
        "kraken_dd": brief.get("kraken", {}).get("dd_pct", 0),
    }
    try:
        with open(PNL_SNAPSHOT, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2)
    except Exception:
        pass
    return snapshot


def log_fix(fix_record):
    """Log every Opus fix action for audit."""
    try:
        with open(FIX_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(fix_record) + "\n")
    except Exception:
        pass


def _get_recent_commits():
    """Get last 5 git commits across all repos for context."""
    commits = []
    for repo, name in [
        (r"C:\Projects\enzobot", "enzobot"),
        (r"C:\Projects\sfmbot", "sfmbot"),
        (r"C:\Projects\alpacabot", "alpacabot"),
        (r"C:\Projects\supervisor", "supervisor"),
    ]:
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", "-3"],
                capture_output=True, text=True, timeout=10, cwd=repo,
            )
            for line in result.stdout.strip().splitlines()[:3]:
                commits.append(f"  [{name}] {line.strip()}")
        except Exception:
            pass
    return "\n".join(commits[-10:]) if commits else "  No recent commits found."


def build_prompt(brief, decisions, outcomes, prev_pnl, current_pnl, review_memory=None):
    now = datetime.now(timezone.utc).isoformat()

    # Summarize decisions from last 12h
    action_counts = {}
    for d in decisions:
        a = d.get("action", "?")
        action_counts[a] = action_counts.get(a, 0) + 1

    recent_commits = _get_recent_commits()

    # PnL delta computation
    if prev_pnl:
        universe_delta = current_pnl["universe_equity"] - prev_pnl.get("universe_equity", current_pnl["universe_equity"])
        kraken_delta = current_pnl["kraken_equity"] - prev_pnl.get("kraken_equity", current_pnl["kraken_equity"])
        sfm_delta = current_pnl["sfm_equity"] - prev_pnl.get("sfm_equity", current_pnl["sfm_equity"])
        alpaca_delta = current_pnl["alpaca_equity"] - prev_pnl.get("alpaca_equity", current_pnl["alpaca_equity"])
        pnl_context = f"""PNL DELTA (vs 12 hours ago):
  Universe: ${universe_delta:+.2f} ({'better' if universe_delta > 0 else 'worse' if universe_delta < 0 else 'flat'})
  Kraken:   ${kraken_delta:+.2f}
  SFM:      ${sfm_delta:+.2f}
  Alpaca:   ${alpaca_delta:+.2f}
  Previous snapshot: {prev_pnl.get('ts', '?')}"""
    else:
        pnl_context = "PNL DELTA: No previous snapshot. This is the first review with PnL tracking."

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

{pnl_context}

CURRENT PNL:
  Universe equity: ${current_pnl['universe_equity']:.2f}
  Universe PnL vs baseline ($6,969.62): ${current_pnl['universe_equity'] - 6969.62:+.2f}
  Kraken: ${current_pnl['kraken_equity']:.2f} (DD {current_pnl.get('kraken_dd', 0):.1f}%)
  SFM: ${current_pnl['sfm_equity']:.2f}
  Alpaca: ${current_pnl['alpaca_equity']:.2f}

GOVERNOR DECISION SUMMARY (last 12h):
{json.dumps(action_counts, indent=2)}

RECENT BRAIN OUTCOMES:
{json.dumps(outcomes[-5:], indent=2) if outcomes else "No recent outcomes."}

BRAIN ADVISORY (last cycle):
{brief.get("brain_advisory", "none")}

PERSISTENT REVIEW MEMORY (from your last 12h review — use this to avoid re-raising resolved issues):
  Review cycle: #{review_memory.get('cycle_count', 0) + 1 if review_memory else 1}
  Issues previously identified: {json.dumps(review_memory.get('issues_identified', []))}
  Issues previously fixed: {json.dumps(review_memory.get('issues_fixed', []))}
  Issues deferred: {json.dumps(review_memory.get('issues_deferred', []))}
  Issues still active: {json.dumps(review_memory.get('issues_active', []))}
  Last regime: {review_memory.get('last_regime', '?') if review_memory else '?'}

RECENT CODE CHANGES (last 3 commits per repo — do NOT re-raise issues already fixed):
{recent_commits}

IMPORTANT: Before flagging any issue, check whether a recent commit already addresses it.
If a fix was already deployed, report it as RESOLVED, not as a current issue.
Only flag issues that are STILL PRESENT in the current running code.

YOUR TASK:
1. Review the last 12 hours of governor and system behavior.
2. Identify any loopholes, bugs, communication issues, or missed opportunities blocking positive trend.
3. For each issue, classify as:
   - MINOR: FIX IT NOW using your file tools (Read/Edit/Write). You have execution authority on minor fixes. Then report what you fixed.
   - MAJOR: requires operator approval — describe the fix but do NOT execute it.
4. Focus on what would improve the system's ability to capture positive PnL trend.
5. After making any fixes, produce a clear operator status report.

You have tool access to read and edit Python files across all bot directories.
You may NOT write to: command files (*_cmd.json), .env, policy.json, brain_state.json, or any runtime state file.
You may NOT restart services. Fixes take effect on next natural restart.

CLOSURE DISCIPLINE:
- Do NOT mark any fix as complete unless you have verified it end-to-end.
- For each fix you apply, verify: the file compiles, the logic is correct, the expected behavior would occur.
- If you cannot verify a fix, mark it as "applied but unverified" and explain what needs checking.
- Do NOT re-raise issues from "issues_fixed" in your persistent memory unless you have NEW evidence they are broken again.

If nothing materially changed: report "No material change."

RESPOND IN THIS EXACT MANDATORY FORMAT (all sections required, every 12 hours, 7 days/week):

## 1. PNL REPORT
| Metric | Value |
|--------|-------|
| Universe equity now | $X |
| Universe PnL (vs $6,969.62 baseline) | $X |
| Delta vs 12 hours ago | $X (better/flat/worse) |
| Kraken delta | $X |
| SFM delta | $X |
| Alpaca delta | $X |

## 2. UNIVERSE STATUS
(2-3 sentences: current state, direction, main risk)

## 3. ISSUES FOUND
For each issue, label its status:
- ACTIVE: still present and unresolved
- RESOLVED: fixed in this or a prior cycle
- BLOCKED: cannot fix without operator approval
- DEFERRED: known but not priority
(numbered list with status labels, or "None")

## 4. FIXES APPLIED (MINOR — in my lane)
For each fix:
- what was wrong
- exact file(s) changed
- what I fixed
- expected benefit
- rollback path
Or: "None"

## 5. FIXES RECOMMENDED (MAJOR — needs operator approval)
For each:
- what is wrong
- what should change
- expected benefit
- risk
Or: "None"

## 6. POSITIVE TREND BLOCKER
- What prevented sleeves from improving positive trend in the last 12h?
- Which sleeve was most blocked?
- Blocker type: market / strategy / governor / command / bug / capital-limit
- Single biggest blocker:
- Blocker status: already fixed / still active / needs approval

## 7. OPERATOR ACTION NEEDED
(yes/no + specific action items if yes)

## 8. OPERATOR BOTTOM LINE
One line: better / flat / worse vs last 12h, and why.

## 9. NEXT 12H OUTLOOK
(1-2 sentences: what to expect, what to watch)
"""


def call_opus(prompt):
    """Call Opus via claude CLI with tool access for minor fixes.
    Uses claude -p (not --bare) so Opus can Read/Write/Edit files
    for minor fixes in its own lane. Does not have access to governor
    command files or live runtime state files."""
    try:
        result = subprocess.run(
            ["claude", "-p", "--model", "opus"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=600,  # 10 min — Opus may need to read/write files
            cwd=BASE_DIR,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        else:
            return f"ERROR: claude returned code {result.returncode}\n{result.stderr[:500]}"
    except FileNotFoundError:
        return "ERROR: claude CLI not found in PATH"
    except subprocess.TimeoutExpired:
        return "ERROR: claude call timed out after 600s"
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
    prev_pnl = read_previous_pnl()
    current_pnl = save_pnl_snapshot(brief)
    review_memory = read_review_memory()

    prompt = build_prompt(brief, decisions, outcomes, prev_pnl, current_pnl, review_memory)
    print(f"[OPUS 12H REVIEW] Prompt built ({len(prompt)} chars). Calling Opus...")

    # Open Opus review window — allows writes to bot files during this call only
    try:
        os.makedirs(os.path.dirname(REVIEW_WINDOW), exist_ok=True)
        with open(REVIEW_WINDOW, "w") as f:
            f.write(f"opus_12h_review active since {ts}")
        print(f"[OPUS 12H REVIEW] Review window opened")
    except Exception as exc:
        print(f"[OPUS 12H REVIEW] WARNING: could not open review window: {exc}")

    try:
        response = call_opus(prompt)
    finally:
        # Always close the review window, even on error
        try:
            if os.path.exists(REVIEW_WINDOW):
                os.remove(REVIEW_WINDOW)
                print(f"[OPUS 12H REVIEW] Review window closed")
        except Exception:
            pass
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

    # Update persistent memory for next cycle
    review_memory["cycle_count"] = review_memory.get("cycle_count", 0) + 1
    review_memory["last_regime"] = brief.get("dominant_regime", "?")
    review_memory["last_pnl"] = current_pnl.get("universe_equity", 0)
    save_review_memory(review_memory)

    print(f"[OPUS 12H REVIEW] Complete. Report at {REPORT_FILE}")


if __name__ == "__main__":
    main()

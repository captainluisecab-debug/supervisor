"""
supervisor_selfheal.py — Opus-powered self-healing engine.

When anomalies are detected, this module:
1. Builds a diagnostic prompt with full anomaly context
2. Calls Opus to diagnose and prescribe specific remediation actions
3. Executes approved actions within safe guardrails
4. Logs every action to selfheal_log.jsonl for audit trail

Opus can prescribe:
  - adjust_policy_json  : change a value in enzobot/policy.json
  - adjust_env          : change an env var in a bot's .env file
  - clear_lock          : delete a stale lock file
  - write_supervisor_cmd: push a mode command to a bot
  - restart_bot         : write a restart flag file
  - alert_human         : escalate — log critical alert, do not auto-fix

All changes are bounded by SAFE_BOUNDS. Anything outside bounds is rejected.
Every action is logged to selfheal_log.jsonl.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from typing import List, Optional

from supervisor_anomaly import Anomaly, AnomalyReport
from supervisor_settings import COMMANDS_DIR

log = logging.getLogger("supervisor_selfheal")

ENZOBOT_DIR   = r"C:\Projects\enzobot"
SFMBOT_DIR    = r"C:\Projects\sfmbot"
ALPACA_DIR    = r"C:\Projects\alpacabot"
SUPERVISOR_DIR = os.path.dirname(os.path.abspath(__file__))

SELFHEAL_LOG  = os.path.join(SUPERVISOR_DIR, "selfheal_log.jsonl")

# ── Safe bounds — Opus cannot set values outside these ───────────────
# Split by executor: policy keys must not pass through the env executor and vice versa.
POLICY_SAFE_BOUNDS = {
    # policy.json — attack_rules
    "attack_rules.max_dd_pct":         (2.0,  8.0),
    "attack_rules.max_daily_loss_pct": (1.0,  5.0),
    # policy.json — defend_rules
    "defend_rules.dd_pct_trigger":     (4.0, 12.0),
}

ENV_SAFE_BOUNDS = {
    # .env variables
    "ADX_MIN_ENTRY":      (8.0,  20.0),
    "MIN_SCORE_TO_TRADE": (48.0, 70.0),
    "SCORE_DROP_EXIT":    (4.0,  15.0),
}

# Cooldown: don't self-heal the same anomaly code twice within N minutes
HEAL_COOLDOWN_MIN = 30
_last_healed: dict[str, float] = {}


def _on_cooldown(code: str) -> bool:
    last = _last_healed.get(code, 0)
    return (time.time() - last) < HEAL_COOLDOWN_MIN * 60


def _mark_healed(code: str):
    _last_healed[code] = time.time()


# ── Prompt builder ────────────────────────────────────────────────────

def _build_prompt(report: AnomalyReport, portfolio_summary: str, regime_summary: str) -> str:
    anomaly_text = "\n".join(
        f"  [{a.severity}] {a.code}: {a.description}\n  data={json.dumps(a.data)}"
        for a in report.anomalies
    )

    return f"""You are the self-healing engine for an autonomous multi-bot trading ecosystem.
Anomalies have been detected. Diagnose them and prescribe precise remediation actions.

═══════════════════════════════════════════
ANOMALIES DETECTED  [{report.ts}]
═══════════════════════════════════════════
{anomaly_text}

═══════════════════════════════════════════
PORTFOLIO CONTEXT
═══════════════════════════════════════════
{portfolio_summary}

═══════════════════════════════════════════
MARKET REGIME
═══════════════════════════════════════════
{regime_summary}

═══════════════════════════════════════════
AVAILABLE ACTIONS
═══════════════════════════════════════════
You may prescribe any combination of these actions:

1. adjust_policy_json
   Modify a value in enzobot/policy.json.
   Safe keys: attack_rules.max_dd_pct (2.0-8.0), attack_rules.max_daily_loss_pct (1.0-5.0),
              defend_rules.dd_pct_trigger (4.0-12.0)
   Example: {{"type":"adjust_policy_json","key":"attack_rules.max_dd_pct","value":5.5,"reason":"..."}}

2. adjust_env
   Modify an environment variable in a bot's .env file. Requires bot restart.
   Safe keys: ADX_MIN_ENTRY (8-20), MIN_SCORE_TO_TRADE (48-70), SCORE_DROP_EXIT (4-15)
   Example: {{"type":"adjust_env","bot":"enzobot","key":"ADX_MIN_ENTRY","value":"12","reason":"..."}}

3. clear_lock
   Delete a stale lock file so a crashed bot can restart.
   Example: {{"type":"clear_lock","bot":"enzobot","reason":"..."}}

4. write_supervisor_cmd
   Push a mode command to a bot (overrides current mode for 1 brain cycle).
   Modes: NORMAL, SCOUT, DEFENSE. size_mult: 0.3-1.3.
   Example: {{"type":"write_supervisor_cmd","bot":"kraken","mode":"NORMAL","size_mult":0.8,"entry_allowed":true,"reason":"..."}}

5. restart_bot
   Signal a bot to restart cleanly (writes a restart flag file).
   Use only if cycle is frozen or lock is stale and already cleared.
   Example: {{"type":"restart_bot","bot":"enzobot","reason":"..."}}

6. alert_human
   Escalate an issue that cannot be auto-fixed. Always include clear description.
   Example: {{"type":"alert_human","severity":"HIGH","message":"...","reason":"..."}}

═══════════════════════════════════════════
RULES
═══════════════════════════════════════════
- Only prescribe actions that directly address the detected anomalies
- For ADX_THRESHOLD_TOO_HIGH: lower ADX_MIN_ENTRY by 2-3 points, not more
- For ATTACK_DD_TOO_TIGHT: verify the DD figure matches supervisor_report.json sleeve drawdown_pct before acting. Only raise attack_rules.max_dd_pct by 1-2 points if the DD is confirmed from that trusted source. Never recommend resetting the DD baseline or HWM unless DD is confirmed from supervisor_report.json
- For BRAIN_CHURN: do NOT write another DEFENSE/HOLD command — DEFENSE blocks entries but does not stop the internal Enzobot parameter loop (paper_boss_v1), which continues thrashing regardless. Instead, use alert_human with severity MEDIUM. Include the changes_today count, confirm that DEFENSE cannot resolve parameter thrashing, and state that a policy-level fix is required.
- For STALE_LOCK: clear_lock first, then restart_bot if cycle is frozen
- For CYCLE_FROZEN: restart_bot only after verifying lock is cleared
- For ENTRY_DROUGHT without other anomalies: do NOT force entries — market may just be choppy
- Never set attack_max_dd above 6.0 or ADX_MIN_ENTRY below 10.0
- Prefer minimal interventions — one targeted action beats three broad ones
- If unsure, use alert_human rather than guessing

Respond ONLY with valid JSON:
{{
  "diagnosis": "2-3 sentence explanation of root cause",
  "priority": "HIGH|MEDIUM|LOW",
  "actions": [
    {{action objects as defined above}}
  ]
}}"""


# ── Action executor ───────────────────────────────────────────────────

def _log_action(action: dict, result: str, cycle: int):
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "cycle": cycle,
        "action": action,
        "result": result,
    }
    try:
        with open(SELFHEAL_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as exc:
        log.warning("[SELFHEAL] Could not write to selfheal_log: %s", exc)


def _execute_adjust_policy_json(action: dict, cycle: int):
    key   = action.get("key", "")
    value = action.get("value")
    reason = action.get("reason", "")

    if key not in POLICY_SAFE_BOUNDS:
        msg = f"REJECTED: key '{key}' not in policy safe bounds list"
        log.warning("[SELFHEAL] %s", msg)
        _log_action(action, msg, cycle)
        return

    lo, hi = POLICY_SAFE_BOUNDS[key]
    try:
        value = float(value)
    except Exception:
        msg = f"REJECTED: value '{value}' not numeric"
        log.warning("[SELFHEAL] %s", msg)
        _log_action(action, msg, cycle)
        return

    if not (lo <= value <= hi):
        value = max(lo, min(hi, value))
        log.warning("[SELFHEAL] Value clamped to bounds [%.1f, %.1f] → %.1f", lo, hi, value)

    path = os.path.join(ENZOBOT_DIR, "policy.json")
    try:
        with open(path, encoding="utf-8") as f:
            policy = json.load(f)

        # Navigate nested key (e.g. "attack_rules.max_dd_pct")
        parts = key.split(".")
        obj = policy
        for part in parts[:-1]:
            obj = obj.setdefault(part, {})
        old_val = obj.get(parts[-1])
        obj[parts[-1]] = value

        with open(path, "w", encoding="utf-8") as f:
            json.dump(policy, f, indent=2)

        msg = f"OK: {key} {old_val} → {value} | {reason}"
        log.info("[SELFHEAL] policy.json: %s", msg)
        _log_action(action, msg, cycle)

    except Exception as exc:
        msg = f"ERROR: {exc}"
        log.error("[SELFHEAL] Failed to adjust policy.json: %s", exc)
        _log_action(action, msg, cycle)


_ENV_ACTION_COUNT = {"count": 0, "day": ""}

def _execute_adjust_env(action: dict, cycle: int):
    today = time.strftime("%Y-%m-%d")
    if _ENV_ACTION_COUNT["day"] != today:
        _ENV_ACTION_COUNT["count"] = 0
        _ENV_ACTION_COUNT["day"] = today
    if _ENV_ACTION_COUNT["count"] >= 3:
        log.warning("[SELFHEAL] adjust_env RATE LIMITED (3/day max)")
        _log_action(action, "RATE LIMITED — 3/day max reached", cycle)
        return
    _ENV_ACTION_COUNT["count"] += 1

    bot    = action.get("bot", "enzobot")
    key    = action.get("key", "")
    value  = str(action.get("value", ""))
    reason = action.get("reason", "")

    if key not in ENV_SAFE_BOUNDS:
        msg = f"REJECTED: env key '{key}' not in env safe bounds list"
        log.warning("[SELFHEAL] %s", msg)
        _log_action(action, msg, cycle)
        return

    lo, hi = ENV_SAFE_BOUNDS[key]
    try:
        num_val = float(value)
        num_val = max(lo, min(hi, num_val))
        value   = str(int(num_val)) if num_val == int(num_val) else str(num_val)
    except Exception:
        pass

    bot_dirs = {"enzobot": ENZOBOT_DIR, "sfmbot": SFMBOT_DIR, "alpacabot": ALPACA_DIR}
    env_path = os.path.join(bot_dirs.get(bot, ENZOBOT_DIR), ".env")

    try:
        with open(env_path, encoding="utf-8") as f:
            lines = f.readlines()

        found = False
        new_lines = []
        for line in lines:
            if line.strip().startswith(f"{key}="):
                new_lines.append(f"{key}={value}\n")
                found = True
            else:
                new_lines.append(line)

        if not found:
            new_lines.append(f"{key}={value}\n")

        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

        # RESTART FLAG REMOVED (2026-03-25): adjust_env was writing restart flags
        # that bypassed the restart_bot suppression, causing a restart loop that
        # prevented stable mode transitions. The .env change is written and will
        # take effect on the next organic restart. No forced restart.
        msg = f"OK: {bot} .env {key}={value} | {reason} | no restart (suppressed)"
        log.info("[SELFHEAL] env: %s", msg)
        _log_action(action, msg, cycle)

    except Exception as exc:
        msg = f"ERROR: {exc}"
        log.error("[SELFHEAL] Failed to adjust .env: %s", exc)
        _log_action(action, msg, cycle)


def _execute_clear_lock(action: dict, cycle: int):
    bot    = action.get("bot", "enzobot")
    reason = action.get("reason", "")

    lock_map = {
        "enzobot":  os.path.join(ENZOBOT_DIR,  "enzobot.lock"),
        "sfmbot":   os.path.join(SFMBOT_DIR,   "sfmbot.lock"),
        "alpacabot":os.path.join(ALPACA_DIR,   "alpacabot.lock"),
    }
    path = lock_map.get(bot)
    if not path:
        _log_action(action, f"REJECTED: unknown bot '{bot}'", cycle)
        return

    if os.path.exists(path):
        try:
            os.remove(path)
            msg = f"OK: cleared {os.path.basename(path)} | {reason}"
            log.info("[SELFHEAL] lock: %s", msg)
            _log_action(action, msg, cycle)
        except Exception as exc:
            msg = f"ERROR: {exc}"
            log.error("[SELFHEAL] Failed to clear lock: %s", exc)
            _log_action(action, msg, cycle)
    else:
        msg = "SKIP: lock file does not exist"
        log.info("[SELFHEAL] lock: %s", msg)
        _log_action(action, msg, cycle)


_CMD_ACTION_COUNT = {"count": 0, "day": ""}

def _execute_write_supervisor_cmd(action: dict, cycle: int):
    today = time.strftime("%Y-%m-%d")
    if _CMD_ACTION_COUNT["day"] != today:
        _CMD_ACTION_COUNT["count"] = 0
        _CMD_ACTION_COUNT["day"] = today
    if _CMD_ACTION_COUNT["count"] >= 2:
        log.warning("[SELFHEAL] write_supervisor_cmd RATE LIMITED (2/day max)")
        _log_action(action, "RATE LIMITED — 2/day max reached", cycle)
        return
    _CMD_ACTION_COUNT["count"] += 1

    # Normalize bot name — Opus may return "enzobot"/"sfmbot"/"alpacabot"
    _bot_alias = {"enzobot": "kraken", "sfmbot": "sfm", "alpacabot": "alpaca"}
    bot    = _bot_alias.get(action.get("bot", "kraken"), action.get("bot", "kraken"))
    mode   = action.get("mode", "SCOUT")
    size   = float(action.get("size_mult", 0.5))
    entry  = bool(action.get("entry_allowed", True))
    reason = action.get("reason", "selfheal")

    if mode not in ("NORMAL", "SCOUT", "DEFENSE"):
        mode = "SCOUT"
    size = max(0.3, min(1.3, size))

    file_map = {
        "kraken":  os.path.join(COMMANDS_DIR, "kraken_cmd.json"),
        "sfm":     os.path.join(COMMANDS_DIR, "sfm_cmd.json"),
        "alpaca":  os.path.join(COMMANDS_DIR, "alpaca_cmd.json"),
    }
    path = file_map.get(bot)
    if not path:
        _log_action(action, f"REJECTED: unknown bot '{bot}'", cycle)
        return

    cmd = {
        "mode": mode,
        "size_mult": size,
        "entry_allowed": entry,
        "reasoning": f"[SELFHEAL] {reason}",
        "bot": bot,
        "ts": datetime.now(timezone.utc).isoformat(),
        "source": "supervisor_selfheal",
    }
    try:
        os.makedirs(COMMANDS_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cmd, f, indent=2)
        msg = f"OK: {bot} → {mode} {size:.1f}x | {reason}"
        log.info("[SELFHEAL] cmd: %s", msg)
        _log_action(action, msg, cycle)
    except Exception as exc:
        msg = f"ERROR: {exc}"
        log.error("[SELFHEAL] Failed to write cmd: %s", exc)
        _log_action(action, msg, cycle)


_RESTART_ACTION_COUNT = {"count": 0, "day": ""}

def _execute_restart_bot(action: dict, cycle: int):
    bot    = action.get("bot", "enzobot")
    reason = action.get("reason", "selfheal")

    today = time.strftime("%Y-%m-%d")
    if _RESTART_ACTION_COUNT["day"] != today:
        _RESTART_ACTION_COUNT["count"] = 0
        _RESTART_ACTION_COUNT["day"] = today
    if _RESTART_ACTION_COUNT["count"] >= 3:
        log.warning("[SELFHEAL] restart_bot RATE LIMITED (3/day max) — escalating to human")
        _log_action(action, "RATE LIMITED — 3 restarts/day max. Escalating.", cycle)
        _execute_alert_human({"severity": "HIGH", "message": f"restart_bot for {bot} exceeded 3/day limit",
                              "reason": reason}, cycle)
        return
    _RESTART_ACTION_COUNT["count"] += 1

    bot_dirs = {"enzobot": ENZOBOT_DIR, "sfmbot": SFMBOT_DIR, "alpacabot": ALPACA_DIR}
    bot_dir  = bot_dirs.get(bot, ENZOBOT_DIR)
    flag     = os.path.join(bot_dir, "RESTART_REQUESTED.flag")

    try:
        with open(flag, "w") as f:
            f.write(f"selfheal_restart:{reason}")
        msg = f"OK: restart flag written for {bot} | {reason}"
        log.info("[SELFHEAL] restart: %s", msg)
        _log_action(action, msg, cycle)
    except Exception as exc:
        msg = f"ERROR: {exc}"
        log.error("[SELFHEAL] Failed to write restart flag: %s", exc)
        _log_action(action, msg, cycle)


def _execute_alert_human(action: dict, cycle: int):
    severity = action.get("severity", "HIGH")
    message  = action.get("message", "")
    reason   = action.get("reason", "")
    msg = f"HUMAN ALERT [{severity}]: {message} | {reason}"
    log.warning("[SELFHEAL] %s", msg)
    _log_action(action, f"ALERT RAISED: {msg}", cycle)


# ── Opus diagnosis ───────────────────────────────────────────────────

_OPUS_SELFHEAL_COOLDOWN = 1800  # 30 min between Opus calls
_OPUS_SELFHEAL_LAST_TS = 0
_OPUS_SELFHEAL_ACTIONS_TODAY = {"count": 0, "day": ""}

EXECUTOR_MAP = {
    "adjust_policy_json":   _execute_adjust_policy_json,
    "adjust_env":           _execute_adjust_env,
    "clear_lock":           _execute_clear_lock,
    "write_supervisor_cmd": _execute_write_supervisor_cmd,
    "restart_bot":          _execute_restart_bot,
    "alert_human":          _execute_alert_human,
}


def _call_opus_diagnosis(prompt: str) -> Optional[dict]:
    try:
        api_key = ""
        env_path = os.path.join(SUPERVISOR_DIR, ".env")
        if os.path.exists(env_path):
            for line in open(env_path, encoding="utf-8"):
                if line.strip().startswith("ANTHROPIC_API_KEY="):
                    api_key = line.strip().split("=", 1)[1].strip().strip('"').strip("'")
        if not api_key:
            return None
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
    except Exception as exc:
        log.error("[SELFHEAL] Opus diagnosis failed: %s", exc)
        return None


# ── Main entry point ──────────────────────────────────────────────────

def run_selfheal(report: AnomalyReport, portfolio_summary: str,
                 regime_summary: str, cycle: int) -> int:
    """
    Phase 2: Opus-powered diagnosis + rate-limited execution.
    Returns number of actions executed.
    """
    global _OPUS_SELFHEAL_LAST_TS

    if not report.anomalies:
        return 0

    active = [a for a in report.anomalies if not _on_cooldown(a.code)]
    if not active:
        return 0

    # Dedup: only log NEW anomalies
    if not hasattr(run_selfheal, "_prev_active_codes"):
        run_selfheal._prev_active_codes = set()
    current_codes = {a.code for a in active}
    new_codes = current_codes - run_selfheal._prev_active_codes

    for a in active:
        if a.code in new_codes:
            log.warning("[SELFHEAL] NEW ANOMALY: %s -- %s", a.code, a.description[:120])
        _mark_healed(a.code)
    run_selfheal._prev_active_codes = current_codes

    # Rate limit: Opus call max every 30 min, max 6 total actions/day
    today = time.strftime("%Y-%m-%d")
    if _OPUS_SELFHEAL_ACTIONS_TODAY["day"] != today:
        _OPUS_SELFHEAL_ACTIONS_TODAY["count"] = 0
        _OPUS_SELFHEAL_ACTIONS_TODAY["day"] = today

    if _OPUS_SELFHEAL_ACTIONS_TODAY["count"] >= 6:
        log.info("[SELFHEAL] Daily action limit (6) reached — detect only")
        _log_action({"type": "rate_limited"}, "DAILY LIMIT — 6 actions/day", cycle)
        return 0

    elapsed = time.time() - _OPUS_SELFHEAL_LAST_TS
    if elapsed < _OPUS_SELFHEAL_COOLDOWN and not new_codes:
        return 0

    if not new_codes:
        return 0

    # Call Opus for diagnosis
    prompt = _build_prompt(report, portfolio_summary, regime_summary)
    log.info("[SELFHEAL] Calling Opus for diagnosis (%d active anomalies)", len(active))
    diagnosis = _call_opus_diagnosis(prompt)

    if not diagnosis:
        _log_action({"type": "opus_call_failed"}, "Opus diagnosis returned None", cycle)
        return 0

    _OPUS_SELFHEAL_LAST_TS = time.time()

    actions = diagnosis.get("actions", [])
    diag_text = diagnosis.get("diagnosis", "")
    priority = diagnosis.get("priority", "MEDIUM")
    log.info("[SELFHEAL] Opus diagnosis: %s (priority=%s, %d actions)", diag_text[:100], priority, len(actions))
    _log_action({"type": "opus_diagnosis", "diagnosis": diag_text, "priority": priority,
                 "action_count": len(actions)}, f"DIAGNOSED — {len(actions)} actions prescribed", cycle)

    executed = 0
    for action in actions:
        action_type = action.get("type", "")
        executor = EXECUTOR_MAP.get(action_type)
        if not executor:
            log.warning("[SELFHEAL] Unknown action type: %s", action_type)
            _log_action(action, f"REJECTED — unknown action type '{action_type}'", cycle)
            continue
        log.info("[SELFHEAL] Executing: %s", json.dumps(action)[:150])
        executor(action, cycle)
        executed += 1
        _OPUS_SELFHEAL_ACTIONS_TODAY["count"] += 1

    return executed

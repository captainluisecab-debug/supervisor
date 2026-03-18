"""
supervisor_telegram.py — Telegram remote access for the supervisor.

Provides:
  - Push alerts: anomalies, kill switch, regime changes, morning brief
  - Commands: /status /regime /brief /mode /selfheal /stop /help

Uses the Telegram Bot API directly via requests (no extra library).
Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env to enable.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

import requests

import supervisor_settings as S

log = logging.getLogger(__name__)

_enabled = bool(S.TELEGRAM_BOT_TOKEN and S.TELEGRAM_CHAT_ID)
_BASE_URL = f"https://api.telegram.org/bot{S.TELEGRAM_BOT_TOKEN}"
_last_update_id = 0


# ── Public API ──────────────────────────────────────────────────────────────

def send_alert(text: str) -> None:
    """Send a push message to the configured Telegram chat."""
    if not _enabled:
        return
    try:
        requests.post(
            f"{_BASE_URL}/sendMessage",
            json={"chat_id": S.TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        log.warning("Telegram send_alert failed: %s", e)


def start_telegram_bot() -> None:
    """Start the Telegram command polling loop in a background daemon thread."""
    if not _enabled:
        log.info("Telegram bot disabled — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")
        return
    t = threading.Thread(target=_poll_loop, daemon=True, name="telegram-poll")
    t.start()
    log.info("Telegram bot started (chat_id=%s)", S.TELEGRAM_CHAT_ID)


# ── Polling loop ────────────────────────────────────────────────────────────

def _poll_loop() -> None:
    global _last_update_id
    while True:
        try:
            updates = _get_updates(_last_update_id + 1)
            for upd in updates:
                _last_update_id = upd["update_id"]
                msg = upd.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = msg.get("text", "")

                if chat_id != str(S.TELEGRAM_CHAT_ID):
                    continue
                if not text.startswith("/"):
                    continue

                reply = _handle_command(text)
                _send_reply(chat_id, reply)
        except Exception as e:
            log.warning("Telegram poll error: %s", e)
            time.sleep(5)


def _get_updates(offset: int) -> list:
    try:
        r = requests.get(
            f"{_BASE_URL}/getUpdates",
            params={"offset": offset, "timeout": 30},
            timeout=35,
        )
        return r.json().get("result", [])
    except Exception:
        return []


def _send_reply(chat_id: str, text: str) -> None:
    try:
        requests.post(
            f"{_BASE_URL}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        log.warning("Telegram reply failed: %s", e)


# ── Command handlers ────────────────────────────────────────────────────────

def _handle_command(text: str) -> str:
    parts = text.strip().split()
    cmd = parts[0].lstrip("/").lower()

    if cmd == "help":
        return (
            "<b>Supervisor Commands</b>\n\n"
            "/status — Portfolio snapshot\n"
            "/regime — Market regime classification\n"
            "/brief — Latest morning brief\n"
            "/mode &lt;bot&gt; &lt;MODE&gt; — Override bot mode\n"
            "  bots: kraken, sfm, alpaca\n"
            "  modes: NORMAL, SCOUT, DEFENSE\n"
            "/selfheal — Request self-heal scan\n"
            "/stop — Activate emergency stop\n"
            "/help — This help message"
        )

    if cmd == "status":
        return _cmd_status()

    if cmd == "regime":
        return _cmd_regime()

    if cmd == "brief":
        return _cmd_brief()

    if cmd == "mode":
        if len(parts) < 3:
            return "Usage: /mode &lt;bot&gt; &lt;NORMAL|SCOUT|DEFENSE&gt;\nExample: /mode kraken DEFENSE"
        return _cmd_mode(parts[1].lower(), parts[2].upper())

    if cmd == "selfheal":
        return _cmd_selfheal()

    if cmd == "stop":
        return _cmd_emergency_stop()

    return f"Unknown command: /{cmd}\nSend /help for available commands."


def _cmd_status() -> str:
    try:
        with open(S.REPORT_FILE, encoding="utf-8") as f:
            r = json.load(f)
    except Exception as e:
        return f"Could not read status: {e}"

    p = r.get("portfolio", {})
    ts = r.get("ts", "")[:19].replace("T", " ")

    lines = [f"<b>Portfolio</b> — {ts} UTC"]
    lines.append(f"Equity: <b>${p.get('total_equity_usd', 0):,.2f}</b>")
    lines.append(
        f"PnL: ${p.get('total_pnl_usd', 0):+,.2f} ({p.get('total_pnl_pct', 0):+.2f}%)"
    )
    lines.append(
        f"DD: {p.get('total_dd_pct', 0):.2f}%  |  Peak: ${p.get('peak_equity_usd', 0):,.2f}"
    )
    if p.get("kill_switch_active"):
        lines.append("⚠️ <b>KILL SWITCH ACTIVE</b>")
    if p.get("emergency_stop"):
        lines.append("🚨 <b>EMERGENCY STOP</b>")

    lines.append("")
    health_emoji = {"GOOD": "✅", "WARN": "⚠️", "CRITICAL": "🔴"}
    for name, s in r.get("sleeves", {}).items():
        em = health_emoji.get(s.get("health", ""), "❓")
        lines.append(
            f"{em} <b>{name}</b>  ${s.get('equity_usd', 0):,.2f}  "
            f"{s.get('mode', '?')}  {s.get('pnl_pct', 0):+.1f}%  "
            f"({s.get('open_positions', 0)} pos)"
        )

    if r.get("alerts"):
        lines.append("")
        for a in r["alerts"]:
            lines.append(f"⚠️ {a}")

    return "\n".join(lines)


def _cmd_regime() -> str:
    try:
        with open(S.REPORT_FILE, encoding="utf-8") as f:
            r = json.load(f)
    except Exception as e:
        return f"Could not read regime: {e}"

    reg = r.get("regime", {})
    emoji = {"RISK_ON": "🟢", "NEUTRAL": "🟡", "RISK_OFF": "🔴"}.get(
        reg.get("classification", ""), "⚪"
    )
    lines = [
        f"{emoji} <b>Regime: {reg.get('classification', '?')}</b> "
        f"({reg.get('confidence', 0) * 100:.0f}% conf)",
        f"BTC 7d: {reg.get('btc_7d_pct', 0):+.2f}%  |  BTC: ${reg.get('btc_price_usd', 0):,.0f}",
        f"SPY vol: {reg.get('spy_vol_10d_pct', 0):.2f}%  |  SPY: ${reg.get('spy_price_usd', 0):.2f}",
    ]
    notes = reg.get("notes", [])
    if notes:
        lines.append("Notes: " + " | ".join(notes))
    return "\n".join(lines)


def _cmd_brief() -> str:
    brief_file = os.path.join(S.BASE_DIR, "morning_brief.txt")
    if not os.path.exists(brief_file):
        return "No morning brief available yet."
    try:
        with open(brief_file, encoding="utf-8") as f:
            text = f.read()
        if len(text) > 3800:
            text = text[:3800] + "\n... [truncated — see /api/brief for full text]"
        return f"<pre>{text}</pre>"
    except Exception as e:
        return f"Could not read brief: {e}"


def _cmd_mode(bot: str, mode: str) -> str:
    bot_map = {"kraken": S.CMD_KRAKEN, "sfm": S.CMD_SFM, "alpaca": S.CMD_ALPACA}
    if bot not in bot_map:
        return f"Unknown bot '{bot}'. Use: kraken, sfm, alpaca"
    if mode not in ("NORMAL", "SCOUT", "DEFENSE"):
        return f"Unknown mode '{mode}'. Use: NORMAL, SCOUT, DEFENSE"

    cmd_file = bot_map[bot]
    try:
        os.makedirs(os.path.dirname(cmd_file), exist_ok=True)
        try:
            with open(cmd_file, encoding="utf-8") as f:
                cmd = json.load(f)
        except Exception:
            cmd = {}

        cmd["mode"] = mode
        cmd["entry_allowed"] = mode != "DEFENSE"
        cmd["manual_override"] = True
        cmd["override_ts"] = datetime.now(timezone.utc).isoformat()

        with open(cmd_file, "w", encoding="utf-8") as f:
            json.dump(cmd, f, indent=2)

        return f"✅ <b>{bot}</b> mode set to <b>{mode}</b>"
    except Exception as e:
        return f"Failed to set mode: {e}"


def _cmd_selfheal() -> None:
    trigger = os.path.join(S.BASE_DIR, "selfheal_trigger.txt")
    try:
        with open(trigger, "w", encoding="utf-8") as f:
            f.write(datetime.now(timezone.utc).isoformat())
        return "✅ Self-heal scan requested — will run on next supervisor cycle."
    except Exception as e:
        return f"Failed to request self-heal: {e}"


def _cmd_emergency_stop() -> str:
    try:
        with open(S.STOP_FILE, "w", encoding="utf-8") as f:
            f.write(
                f"EMERGENCY STOP via Telegram at {datetime.now(timezone.utc).isoformat()}"
            )
        return (
            "🚨 <b>EMERGENCY STOP activated!</b>\n"
            "All bots will switch to DEFENSE on next supervisor cycle."
        )
    except Exception as e:
        return f"Failed to write stop file: {e}"

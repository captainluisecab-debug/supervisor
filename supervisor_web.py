"""
supervisor_web.py — Web dashboard + REST API for remote monitoring.

Provides:
  GET  /              — Auto-refreshing HTML portfolio dashboard
  GET  /api/status    — JSON portfolio + regime snapshot
  GET  /api/report    — Full supervisor_report.json
  GET  /api/brief     — Latest morning brief (plain text)
  POST /api/command   — Override bot mode  {"bot": "kraken", "mode": "DEFENSE"}
  POST /api/stop      — Activate emergency stop

Auth: If WEB_SECRET is set in .env, pass it as header X-Secret or ?secret=...

Set WEB_PORT (default 8080) and WEB_HOST (default 0.0.0.0) in .env.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone

import supervisor_settings as S

log = logging.getLogger(__name__)

# ── HTML helpers ────────────────────────────────────────────────────────────

_HEALTH_COLOR = {"GOOD": "#00c853", "WARN": "#ffd600", "CRITICAL": "#d50000"}
_REGIME_COLOR = {"RISK_ON": "#00c853", "NEUTRAL": "#ffd600", "RISK_OFF": "#d50000"}


def _load_report() -> dict:
    try:
        with open(S.REPORT_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _build_dashboard_html(report: dict) -> str:
    p = report.get("portfolio", {})
    reg = report.get("regime", {})
    sleeves = report.get("sleeves", {})
    alerts = report.get("alerts", [])
    ts = report.get("ts", "—")[:19].replace("T", " ")
    cycle = report.get("cycle", "?")

    regime_cls = reg.get("classification", "")
    regime_color = _REGIME_COLOR.get(regime_cls, "#888")
    pnl_color = "#00c853" if p.get("total_pnl_pct", 0) >= 0 else "#d50000"

    kill_banner = ""
    if p.get("emergency_stop"):
        kill_banner = '<div class="banner">🚨 EMERGENCY STOP — Supervisor halted</div>'
    elif p.get("kill_switch_active"):
        kill_banner = '<div class="banner">⚠️ KILL SWITCH ACTIVE — All bots in DEFENSE</div>'

    alert_html = "".join(
        f'<div class="alert-row">⚠️ {a}</div>' for a in alerts
    )

    sleeve_rows = ""
    for name, s in sleeves.items():
        h_color = _HEALTH_COLOR.get(s.get("health", ""), "#888")
        sp_color = "#00c853" if s.get("pnl_pct", 0) >= 0 else "#d50000"
        sleeve_rows += (
            f"<tr>"
            f"<td><b>{name}</b></td>"
            f"<td>${s.get('equity_usd', 0):,.2f}</td>"
            f"<td style='color:{sp_color}'>{s.get('pnl_pct', 0):+.2f}%</td>"
            f"<td>{s.get('drawdown_pct', 0):.2f}%</td>"
            f"<td>{s.get('open_positions', 0)}</td>"
            f"<td><b>{s.get('mode', '?')}</b></td>"
            f"<td style='color:{h_color}'><b>{s.get('health', '?')}</b></td>"
            f"</tr>"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="30">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Supervisor Dashboard</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{background:#0d1117;color:#c9d1d9;font-family:monospace;font-size:14px;padding:20px}}
    h1{{color:#58a6ff;margin-bottom:4px}}
    .sub{{color:#8b949e;font-size:12px;margin-bottom:18px}}
    .sub a{{color:#58a6ff;text-decoration:none}}
    .banner{{background:#b71c1c;color:#fff;padding:10px 16px;border-radius:6px;margin-bottom:14px;font-weight:bold}}
    .alert-row{{background:#1a1200;border:1px solid #ffd600;color:#ffd600;padding:7px 14px;border-radius:4px;margin-bottom:8px}}
    .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin-bottom:20px}}
    .card{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px}}
    .card h3{{color:#8b949e;font-size:10px;text-transform:uppercase;margin-bottom:6px}}
    .card .val{{font-size:20px;font-weight:bold}}
    .badge{{display:inline-block;padding:3px 10px;border-radius:20px;font-weight:bold;
            background:{regime_color}22;color:{regime_color};border:1px solid {regime_color}}}
    .sec{{color:#8b949e;font-size:10px;text-transform:uppercase;margin:18px 0 8px}}
    table{{width:100%;border-collapse:collapse;background:#161b22;border-radius:8px;overflow:hidden}}
    th{{background:#21262d;padding:9px 12px;text-align:left;color:#8b949e;font-size:10px;text-transform:uppercase}}
    td{{padding:9px 12px;border-top:1px solid #21262d}}
    .footer{{margin-top:24px;color:#484f58;font-size:11px}}
  </style>
</head>
<body>
  <h1>Supervisor Dashboard</h1>
  <div class="sub">
    Cycle #{cycle} &nbsp;|&nbsp; {ts} UTC &nbsp;|&nbsp; Auto-refreshes every 30s
    &nbsp;|&nbsp; <a href="/api/report">Raw JSON</a>
    &nbsp;|&nbsp; <a href="/api/brief">Morning Brief</a>
  </div>

  {kill_banner}
  {alert_html}

  <div class="grid">
    <div class="card">
      <h3>Total Equity</h3>
      <div class="val">${p.get('total_equity_usd', 0):,.2f}</div>
    </div>
    <div class="card">
      <h3>PnL</h3>
      <div class="val" style="color:{pnl_color}">{p.get('total_pnl_pct', 0):+.2f}%</div>
      <div style="color:{pnl_color};font-size:12px">${p.get('total_pnl_usd', 0):+,.2f}</div>
    </div>
    <div class="card">
      <h3>Drawdown</h3>
      <div class="val">{p.get('total_dd_pct', 0):.2f}%</div>
      <div style="color:#8b949e;font-size:12px">Peak ${p.get('peak_equity_usd', 0):,.2f}</div>
    </div>
    <div class="card">
      <h3>Regime</h3>
      <div style="margin-top:4px"><span class="badge">{regime_cls or '?'}</span></div>
      <div style="color:#8b949e;font-size:12px;margin-top:8px">
        BTC 7d {reg.get('btc_7d_pct', 0):+.2f}% &nbsp; SPY vol {reg.get('spy_vol_10d_pct', 0):.2f}%
      </div>
    </div>
    <div class="card">
      <h3>BTC Price</h3>
      <div class="val">${reg.get('btc_price_usd', 0):,.0f}</div>
    </div>
    <div class="card">
      <h3>SPY Price</h3>
      <div class="val">${reg.get('spy_price_usd', 0):.2f}</div>
    </div>
  </div>

  <div class="sec">Sleeve Breakdown</div>
  <table>
    <thead>
      <tr>
        <th>Bot</th><th>Equity</th><th>PnL%</th><th>DD%</th>
        <th>Positions</th><th>Mode</th><th>Health</th>
      </tr>
    </thead>
    <tbody>{sleeve_rows}</tbody>
  </table>

  <div class="footer">
    REST API: /api/status &nbsp;|&nbsp; /api/report &nbsp;|&nbsp;
    /api/brief &nbsp;|&nbsp; POST /api/command &nbsp;|&nbsp; POST /api/stop
  </div>
</body>
</html>"""


# ── Flask app factory ────────────────────────────────────────────────────────

def _create_app():
    try:
        from flask import Flask, Response, jsonify, request
    except ImportError:
        log.error("Flask not installed — web dashboard disabled. Run: pip install flask")
        return None

    app = Flask("supervisor_web")
    app.logger.setLevel(logging.WARNING)

    def _check_auth():
        if not S.WEB_SECRET:
            return None
        token = request.headers.get("X-Secret") or request.args.get("secret", "")
        if token != S.WEB_SECRET:
            return Response("Unauthorized", status=401)
        return None

    @app.route("/")
    def dashboard():
        return _build_dashboard_html(_load_report())

    @app.route("/api/status")
    def api_status():
        err = _check_auth()
        if err:
            return err
        r = _load_report()
        return jsonify({
            "ts":        r.get("ts"),
            "cycle":     r.get("cycle"),
            "portfolio": r.get("portfolio", {}),
            "regime":    r.get("regime", {}),
            "sleeves":   r.get("sleeves", {}),
            "alerts":    r.get("alerts", []),
        })

    @app.route("/api/report")
    def api_report():
        err = _check_auth()
        if err:
            return err
        return jsonify(_load_report())

    @app.route("/api/brief")
    def api_brief():
        err = _check_auth()
        if err:
            return err
        brief_file = os.path.join(S.BASE_DIR, "morning_brief.txt")
        if not os.path.exists(brief_file):
            return Response("No morning brief available.", mimetype="text/plain")
        with open(brief_file, encoding="utf-8") as f:
            return Response(f.read(), mimetype="text/plain")

    @app.route("/api/command", methods=["POST"])
    def api_command():
        err = _check_auth()
        if err:
            return err
        body = request.get_json(silent=True) or {}
        bot  = body.get("bot", "").lower()
        mode = body.get("mode", "").upper()

        bot_map = {"kraken": S.CMD_KRAKEN, "sfm": S.CMD_SFM, "alpaca": S.CMD_ALPACA}
        if bot not in bot_map:
            return jsonify({"error": f"Unknown bot '{bot}'. Use: kraken, sfm, alpaca"}), 400
        if mode not in ("NORMAL", "SCOUT", "DEFENSE"):
            return jsonify({"error": f"Unknown mode '{mode}'. Use: NORMAL, SCOUT, DEFENSE"}), 400

        cmd_file = bot_map[bot]
        try:
            os.makedirs(os.path.dirname(cmd_file), exist_ok=True)
            try:
                with open(cmd_file, encoding="utf-8") as f:
                    cmd = json.load(f)
            except Exception:
                cmd = {}

            cmd["mode"]            = mode
            cmd["entry_allowed"]   = mode != "DEFENSE"
            cmd["manual_override"] = True
            cmd["override_ts"]     = datetime.now(timezone.utc).isoformat()

            with open(cmd_file, "w", encoding="utf-8") as f:
                json.dump(cmd, f, indent=2)

            return jsonify({"ok": True, "bot": bot, "mode": mode})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/stop", methods=["POST"])
    def api_stop():
        err = _check_auth()
        if err:
            return err
        try:
            with open(S.STOP_FILE, "w", encoding="utf-8") as f:
                f.write(
                    f"EMERGENCY STOP via web API at {datetime.now(timezone.utc).isoformat()}"
                )
            return jsonify({"ok": True, "message": "Emergency stop activated"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return app


# ── Server start ────────────────────────────────────────────────────────────

def start_web_server() -> None:
    """Start the Flask web server in a background daemon thread."""
    if not S.WEB_ENABLED:
        log.info("Web dashboard disabled (WEB_ENABLED=false in .env)")
        return

    app = _create_app()
    if app is None:
        return

    def _run():
        import logging as _l
        _l.getLogger("werkzeug").setLevel(_l.WARNING)
        app.run(host=S.WEB_HOST, port=S.WEB_PORT, debug=False, use_reloader=False)

    t = threading.Thread(target=_run, daemon=True, name="web-dashboard")
    t.start()
    log.info("Web dashboard → http://%s:%d", S.WEB_HOST, S.WEB_PORT)

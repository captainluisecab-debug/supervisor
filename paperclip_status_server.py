"""
paperclip_status_server.py — Read-only status endpoint for Paperclip.

Serves current system state as JSON on http://127.0.0.1:3101/status
Reads existing files only. Never writes. Never modifies state.

Used by Paperclip http adapter for loop-closure verification.
"""
from __future__ import annotations

import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

STATUS_FILES = {
    "hermes_context": os.path.join(BASE_DIR, "hermes_context.json"),
    "kraken_state_truth": os.path.join(BASE_DIR, "kraken_state_truth.json"),
    "kernel_audit_last": os.path.join(BASE_DIR, "kernel_audit.jsonl"),
    "kraken_cmd": os.path.join(BASE_DIR, "commands", "kraken_cmd.json"),
    "sfm_cmd": os.path.join(BASE_DIR, "commands", "sfm_cmd.json"),
    "alpaca_cmd": os.path.join(BASE_DIR, "commands", "alpaca_cmd.json"),
}


def _read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"error": f"unreadable: {path}"}


def _read_last_jsonl(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        return json.loads(lines[-1]) if lines else {}
    except Exception:
        return {"error": f"unreadable: {path}"}


def build_status() -> dict:
    hermes = _read_json(STATUS_FILES["hermes_context"])
    truth = _read_json(STATUS_FILES["kraken_state_truth"])
    kernel = _read_last_jsonl(STATUS_FILES["kernel_audit_last"])

    return {
        "system": "supervisor",
        "universe_equity": hermes.get("universe", {}).get("equity"),
        "universe_pnl_pct": hermes.get("universe", {}).get("pnl_pct"),
        "regime": hermes.get("regime", {}).get("label"),
        "kraken": {
            "equity": hermes.get("kraken", {}).get("equity"),
            "dd_pct": hermes.get("kraken", {}).get("dd_pct"),
            "posture": truth.get("effective_posture"),
            "force_flatten": truth.get("force_flatten"),
            "cmd_entry_allowed": _read_json(STATUS_FILES["kraken_cmd"]).get("entry_allowed"),
        },
        "sfm": {
            "equity": hermes.get("sfm", {}).get("equity"),
            "dd_pct": hermes.get("sfm", {}).get("dd_pct"),
            "cmd_entry_allowed": _read_json(STATUS_FILES["sfm_cmd"]).get("entry_allowed"),
        },
        "alpaca": {
            "equity": hermes.get("alpaca", {}).get("equity"),
            "cmd_entry_allowed": _read_json(STATUS_FILES["alpaca_cmd"]).get("entry_allowed"),
        },
        "kernel_last": {
            "status": kernel.get("status"),
            "violations": kernel.get("violations"),
            "cycle": kernel.get("cycle"),
        },
        "advisory": hermes.get("advisory", {}).get("note"),
    }


class StatusHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/status":
            body = json.dumps(build_status(), indent=2).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress request logging


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", 3101), StatusHandler)
    print("Paperclip status server running on http://127.0.0.1:3101/status")
    server.serve_forever()

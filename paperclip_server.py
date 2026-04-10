"""
paperclip_server.py — Local Paperclip issue tracking server.

Lightweight replacement for the external Paperclip service.
Implements the exact API contract that paperclip_bridge.py expects.
Uses SQLite for persistent storage. Zero external dependencies.

Runs on http://127.0.0.1:3100/api

Endpoints:
  POST   /api/companies/{cid}/issues      — create issue
  GET    /api/companies/{cid}/issues       — list issues (optional ?status=todo)
  PATCH  /api/issues/{id}                  — update issue fields
  POST   /api/issues/{id}/comments         — add comment
  GET    /api/companies/{cid}/agents       — list agents
  PATCH  /api/agents/{id}                  — update agent status
  GET    /api/health                       — health check

Start: python paperclip_server.py
Stop:  Ctrl+C or kill process
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

log = logging.getLogger("paperclip")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [PAPERCLIP] %(message)s")

HOST = "127.0.0.1"
PORT = 3100
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "paperclip.db")

# Pre-configured IDs (must match paperclip_bridge.py)
COMPANY_ID = "f1f333d3-ad5b-48a9-8d7f-c600761d9aae"
PROJECT_ID = "304d91af-d5fc-48ab-8873-a3f8806add4f"

AGENTS = {
    "78e06d06-07b8-45c5-8ab6-1ab35e723488": {"name": "Luis", "role": "Operator", "status": "active"},
    "ac91fe14-83c3-4e53-97d4-00b14d71cdd2": {"name": "Opus", "role": "Commander", "status": "active"},
    "f5f2e179-ab74-4bdd-b421-89585c9870cf": {"name": "Hermes", "role": "Observer", "status": "active"},
    "bf5f6c80-176f-4801-a908-a394d7501aca": {"name": "Supervisor", "role": "Enforcer", "status": "active"},
    "34193093-ecf0-456e-86e5-2e75a22c81cb": {"name": "Paperclip", "role": "Orchestrator", "status": "active"},
    "1710b68b-e4a5-458c-be9b-02c03038810e": {"name": "Kernel", "role": "Validator", "status": "active"},
    "4176fae8-0375-434a-8a53-4f6f522eee5e": {"name": "BotOps", "role": "Operations", "status": "active"},
}

# Issue counter for human-readable identifiers
_issue_counter = 0


def _init_db():
    """Initialize SQLite database with schema."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS issues (
            id TEXT PRIMARY KEY,
            identifier TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            status TEXT DEFAULT 'todo',
            priority TEXT DEFAULT 'medium',
            project_id TEXT,
            assignee_agent_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS comments (
            id TEXT PRIMARY KEY,
            issue_id TEXT NOT NULL,
            body TEXT NOT NULL,
            author_agent_id TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY (issue_id) REFERENCES issues(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            role TEXT DEFAULT '',
            status TEXT DEFAULT 'active'
        )
    """)
    # Seed agents if empty
    cur = conn.execute("SELECT COUNT(*) FROM agents")
    if cur.fetchone()[0] == 0:
        for aid, info in AGENTS.items():
            conn.execute("INSERT INTO agents (id, name, role, status) VALUES (?, ?, ?, ?)",
                         (aid, info["name"], info["role"], info["status"]))
    conn.commit()

    # Load issue counter
    global _issue_counter
    cur = conn.execute("SELECT COUNT(*) FROM issues")
    _issue_counter = cur.fetchone()[0]
    conn.close()


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _new_id():
    return str(uuid.uuid4())


def _next_identifier():
    global _issue_counter
    _issue_counter += 1
    return f"PC-{_issue_counter}"


class PaperclipHandler(BaseHTTPRequestHandler):
    """HTTP request handler for Paperclip API."""

    def log_message(self, format, *args):
        log.info(format, *args)

    def _send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode())
        except Exception:
            return {}

    def _parse_path(self):
        parsed = urlparse(self.path)
        return parsed.path.rstrip("/"), parse_qs(parsed.query)

    # ── GET ──────────────────────────────────────────────────────────

    def do_GET(self):
        path, qs = self._parse_path()

        # GET /api/health
        if path == "/api/health":
            self._send_json({
                "status": "ok",
                "version": "paperclip-local-1.0",
                "ts": _now_iso(),
            })
            return

        # GET /api/companies/{cid}/issues
        if path.startswith("/api/companies/") and path.endswith("/issues"):
            status_filter = qs.get("status", [None])[0]
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            if status_filter:
                rows = conn.execute(
                    "SELECT * FROM issues WHERE status = ? ORDER BY created_at DESC", (status_filter,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM issues ORDER BY created_at DESC").fetchall()
            conn.close()
            issues = []
            for r in rows:
                issues.append({
                    "id": r["id"],
                    "identifier": r["identifier"],
                    "title": r["title"],
                    "description": r["description"],
                    "status": r["status"],
                    "priority": r["priority"],
                    "projectId": r["project_id"],
                    "assigneeAgentId": r["assignee_agent_id"],
                    "createdAt": r["created_at"],
                    "updatedAt": r["updated_at"],
                })
            self._send_json(issues)
            return

        # GET /api/companies/{cid}/agents
        if path.startswith("/api/companies/") and path.endswith("/agents"):
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM agents").fetchall()
            conn.close()
            agents = [{"id": r["id"], "name": r["name"], "role": r["role"], "status": r["status"]}
                      for r in rows]
            self._send_json(agents)
            return

        self._send_json({"error": "not found"}, 404)

    # ── POST ─────────────────────────────────────────────────────────

    def do_POST(self):
        path, _ = self._parse_path()
        data = self._read_body()

        # POST /api/companies/{cid}/issues — create issue
        if path.startswith("/api/companies/") and path.endswith("/issues"):
            now = _now_iso()
            issue_id = _new_id()
            identifier = _next_identifier()
            conn = sqlite3.connect(DB_PATH)
            conn.execute(
                "INSERT INTO issues (id, identifier, title, description, status, priority, "
                "project_id, assignee_agent_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    issue_id,
                    identifier,
                    data.get("title", "Untitled"),
                    data.get("description", ""),
                    data.get("status", "todo"),
                    data.get("priority", "medium"),
                    data.get("projectId", PROJECT_ID),
                    data.get("assigneeAgentId", ""),
                    now,
                    now,
                ),
            )
            conn.commit()
            conn.close()
            log.info("Issue created: %s — %s [%s]", identifier, data.get("title", "")[:60],
                     data.get("priority", "medium"))
            self._send_json({
                "id": issue_id,
                "identifier": identifier,
                "title": data.get("title", "Untitled"),
                "status": "todo",
                "priority": data.get("priority", "medium"),
                "createdAt": now,
            }, 201)
            return

        # POST /api/issues/{id}/comments — add comment
        parts = path.split("/")
        if len(parts) >= 4 and parts[1] == "api" and parts[2] == "issues" and parts[-1] == "comments":
            issue_id = parts[3]
            now = _now_iso()
            comment_id = _new_id()
            conn = sqlite3.connect(DB_PATH)
            conn.execute(
                "INSERT INTO comments (id, issue_id, body, author_agent_id, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (comment_id, issue_id, data.get("body", ""), data.get("authorAgentId", ""), now),
            )
            # Update issue's updated_at
            conn.execute("UPDATE issues SET updated_at = ? WHERE id = ?", (now, issue_id))
            conn.commit()
            conn.close()
            self._send_json({"id": comment_id, "body": data.get("body", ""), "createdAt": now}, 201)
            return

        self._send_json({"error": "not found"}, 404)

    # ── PATCH ────────────────────────────────────────────────────────

    def do_PATCH(self):
        path, _ = self._parse_path()
        data = self._read_body()

        # PATCH /api/issues/{id}
        parts = path.split("/")
        if len(parts) >= 3 and parts[1] == "api" and parts[2] == "issues" and len(parts) == 4:
            issue_id = parts[3]
            now = _now_iso()
            conn = sqlite3.connect(DB_PATH)
            updates = []
            params = []
            for field in ("status", "priority", "title", "description"):
                if field in data:
                    updates.append(f"{field} = ?")
                    params.append(data[field])
            if "assigneeAgentId" in data:
                updates.append("assignee_agent_id = ?")
                params.append(data["assigneeAgentId"])
            if updates:
                updates.append("updated_at = ?")
                params.append(now)
                params.append(issue_id)
                conn.execute(f"UPDATE issues SET {', '.join(updates)} WHERE id = ?", params)
                conn.commit()
                if "status" in data:
                    log.info("Issue %s → %s", issue_id[:8], data["status"])
            conn.close()
            self._send_json({"id": issue_id, "updated": True, "updatedAt": now})
            return

        # PATCH /api/agents/{id}
        if len(parts) >= 3 and parts[1] == "api" and parts[2] == "agents" and len(parts) == 4:
            agent_id = parts[3]
            conn = sqlite3.connect(DB_PATH)
            if "status" in data:
                conn.execute("UPDATE agents SET status = ? WHERE id = ?", (data["status"], agent_id))
                conn.commit()
            conn.close()
            self._send_json({"id": agent_id, "updated": True})
            return

        self._send_json({"error": "not found"}, 404)


def main():
    _init_db()
    server = HTTPServer((HOST, PORT), PaperclipHandler)
    log.info("Paperclip server running on http://%s:%d/api", HOST, PORT)
    log.info("Database: %s", DB_PATH)
    log.info("Agents: %s", ", ".join(a["name"] for a in AGENTS.values()))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Paperclip server stopped.")
        server.server_close()


if __name__ == "__main__":
    main()

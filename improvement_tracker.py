"""
improvement_tracker.py — Institutional Memory: Lessons + Before/After Proof Loops.

Stores system lessons (permanent) and improvement proofs (before/after evidence).
All storage is disk-backed JSONL for persistence across restarts and sessions.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LESSONS_FILE = os.path.join(BASE_DIR, "system_lessons.jsonl")
PROOFS_FILE = os.path.join(BASE_DIR, "improvement_proofs.jsonl")


def _append_jsonl(path: str, record: dict):
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass


def _read_jsonl(path: str, n: int = 50) -> list:
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        return [json.loads(l) for l in lines[-n:] if l.strip()]
    except Exception:
        return []


def load_lessons(n: int = 20) -> list:
    """Read last N institutional lessons."""
    return _read_jsonl(LESSONS_FILE, n)


def append_lesson(lesson: dict):
    """Append a lesson to the permanent institutional memory."""
    lesson.setdefault("ts", datetime.now(timezone.utc).isoformat())
    _append_jsonl(LESSONS_FILE, lesson)


def record_improvement(improvement_id: str, category: str, description: str,
                       baseline_metric: str, baseline_value: float,
                       window_hours: int = 24):
    """Register a new improvement for before/after tracking."""
    _append_jsonl(PROOFS_FILE, {
        "improvement_id": improvement_id,
        "type": "baseline",
        "category": category,
        "description": description,
        "metric": baseline_metric,
        "value": baseline_value,
        "window_hours": window_hours,
        "ts": datetime.now(timezone.utc).isoformat(),
    })


def record_proof(improvement_id: str, proof_metric: str, proof_value: float,
                 conclusion: str, lesson: str = ""):
    """Record the after-measurement for an improvement."""
    _append_jsonl(PROOFS_FILE, {
        "improvement_id": improvement_id,
        "type": "proof",
        "metric": proof_metric,
        "value": proof_value,
        "conclusion": conclusion,
        "lesson": lesson,
        "ts": datetime.now(timezone.utc).isoformat(),
    })


def get_open_improvements() -> list:
    """Return improvements that have a baseline but no proof yet."""
    records = _read_jsonl(PROOFS_FILE, 200)
    baselines = {}
    proven = set()
    for r in records:
        if r.get("type") == "baseline":
            baselines[r["improvement_id"]] = r
        elif r.get("type") == "proof":
            proven.add(r["improvement_id"])
    return [v for k, v in baselines.items() if k not in proven]

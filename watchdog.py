"""
watchdog.py — Keeps supervisor.py and opus_sentinel.py alive.
Usage: python watchdog.py
"""
from __future__ import annotations
import logging, os, subprocess, sys, time

logging.basicConfig(level=logging.INFO,
                    format="[%(asctime)s][WATCHDOG] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("watchdog")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON   = sys.executable
CHECK_SEC = 30
RESTART_DELAY = 5
PROCESSES = [
    {"name": "supervisor",    "script": "supervisor.py",    "proc": None, "restarts": 0},
    {"name": "opus_sentinel", "script": "opus_sentinel.py", "proc": None, "restarts": 0},
    {"name": "opus_review",   "script": "opus_review.py",   "proc": None, "restarts": 0},
]


def start(entry):
    script = os.path.join(BASE_DIR, entry["script"])
    if not os.path.exists(script):
        log.error("Script not found: %s", script); return
    log.info("Starting %s...", entry["name"])
    entry["proc"] = subprocess.Popen([PYTHON, script], cwd=BASE_DIR)
    log.info("%s started (pid=%d)", entry["name"], entry["proc"].pid)


def main():
    log.info("=" * 50)
    log.info("SUPERVISOR WATCHDOG — %d processes managed", len(PROCESSES))
    log.info("=" * 50)
    for entry in PROCESSES:
        start(entry)
    while True:
        time.sleep(CHECK_SEC)
        for entry in PROCESSES:
            proc = entry["proc"]
            if proc is None or proc.poll() is not None:
                entry["restarts"] += 1
                log.warning("%s crashed — restarting in %ds (restart #%d)",
                            entry["name"], RESTART_DELAY, entry["restarts"])
                time.sleep(RESTART_DELAY)
                start(entry)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Watchdog stopped.")
        for entry in PROCESSES:
            if entry["proc"] and entry["proc"].poll() is None:
                entry["proc"].terminate()

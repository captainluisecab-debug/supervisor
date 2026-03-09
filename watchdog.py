"""
watchdog.py — Keeps supervisor.py alive.
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
PROCESS = {"name": "supervisor", "script": "supervisor.py", "proc": None, "restarts": 0}


def start(entry):
    script = os.path.join(BASE_DIR, entry["script"])
    if not os.path.exists(script):
        log.error("Script not found: %s", script); return
    log.info("Starting %s...", entry["name"])
    entry["proc"] = subprocess.Popen([PYTHON, script], cwd=BASE_DIR)
    log.info("%s started (pid=%d)", entry["name"], entry["proc"].pid)


def main():
    log.info("=" * 50)
    log.info("SUPERVISOR WATCHDOG")
    log.info("=" * 50)
    start(PROCESS)
    while True:
        time.sleep(CHECK_SEC)
        proc = PROCESS["proc"]
        if proc is None or proc.poll() is not None:
            PROCESS["restarts"] += 1
            log.warning("supervisor crashed — restarting in %ds (restart #%d)",
                        RESTART_DELAY, PROCESS["restarts"])
            time.sleep(RESTART_DELAY)
            start(PROCESS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Watchdog stopped.")
        if PROCESS["proc"] and PROCESS["proc"].poll() is None:
            PROCESS["proc"].terminate()

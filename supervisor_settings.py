"""
supervisor_settings.py — Load .env config for master supervisor.
"""
from __future__ import annotations
import os

_ENV = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def _load(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ[k.strip()] = v.strip().strip('"').strip("'")


_load(_ENV)


def _s(k, d=""): return os.environ.get(k, d)
def _f(k, d):
    try: return float(_s(k, str(d)))
    except: return d
def _i(k, d):
    try: return int(_s(k, str(d)))
    except: return d


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Bot state paths
ENZOBOT_STATE  = _s("ENZOBOT_STATE",  r"C:\Projects\enzobot\state.json")
ENZOBOT_BRAIN  = _s("ENZOBOT_BRAIN",  r"C:\Projects\enzobot\brain_state.json")
SFMBOT_STATE   = _s("SFMBOT_STATE",   r"C:\Projects\sfmbot\sfm_state.json")
ALPACA_STATE   = _s("ALPACA_STATE",   r"C:\Projects\alpacabot\alpaca_state.json")

# Alpaca live account
ALPACA_API_KEY    = _s("ALPACA_API_KEY")
ALPACA_SECRET_KEY = _s("ALPACA_SECRET_KEY")

# Capital baselines
ENZOBOT_BASELINE = _f("ENZOBOT_BASELINE", 4000.00)
SFMBOT_BASELINE  = _f("SFMBOT_BASELINE",  2350.87)
ALPACA_BASELINE  = _f("ALPACA_BASELINE",  500.00)
TOTAL_BASELINE   = ENZOBOT_BASELINE + SFMBOT_BASELINE + ALPACA_BASELINE

# Risk thresholds
KILL_SWITCH_DD_PCT    = _f("KILL_SWITCH_DD_PCT", 10.0)
BTC_TREND_RISK_OFF    = _f("BTC_TREND_RISK_OFF_PCT", -5.0)
BTC_TREND_RISK_ON     = _f("BTC_TREND_RISK_ON_PCT",  3.0)
SPY_VOL_RISK_OFF      = _f("SPY_VOL_RISK_OFF_PCT",   2.5)

CYCLE_SEC = _i("CYCLE_SEC", 300)

# Claude brain
ANTHROPIC_API_KEY    = _s("ANTHROPIC_API_KEY")
CLAUDE_MODEL         = _s("CLAUDE_MODEL", "claude-sonnet-4-6")
BRAIN_INTERVAL_CYCLES = _i("BRAIN_INTERVAL_CYCLES", 6)  # call Claude every N cycles

# Output paths
REPORT_FILE   = os.path.join(BASE_DIR, "supervisor_report.json")
HISTORY_FILE  = os.path.join(BASE_DIR, "supervisor_history.jsonl")
STOP_FILE     = os.path.join(BASE_DIR, "EMERGENCY_STOP.txt")
COMMANDS_DIR  = os.path.join(BASE_DIR, "commands")

# Per-bot command files (supervisor writes, bots read)
CMD_KRAKEN = os.path.join(COMMANDS_DIR, "kraken_cmd.json")
CMD_SFM    = os.path.join(COMMANDS_DIR, "sfm_cmd.json")
CMD_ALPACA = os.path.join(COMMANDS_DIR, "alpaca_cmd.json")

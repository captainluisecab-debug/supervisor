"""
supervisor_execution.py — Shared execution log reader/writer.
Each bot appends here after every trade. Master brain reads it every cycle.
"""
import json, os
from datetime import datetime, timezone

EXEC_LOG = r"C:\Projects\supervisor\execution_log.jsonl"

def log_execution(bot: str, symbol: str, side: str, size_usd: float,
                  price: float, pnl_usd: float, reason: str) -> None:
    """Called by each bot after every trade fill."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "bot": bot,
        "symbol": symbol,
        "side": side,           # BUY or SELL
        "size_usd": size_usd,
        "price": price,
        "pnl_usd": pnl_usd,     # 0.0 for buys
        "reason": reason,
    }
    with open(EXEC_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

def read_recent_executions(n: int = 20) -> list:
    """Read last N executions across all bots."""
    if not os.path.exists(EXEC_LOG):
        return []
    with open(EXEC_LOG, encoding="utf-8") as f:
        lines = f.readlines()
    results = []
    for line in lines[-n:]:
        try:
            results.append(json.loads(line.strip()))
        except Exception:
            pass
    return results

def format_executions_for_prompt(executions: list) -> str:
    """Format recent executions for brain prompt."""
    if not executions:
        return "No recent executions."
    lines = []
    for e in executions[-10:]:
        ts = e.get("ts","")[-8:][:5]  # HH:MM
        pnl = f" pnl=${e['pnl_usd']:+.2f}" if e.get("pnl_usd") else ""
        lines.append(f"  {ts} [{e['bot']}] {e['side']} {e['symbol']} ${e['size_usd']:.0f} @ {e['price']}{pnl} ({e['reason']})")
    return "\n".join(lines)

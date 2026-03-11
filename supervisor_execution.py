"""
supervisor_execution.py — Shared execution log reader/writer.
Each bot appends here after every trade. Master brain reads it every cycle.
"""
import json, os, time
from datetime import datetime, timezone

EXEC_LOG = r"C:\Projects\supervisor\execution_log.jsonl"

def _append_with_retry(path: str, line: str, retries: int = 5) -> None:
    """Append a line to a shared log file with retry on write error (concurrent access)."""
    for attempt in range(retries):
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
            return
        except OSError:
            if attempt < retries - 1:
                time.sleep(0.05 * (attempt + 1))

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
    _append_with_retry(EXEC_LOG, json.dumps(entry) + "\n")

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

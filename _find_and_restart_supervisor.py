"""One-shot helper: find supervisor.py process and terminate it.
Watchdog auto-restarts within ~30-35s.
"""
import subprocess
import sys

def find_supervisor_pids():
    # Try to read CommandLine via WMI through PowerShell.
    # Some Win11 setups hide CommandLine without admin; fall back to
    # parent watchdog.py heuristic if needed.
    ps_cmd = (
        "Get-WmiObject Win32_Process -Filter \"Name='python.exe'\" | "
        "Select-Object ProcessId,CommandLine,ParentProcessId | "
        "ConvertTo-Json -Compress"
    )
    out = subprocess.check_output(
        ["powershell", "-NoProfile", "-Command", ps_cmd],
        stderr=subprocess.DEVNULL,
        text=True,
    )
    print("DEBUG: ps output =", out[:2000], file=sys.stderr)
    return []

def main():
    pids = find_supervisor_pids()
    print(f"Found {len(pids)} supervisor.py process(es): {pids}")

if __name__ == "__main__":
    main()

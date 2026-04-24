"""
cleanup_scan.py — Phase 1 inventory + classification, NO FILESYSTEM WRITES
outside the report file.

Walks:
    C:/Projects/supervisor
    C:/Projects/enzobot
    C:/Projects/alpacabot
    C:/Projects/sfmbot
    C:/Projects/memory

Skips:
    .git/        (too large, protected at top level anyway)
    .venv/       (environment, reports only size)
    node_modules/ (if present)

Classifies each file:
    protected       — never auto-delete
    archive         — keep, rotate/compress eligible
    purgeable       — safe to remove under age + path rules
    manual-review   — operator decides

Writes:
    cleanup_report_YYYY-MM-DD.md   (in supervisor/)

Zero writes to any live runtime file. No moves, no deletes, no archives.
"""
from __future__ import annotations
import fnmatch
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

BASE_DIR = Path(__file__).resolve().parent
REPORT_PATH = BASE_DIR / f"cleanup_report_{datetime.now().strftime('%Y-%m-%d')}.md"

SCAN_ROOTS = [
    r"C:\Projects\supervisor",
    r"C:\Projects\enzobot",
    r"C:\Projects\alpacabot",
    r"C:\Projects\sfmbot",
    r"C:\Projects\memory",
]

# Traversal skips (report as a single entry, don't recurse)
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", ".pytest_cache", ".mypy_cache"}

# ── Classification rules (checked in order; first match wins) ────────

# Highest priority: PROTECTED
PROTECTED_EXACT_NAMES = {
    # runtime truth
    "state.json", "alpaca_state.json", "sfm_state.json", "solana_state.json",
    "kraken_state_truth.json", "brain_state.json",
    "hermes_state_persist.json", "paperclip_bridge_state.json",
    # config / policy
    "policy.json", "governor_policy.json", "autonomy_schedule.json",
    # live overrides
    "supervisor_override.json", "sentinel_override.json", "pair_status.json",
    "alpaca_brain_overrides.json", "sfm_brain_overrides.json",
    "brain_overrides.json",
    # audit / ledgers
    "kernel_audit.jsonl", "opus_sentinel_audit.jsonl",
    "tuning_outcomes.jsonl", "autonomy_frozen_params.json",
    "autonomy_rate_state.json",
    "exit_counterfactuals.jsonl",
    "issues.jsonl", "audit_log.jsonl",
    # current packet + schedule surfaces
    "operator_packet.md", "UPGRADE_SCHEDULE.md",
    # lock / kill switches
    "maintenance_window.active", "full_mode_lockout.active",
    "OPUS_SENTINEL_PAUSE.txt", "OPUS_SENTINEL_ACTIVE.txt",
    "KERNEL_BYPASS.txt", "RESTART_REQUESTED.flag", ".brain.lock",
    # memory systems
    "MEMORY.md", "CLAUDE.md", "pending_issues.md",
    # feedback files for sleeves
    "supervisor_feedback.json", "sfm_supervisor_feedback.json",
}

PROTECTED_SUFFIXES = (".py", ".ps1", ".sh", ".key", ".pem")

PROTECTED_NAME_CONTAINS = ("credential", "secret", "api_key", "apikey", "token", "password")

PROTECTED_PATH_SEGMENTS = (
    # path parts that make a file protected regardless of name
    ".git", ".claude",
    "commands",          # commands/*_cmd.json
    ".locks",
    "openclaw_workspace",
    "hooks",             # openclaw hooks
    "readers",           # openclaw readers (source)
)

# Next: MANUAL REVIEW (specific named artifacts + risky patterns)
MANUAL_REVIEW_EXACT_NAMES = {
    "golive_report.txt", "find_procs.py", "paperclip.db",
}
MANUAL_REVIEW_PREFIXES = ("old_", "backup_", "crash_", "core.", "dump_")
MANUAL_REVIEW_CONTAINS = ("_archive_", "_backup_")  # anywhere in filename
MANUAL_REVIEW_SUFFIXES = (".bak", ".old", ".orig", ".rej")

# Next: ARCHIVE (known appendonly artifacts + logs)
ARCHIVE_EXACT_NAMES = {
    "brain_decisions.jsonl", "governor_decisions.jsonl",
    "escalation_log.jsonl", "escalation_archive.jsonl",
    "selfheal_log.jsonl", "opus_strategic_log.jsonl",
    "opus_fix_log.jsonl", "command_snapshots.jsonl",
    "governor_posture_outcomes.jsonl", "score_diag.jsonl",
    "score_adjustments.json", "alpaca_score_adjustments.json", "sfm_score_adjustments.json",
    "opus_12h_report.md", "opus_review_packet.md",
    "opus_pnl_snapshot.json", "opus_review_memory.json",
    "hermes_context.json", "hermes_escalations.jsonl",
    "brain_review_log.jsonl",
    "kraken_free_tier.json",
    "alpaca_brain_decisions.jsonl", "sfm_brain_decisions.jsonl",
    "paperclip_bridge_state.json",  # listed protected; stays protected
}
ARCHIVE_SUFFIXES = (".log", ".md")   # log files + old markdown (protected names override)
ARCHIVE_PATH_SEGMENTS = ("logs", "operator_packets", "escalations")

# Lowest: PURGEABLE (safe under age rules)
PURGEABLE_DIR_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache"}
PURGEABLE_SUFFIXES = (".pyc", ".pyo", ".tmp", ".swp", ".swo")
PURGEABLE_EXACT_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}
PURGEABLE_PATTERNS = (".#*", "*~", "*.swp", "*.tmp")

# ── Helpers ──────────────────────────────────────────────────────────

def _now() -> float:
    return datetime.now().timestamp()

def fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"

def fmt_age(sec: float) -> str:
    d = sec / 86400
    if d < 1:
        h = sec / 3600
        return f"{h:.1f}h"
    if d < 30:
        return f"{d:.0f}d"
    if d < 365:
        return f"{d/30:.1f}mo"
    return f"{d/365:.1f}y"

def _name_matches_patterns(name: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(name, p) for p in patterns)

def _path_has_segment(path: Path, segments: Iterable[str]) -> bool:
    parts_lower = [p.lower() for p in path.parts]
    return any(seg.lower() in parts_lower for seg in segments)


# ── Classifier ────────────────────────────────────────────────────────

def classify(path: Path) -> str:
    name = path.name
    name_lower = name.lower()

    # PROTECTED: path-segment-based (credentials, .git, .claude, commands, .locks,
    # openclaw_workspace, hooks, readers)
    if _path_has_segment(path, PROTECTED_PATH_SEGMENTS):
        return "protected"

    # PROTECTED: secret-ish substrings
    if any(tag in name_lower for tag in PROTECTED_NAME_CONTAINS):
        return "protected"

    # PROTECTED: protected extension
    if any(name_lower.endswith(suf) for suf in PROTECTED_SUFFIXES):
        return "protected"

    # PROTECTED: exact names
    if name in PROTECTED_EXACT_NAMES:
        return "protected"

    # .env detection (may not have .env suffix; .env.* also)
    if name_lower == ".env" or name_lower.startswith(".env."):
        return "protected"

    # MANUAL REVIEW: specific named files
    if name in MANUAL_REVIEW_EXACT_NAMES:
        return "manual-review"
    if any(name.startswith(p) for p in MANUAL_REVIEW_PREFIXES):
        return "manual-review"
    if any(tag in name for tag in MANUAL_REVIEW_CONTAINS):
        return "manual-review"
    if any(name_lower.endswith(suf) for suf in MANUAL_REVIEW_SUFFIXES):
        return "manual-review"

    # PURGEABLE: in __pycache__/.pytest_cache/etc directories
    if any(part in PURGEABLE_DIR_NAMES for part in path.parts):
        return "purgeable"
    if name in PURGEABLE_EXACT_NAMES:
        return "purgeable"
    if any(name_lower.endswith(suf) for suf in PURGEABLE_SUFFIXES):
        return "purgeable"
    if _name_matches_patterns(name, PURGEABLE_PATTERNS):
        return "purgeable"

    # ARCHIVE: exact names, path segments, suffixes
    if name in ARCHIVE_EXACT_NAMES:
        return "archive"
    if _path_has_segment(path, ARCHIVE_PATH_SEGMENTS):
        return "archive"
    if any(name_lower.endswith(suf) for suf in ARCHIVE_SUFFIXES):
        return "archive"

    # Default: unknown goes to manual-review (deny-by-default)
    return "manual-review"


# ── Walker ────────────────────────────────────────────────────────────

class FileEntry:
    __slots__ = ("path", "size", "mtime", "klass", "age_sec")
    def __init__(self, path: Path, size: int, mtime: float, klass: str):
        self.path = path
        self.size = size
        self.mtime = mtime
        self.klass = klass
        self.age_sec = _now() - mtime

def walk(roots: list[str]) -> list[FileEntry]:
    entries: list[FileEntry] = []
    skipped_trees: list[tuple[str, int, int]] = []  # (path, file_count_est, size_est)

    for root in roots:
        root_path = Path(root)
        if not root_path.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root_path):
            # Prune SKIP_DIRS (no recursion into them, but report summary)
            pruned = []
            for d in list(dirnames):
                if d in SKIP_DIRS:
                    pruned.append(d)
                    dirnames.remove(d)
            for d in pruned:
                full = Path(dirpath) / d
                # Quick shallow size estimate: sum top-level only (avoid deep walk)
                # For .git this is still expensive; just mark it's there.
                try:
                    entries_in = sum(1 for _ in full.iterdir())
                except Exception:
                    entries_in = 0
                skipped_trees.append((str(full), entries_in, 0))

            for fn in filenames:
                try:
                    full = Path(dirpath) / fn
                    st = full.stat()
                except (OSError, PermissionError):
                    continue
                klass = classify(full)
                entries.append(FileEntry(full, st.st_size, st.st_mtime, klass))

    return entries, skipped_trees


# ── Report ────────────────────────────────────────────────────────────

def _group(entries: list[FileEntry]) -> dict:
    out = {"protected": [], "archive": [], "purgeable": [], "manual-review": []}
    for e in entries:
        out.setdefault(e.klass, []).append(e)
    return out

def _by_root(entries: list[FileEntry]) -> dict:
    out = {}
    for e in entries:
        for root in SCAN_ROOTS:
            if str(e.path).lower().startswith(root.lower()):
                key = Path(root).name
                out.setdefault(key, []).append(e)
                break
    return out

def _reclaim_estimates(grouped: dict) -> list[tuple[str, str, int, int]]:
    """Rows: (phase, action, file_count, total_bytes)."""
    now = _now()
    rows = []

    purge = grouped.get("purgeable", [])
    # 2A: __pycache__ + *.pyc + OS detritus
    p2a = [e for e in purge if
           any(part in PURGEABLE_DIR_NAMES for part in e.path.parts)
           or e.path.name.lower().endswith((".pyc", ".pyo"))
           or e.path.name in PURGEABLE_EXACT_NAMES]
    rows.append(("2A", "__pycache__ + *.pyc + OS detritus",
                 len(p2a), sum(e.size for e in p2a)))

    # 2B: *.tmp older than 24h
    p2b = [e for e in purge if
           e.path.name.lower().endswith(".tmp") and (now - e.mtime) > 86400]
    rows.append(("2B", "*.tmp older than 24h",
                 len(p2b), sum(e.size for e in p2b)))

    # 2C: logs rotatable (>100MB) from archive class, suffix .log
    arch = grouped.get("archive", [])
    p2c = [e for e in arch if e.path.suffix.lower() == ".log" and e.size > 100 * 1024 * 1024]
    rows.append(("2C", "Log rotation (>100MB .log)",
                 len(p2c), sum(e.size for e in p2c)))

    # 2D: JSONL rotation (archive jsonls >100MB)
    p2d = [e for e in arch if e.path.suffix.lower() == ".jsonl" and e.size > 100 * 1024 * 1024]
    rows.append(("2D", "JSONL rotation (>100MB)",
                 len(p2d), sum(e.size for e in p2d)))

    # 2E: operator packet archive older than 30d
    p2e = [e for e in arch if "operator_packets" in [p.lower() for p in e.path.parts]
           and (now - e.mtime) > 30 * 86400]
    rows.append(("2E", "Operator packets > 30d (compress)",
                 len(p2e), sum(e.size for e in p2e)))

    return rows

def render_report(entries: list[FileEntry], skipped_trees: list) -> str:
    lines: list[str] = []
    now_iso = datetime.now(timezone.utc).isoformat()
    today = datetime.now().strftime("%Y-%m-%d")

    grouped = _group(entries)
    by_root = _by_root(entries)

    total_count = len(entries)
    total_size = sum(e.size for e in entries)

    lines.append(f"# Cleanup Scan Report — {today}")
    lines.append("")
    lines.append(f"_Generated: {now_iso}_")
    lines.append("")
    lines.append("**Mode: DRY-RUN / REPORT ONLY** — zero filesystem changes outside this file.")
    lines.append("")
    lines.append(f"Total files scanned: **{total_count:,}** "
                 f"totalling **{fmt_bytes(total_size)}**")
    if skipped_trees:
        lines.append("")
        lines.append("Skipped trees (not traversed, reported for awareness):")
        for path, cnt, _ in skipped_trees:
            lines.append(f"- `{path}` — {cnt:,} top-level entries")
    lines.append("")
    lines.append("---")
    lines.append("")

    # A. total by class
    lines.append("## A. Total file count and size by class")
    lines.append("")
    lines.append("| Class | Count | Size | % of total |")
    lines.append("|---|---:|---:|---:|")
    for klass in ("protected", "archive", "purgeable", "manual-review"):
        lst = grouped.get(klass, [])
        cnt = len(lst)
        sz = sum(e.size for e in lst)
        pct = (sz / total_size * 100) if total_size else 0
        lines.append(f"| {klass} | {cnt:,} | {fmt_bytes(sz)} | {pct:.1f}% |")
    lines.append(f"| **total** | **{total_count:,}** | **{fmt_bytes(total_size)}** | 100% |")
    lines.append("")

    # B. Size by root
    lines.append("## B. Size by scan root and class")
    lines.append("")
    lines.append("| Root | Total | Protected | Archive | Purgeable | Manual |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for root_key in sorted(by_root.keys()):
        root_entries = by_root[root_key]
        tot = sum(e.size for e in root_entries)
        prot = sum(e.size for e in root_entries if e.klass == "protected")
        arch = sum(e.size for e in root_entries if e.klass == "archive")
        purg = sum(e.size for e in root_entries if e.klass == "purgeable")
        manu = sum(e.size for e in root_entries if e.klass == "manual-review")
        lines.append(f"| {root_key} | {fmt_bytes(tot)} | {fmt_bytes(prot)} | "
                     f"{fmt_bytes(arch)} | {fmt_bytes(purg)} | {fmt_bytes(manu)} |")
    lines.append("")

    # C. Top largest candidates per class
    lines.append("## C. Top 15 largest candidates (per class)")
    lines.append("")
    for klass in ("purgeable", "archive", "manual-review"):
        lst = sorted(grouped.get(klass, []), key=lambda e: e.size, reverse=True)[:15]
        if not lst:
            continue
        lines.append(f"### {klass}")
        lines.append("")
        lines.append("| Size | Age | Path |")
        lines.append("|---:|---:|---|")
        for e in lst:
            rel = str(e.path).replace("\\", "/")
            lines.append(f"| {fmt_bytes(e.size)} | {fmt_age(e.age_sec)} | `{rel}` |")
        lines.append("")
    lines.append("")

    # D. Oldest candidates (purgeable + archive)
    lines.append("## D. Oldest 20 candidates (non-protected)")
    lines.append("")
    nonprot = [e for e in entries if e.klass != "protected"]
    nonprot.sort(key=lambda e: e.mtime)
    lines.append("| Age | Size | Class | Path |")
    lines.append("|---:|---:|---|---|")
    for e in nonprot[:20]:
        rel = str(e.path).replace("\\", "/")
        lines.append(f"| {fmt_age(e.age_sec)} | {fmt_bytes(e.size)} | {e.klass} | `{rel}` |")
    lines.append("")

    # E. Manual-review pile
    lines.append("## E. Manual-review pile (operator decides)")
    lines.append("")
    manu = sorted(grouped.get("manual-review", []), key=lambda e: e.size, reverse=True)
    lines.append(f"Total: **{len(manu):,}** files, **{fmt_bytes(sum(e.size for e in manu))}**")
    lines.append("")
    if manu:
        lines.append("### Largest 25")
        lines.append("")
        lines.append("| Size | Age | Path |")
        lines.append("|---:|---:|---|")
        for e in manu[:25]:
            rel = str(e.path).replace("\\", "/")
            lines.append(f"| {fmt_bytes(e.size)} | {fmt_age(e.age_sec)} | `{rel}` |")
        lines.append("")
    lines.append("")

    # F. Reclaim estimates
    lines.append("## F. Reclaim estimate by future phase")
    lines.append("")
    lines.append("| Phase | Action | Files | Est. Reclaim |")
    lines.append("|---|---|---:|---:|")
    for phase, action, cnt, sz in _reclaim_estimates(grouped):
        lines.append(f"| {phase} | {action} | {cnt:,} | {fmt_bytes(sz)} |")
    lines.append("")
    lines.append("_Phases are staged. Each requires separate operator approval. "
                 "Purge only after archive verification. Hard caps: 500MB or 500 files per run._")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Next step")
    lines.append("")
    lines.append("Operator review at 8 AM / 8 PM brief. "
                 "If approved: build `cleanup_run.py` executing **Phase 2A only** "
                 "(`__pycache__` + `*.pyc` + OS detritus). No other phases until "
                 "2A produces a clean audit.")

    return "\n".join(lines)


def main() -> int:
    print(f"scanning {len(SCAN_ROOTS)} roots ...", file=sys.stderr)
    entries, skipped = walk(SCAN_ROOTS)
    print(f"scanned {len(entries):,} files", file=sys.stderr)
    md = render_report(entries, skipped)
    REPORT_PATH.write_text(md, encoding="utf-8")
    print(f"report written: {REPORT_PATH}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

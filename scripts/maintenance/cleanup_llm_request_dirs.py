#!/usr/bin/env python3
import argparse
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Candidate:
    path: Path
    mtime: float
    size_bytes: int


def format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} {unit}"
        value /= 1024
    return f"{size} B"


def directory_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        if not item.is_file() or item.is_symlink():
            continue
        try:
            total += item.stat().st_size
        except OSError:
            continue
    return total


def latest_tree_mtime(path: Path) -> float:
    latest = path.stat().st_mtime
    for item in path.rglob("*"):
        if item.is_symlink():
            continue
        try:
            latest = max(latest, item.stat().st_mtime)
        except OSError:
            continue
    return latest


def find_candidates(sessions_root: Path, cutoff: float) -> list[Candidate]:
    candidates: list[Candidate] = []
    for path in sessions_root.rglob("llm_request"):
        if path.is_symlink() or not path.is_dir():
            continue
        mtime = latest_tree_mtime(path)
        if mtime >= cutoff:
            continue
        candidates.append(
            Candidate(path=path, mtime=mtime, size_bytes=directory_size(path))
        )
    return sorted(candidates, key=lambda item: item.mtime)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clean stale Sage llm_request directories under sessions."
    )
    parser.add_argument(
        "--sessions-root",
        default="sessions",
        help="Sessions root to scan (default: ./sessions).",
    )
    parser.add_argument(
        "--days",
        type=float,
        default=7,
        help="Delete llm_request directories older than this many days (default: 7).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete matched directories. Without this flag, dry-run only.",
    )
    parser.add_argument(
        "--max-list",
        type=int,
        default=200,
        help="Max candidate rows to print (default: 200; 0 = all).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sessions_root = Path(args.sessions_root).expanduser().resolve()
    if args.days <= 0:
        print("[ERROR] --days must be greater than 0", file=sys.stderr)
        return 2
    if not sessions_root.is_dir():
        print(f"[ERROR] sessions root not found: {sessions_root}", file=sys.stderr)
        return 1

    now = time.time()
    cutoff = now - args.days * 24 * 60 * 60
    candidates = find_candidates(sessions_root, cutoff)
    total_size = sum(item.size_bytes for item in candidates)
    mode = "APPLY" if args.apply else "DRY-RUN"

    print(f"[{mode}] sessions_root={sessions_root}")
    print(
        f"[{mode}] cutoff={time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(cutoff))} "
        f"({args.days:g} days)"
    )
    print(f"[{mode}] matched={len(candidates)}, total_size={format_bytes(total_size)}")

    visible = candidates if args.max_list == 0 else candidates[: args.max_list]
    for item in visible:
        mtime_text = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(item.mtime))
        rel_path = item.path.relative_to(sessions_root)
        print(f"{mtime_text}  {format_bytes(item.size_bytes):>10}  {rel_path}")
    if args.max_list > 0 and len(candidates) > args.max_list:
        print(f"... {len(candidates) - args.max_list} more not shown")

    if not args.apply:
        print("[DRY-RUN] no files deleted; rerun with --apply to delete matches")
        return 0

    deleted = 0
    failed = 0
    for item in candidates:
        try:
            shutil.rmtree(item.path)
            deleted += 1
        except OSError as exc:
            failed += 1
            print(f"[ERROR] failed to delete {item.path}: {exc}", file=sys.stderr)

    print(f"[APPLY] deleted={deleted}, failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
Run the current memory-search validation suite for P1 + P2.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str]) -> None:
    print(f"\n==> {' '.join(cmd)}")
    subprocess.run(cmd, cwd=REPO_ROOT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run memory search validation suite.")
    parser.add_argument("--noise-files", type=int, default=120, help="Synthetic benchmark noise file count.")
    parser.add_argument("--top-k", type=int, default=3, help="Top-k benchmark result count.")
    args = parser.parse_args()

    py_compile_targets = [
        "sagents/tool/impl/memory_index.py",
        "sagents/tool/impl/memory_tool.py",
        "sagents/context/session_memory/backend.py",
        "sagents/context/session_memory/bm25_backend.py",
        "sagents/context/session_memory/factory.py",
        "sagents/context/session_memory/session_memory_manager.py",
        "sagents/context/session_memory/noop_backend.py",
        "sagents/tool/impl/file_memory/backend.py",
        "sagents/tool/impl/file_memory/index_backend.py",
        "sagents/tool/impl/file_memory/factory.py",
        "sagents/tool/impl/file_memory/noop_backend.py",
        "tests/test_memory_index_fts.py",
        "tests/test_memory_tool.py",
        "tests/sagents/context/test_session_memory_manager.py",
        "tests/sagents/tool/impl/test_file_memory_backend.py",
        "scripts/memory_search_benchmark.py",
    ]

    _run([sys.executable, "-m", "py_compile", *py_compile_targets])
    _run([sys.executable, "tests/test_memory_index_fts.py"])
    _run([sys.executable, "tests/test_memory_tool.py"])
    _run([sys.executable, "tests/sagents/context/test_session_memory_manager.py"])
    _run([sys.executable, "tests/sagents/tool/impl/test_file_memory_backend.py"])
    _run(
        [
            sys.executable,
            "scripts/memory_search_benchmark.py",
            "--noise-files",
            str(args.noise_files),
            "--top-k",
            str(args.top_k),
        ]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

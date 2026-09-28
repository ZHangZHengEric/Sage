#!/usr/bin/env python3
"""
Run the current memory-search validation suite for P1 through P4.
"""

from __future__ import annotations

import argparse
import os
from tempfile import TemporaryDirectory
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(cmd: list[str]) -> None:
    print(f"\n==> {' '.join(cmd)}")
    # Validation must not write to the developer's actual Sage data directory.
    with TemporaryDirectory(prefix="sage-memory-validation-") as data_root:
        env = {
            **os.environ,
            "SAGE_LOCAL_DATA_ROOT": data_root,
            "MEMORY_ROOT_PATH": str(Path(data_root) / "memory"),
            "PYTHONPATH": str(REPO_ROOT),
        }
        subprocess.run(cmd, cwd=REPO_ROOT, env=env, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run memory search validation suite.")
    parser.add_argument(
        "--noise-files",
        type=int,
        default=120,
        help="Synthetic benchmark noise file count.",
    )
    parser.add_argument(
        "--top-k", type=int, default=3, help="Top-k benchmark result count."
    )
    args = parser.parse_args()

    py_compile_targets = [
        "sagents/v1/tool/impl/memory_index.py",
        "sagents/v1/tool/impl/memory_tool.py",
        "sagents/v1/context/session_memory/backend.py",
        "sagents/v1/context/session_memory/bm25_backend.py",
        "sagents/v1/context/session_memory/factory.py",
        "sagents/v1/context/session_memory/session_memory_manager.py",
        "sagents/v1/context/session_memory/noop_backend.py",
        "sagents/v1/context/memory_backend_registry.py",
        "sagents/v1/tool/impl/file_memory/backend.py",
        "sagents/v1/tool/impl/file_memory/index_backend.py",
        "sagents/v1/tool/impl/file_memory/factory.py",
        "sagents/v1/tool/impl/file_memory/noop_backend.py",
        "app/v1/cli/service.py",
        "tests/sagents/v1/tool/impl/test_memory_index_fts.py",
        "tests/sagents/v1/tool/impl/test_memory_tool.py",
        "tests/sagents/v1/context/test_session_memory_manager.py",
        "tests/sagents/v1/tool/impl/test_file_memory_backend.py",
        "tests/clients/cli/test_doctor_memory_backends.py",
        "scripts/v1/memory_search_benchmark.py",
    ]

    _run([sys.executable, "-m", "py_compile", *py_compile_targets])
    _run([sys.executable, "tests/sagents/v1/tool/impl/test_memory_index_fts.py"])
    _run([sys.executable, "tests/sagents/v1/tool/impl/test_memory_tool.py"])
    _run([sys.executable, "tests/sagents/v1/context/test_session_memory_manager.py"])
    _run([sys.executable, "tests/sagents/v1/tool/impl/test_file_memory_backend.py"])
    _run([sys.executable, "tests/clients/cli/test_doctor_memory_backends.py"])
    _run(
        [
            sys.executable,
            "scripts/v1/memory_search_benchmark.py",
            "--noise-files",
            str(args.noise_files),
            "--top-k",
            str(args.top_k),
        ]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

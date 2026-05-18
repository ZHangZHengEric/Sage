import argparse
import os
from pathlib import Path
import shutil
import subprocess
from typing import Iterable, Optional

from app.cli.service import CLIError


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def resolve_terminal_binary(
    *,
    env_value: Optional[str] = None,
    path_lookup: Optional[str] = None,
    repo_root: Optional[Path] = None,
) -> Optional[Path]:
    candidates = []
    if env_value:
        candidates.append(Path(env_value).expanduser())
    if path_lookup:
        candidates.append(Path(path_lookup))

    root = repo_root or _repo_root()
    source_candidates = [
        root / "app" / "terminal" / "target" / "release" / "sage-terminal",
        root / "app" / "terminal" / "target" / "debug" / "sage-terminal",
    ]
    source_candidates.sort(
        key=lambda path: path.stat().st_mtime if path.exists() else 0,
        reverse=True,
    )
    candidates.extend(source_candidates)

    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def tui_command(args: argparse.Namespace, *, terminal_args: Optional[Iterable[str]] = None) -> int:
    forwarded_args = list(terminal_args if terminal_args is not None else (args.terminal_args or []))
    terminal_bin = resolve_terminal_binary(
        env_value=os.environ.get("SAGE_TERMINAL_BIN"),
        path_lookup=shutil.which("sage-terminal"),
    )
    if terminal_bin is None:
        raise CLIError(
            "Sage Terminal TUI binary was not found.",
            next_steps=[
                "Build it with: cargo build --manifest-path app/terminal/Cargo.toml --release",
                "Then run `sage tui ...` again.",
                "Alternatively set SAGE_TERMINAL_BIN=/path/to/sage-terminal.",
            ],
        )

    return subprocess.call([str(terminal_bin), *forwarded_args])

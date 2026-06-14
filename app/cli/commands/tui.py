import argparse
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from typing import Iterable, Optional

from app.cli.service import CLIError


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _platform_binary_name() -> str:
    return "sage-terminal.exe" if os.name == "nt" else "sage-terminal"


def _launcher_name() -> str:
    return "run-sage-terminal.cmd" if os.name == "nt" else "run-sage-terminal.sh"


def _platform_tag() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower().replace("amd64", "x86_64")
    if system == "darwin":
        system = "macos"
    return f"{system}-{machine}"


def _package_terminal_candidates() -> list[Path]:
    terminal_root = Path(__file__).resolve().parents[1] / "terminal"
    binary_name = _platform_binary_name()
    launcher_name = _launcher_name()
    platform_tag = _platform_tag()
    return [
        terminal_root / "bin" / platform_tag / launcher_name,
        terminal_root / "bin" / launcher_name,
        terminal_root / "scripts" / launcher_name,
        terminal_root / "bin" / platform_tag / binary_name,
        terminal_root / "bin" / binary_name,
    ]


def resolve_terminal_binary(
    *,
    env_value: Optional[str] = None,
    path_lookup: Optional[str] = None,
    repo_root: Optional[Path] = None,
) -> Optional[Path]:
    candidates = []
    if env_value:
        candidates.append(Path(env_value).expanduser())

    candidates.extend(_package_terminal_candidates())

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


def _terminal_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("SAGE_PYTHON", sys.executable)
    return env


def tui_command(args: argparse.Namespace, *, terminal_args: Optional[Iterable[str]] = None) -> int:
    forwarded_args = list(terminal_args if terminal_args is not None else (args.terminal_args or []))
    terminal_entrypoint = resolve_terminal_binary(
        env_value=os.environ.get("SAGE_TERMINAL_BIN"),
        path_lookup=shutil.which("run-sage-terminal") or shutil.which("sage-terminal"),
    )
    if terminal_entrypoint is None:
        raise CLIError(
            "Sage Terminal TUI binary was not found.",
            next_steps=[
                "Install a Sage package that includes the Terminal TUI launcher and binary for your platform.",
                "Alternatively set SAGE_TERMINAL_BIN=/path/to/sage-terminal.",
                "For source checkout development only, build it with: cargo build --manifest-path app/terminal/Cargo.toml --release",
            ],
        )

    return subprocess.call(
        [str(terminal_entrypoint), *forwarded_args],
        env=_terminal_subprocess_env(),
    )

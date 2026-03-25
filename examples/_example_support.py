"""Shared helpers for the standalone examples."""

import sys
from pathlib import Path


HELP_FLAGS = {"-h", "--help"}
MIN_PYTHON = (3, 10)


def project_root(script_file: str) -> Path:
    return Path(script_file).resolve().parent.parent


def script_dir(script_file: str) -> Path:
    return Path(script_file).resolve().parent


def add_project_root(script_file: str) -> Path:
    root = project_root(script_file)
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    return root


def wants_help(argv=None) -> bool:
    args = sys.argv[1:] if argv is None else argv
    return any(flag in args for flag in HELP_FLAGS)


def maybe_show_help(build_parser, argv=None) -> None:
    if wants_help(argv):
        build_parser().print_help()
        raise SystemExit(0)


def ensure_python_version(script_file: str, minimum=MIN_PYTHON) -> None:
    if sys.version_info >= minimum:
        return

    root = project_root(script_file)
    version = sys.version.split()[0]
    raise SystemExit(
        f"Sage examples require Python {minimum[0]}.{minimum[1]}+; current interpreter is "
        f"{version}. Switch to Python 3.10+ and install dependencies with "
        f"`python3 -m pip install -r {root / 'requirements.txt'}`."
    )


def exit_for_missing_dependency(script_file: str, exc: ModuleNotFoundError) -> None:
    root = project_root(script_file)
    module_name = (exc.name or "unknown").split(".")[0]
    raise SystemExit(
        f"Missing dependency `{module_name}`. Install the example requirements with "
        f"`python3 -m pip install -r {root / 'requirements.txt'}` after switching to Python 3.10+."
    ) from exc

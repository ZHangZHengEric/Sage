import argparse
import json
import sys
import traceback
from typing import Any, Dict


def _build_cli_error_payload(exc: Exception, *, verbose: bool) -> Dict[str, Any]:
    from app.cli.services.base import CLIError

    try:
        from common.core.exceptions import SageHTTPException
    except Exception:  # noqa: BLE001
        SageHTTPException = None  # type: ignore[assignment]

    if isinstance(exc, CLIError):
        return {
            "type": "cli_error",
            "message": str(exc),
            "next_steps": list(exc.next_steps),
            "debug_detail": exc.debug_detail if verbose else None,
            "exit_code": exc.exit_code,
        }

    if SageHTTPException is not None and isinstance(exc, SageHTTPException):
        return {
            "type": "cli_error",
            "message": exc.detail or "Sage request failed",
            "next_steps": [],
            "debug_detail": exc.error_detail if verbose and exc.error_detail else None,
            "exit_code": 1,
        }

    if isinstance(exc, ModuleNotFoundError):
        return {
            "type": "cli_error",
            "message": f"Missing dependency: {exc.name}",
            "next_steps": [
                "Install project dependencies first, for example: `pip install -r requirements.txt`.",
                "If only `rank_bm25` is missing, install it directly with: `pip install rank-bm25`.",
            ],
            "debug_detail": None,
            "exit_code": 1,
        }

    if isinstance(exc, PermissionError):
        return {
            "type": "cli_error",
            "message": str(exc) or "Permission denied",
            "next_steps": ["Check file permissions, selected user id, and agent visibility."],
            "debug_detail": traceback.format_exc() if verbose else None,
            "exit_code": 1,
        }

    if isinstance(exc, FileNotFoundError):
        return {
            "type": "cli_error",
            "message": str(exc) or "File not found",
            "next_steps": ["Check the file or workspace path and try again."],
            "debug_detail": traceback.format_exc() if verbose else None,
            "exit_code": 1,
        }

    if isinstance(exc, (NotADirectoryError, OSError, RuntimeError, ValueError)):
        return {
            "type": "cli_error",
            "message": str(exc) or exc.__class__.__name__,
            "next_steps": [],
            "debug_detail": traceback.format_exc() if verbose else None,
            "exit_code": 1,
        }

    return {
        "type": "cli_error",
        "message": f"Unexpected CLI error: {exc}",
        "next_steps": ["Retry with `--verbose` to inspect the full error detail."],
        "debug_detail": traceback.format_exc() if verbose else None,
        "exit_code": 1,
    }


def _emit_cli_error(args: argparse.Namespace, payload: Dict[str, Any]) -> int:
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False))
        return int(payload.get("exit_code", 1))

    sys.stderr.write(f"{payload.get('message')}\n")
    next_steps = payload.get("next_steps") or []
    if next_steps:
        sys.stderr.write("Next steps:\n")
        for item in next_steps:
            sys.stderr.write(f"- {item}\n")
    debug_detail = payload.get("debug_detail")
    if debug_detail:
        sys.stderr.write("\n[debug]\n")
        sys.stderr.write(f"{debug_detail.rstrip()}\n")
    sys.stderr.flush()
    return int(payload.get("exit_code", 1))

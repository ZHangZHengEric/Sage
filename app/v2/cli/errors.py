import argparse
import json
import sys
import traceback
from typing import Any, Dict



from typing import List, Optional
class CLIError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        next_steps: Optional[List[str]] = None,
        debug_detail: Optional[str] = None,
        exit_code: int = 1,
    ) -> None:
        super().__init__(message)
        self.next_steps = list(next_steps or [])
        self.debug_detail = debug_detail
        self.exit_code = exit_code


def _build_cli_error_payload(exc: Exception, *, verbose: bool) -> Dict[str, Any]:


    if isinstance(exc, CLIError):
        return {
            "type": "cli_error",
            "message": str(exc),
            "next_steps": list(exc.next_steps),
            "debug_detail": exc.debug_detail if verbose else None,
            "exit_code": exc.exit_code,
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
            "next_steps": [
                "Check file permissions, selected user id, and agent visibility."
            ],
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

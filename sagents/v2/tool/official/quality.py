"""Decorator-backed V2 lint Tool."""

from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Any

from sagents.v2.tool import SideEffectLevel, ToolInvocation, tool
from sagents.v2.tool.official.runtime import OfficialToolRuntime


class QualityTools:
    def __init__(self, runtime: OfficialToolRuntime) -> None:
        self.runtime = runtime

    @tool(
        description="Run available linters for Python and JavaScript/TypeScript files.",
        side_effect_level=SideEffectLevel.READ,
    )
    async def read_lints(
        self,
        paths: list[str],
        invocation: ToolInvocation,
        max_diagnostics: int = 50,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        del session_id
        if not paths:
            raise ValueError("paths must be a non-empty list")
        python_paths = [path for path in paths if PurePosixPath(path).suffix == ".py"]
        script_paths = [
            path
            for path in paths
            if PurePosixPath(path).suffix in {".js", ".jsx", ".ts", ".tsx", ".vue"}
        ]
        diagnostics: list[dict[str, Any]] = []
        linters: dict[str, Any] = {}
        if python_paths:
            result = await self.runtime.shell(
                "ruff check --output-format json -- "
                + " ".join(_shell_quote(path) for path in python_paths),
                invocation,
                workdir=None,
                env_vars={},
                block_until_ms=120_000,
            )
            linters["ruff"] = _linter_status(result)
            try:
                values = json.loads(result.get("stdout") or "[]")
                for value in values:
                    location = value.get("location") or {}
                    diagnostics.append(
                        {
                            "path": value.get("filename"),
                            "line": location.get("row"),
                            "column": location.get("column"),
                            "code": value.get("code"),
                            "message": value.get("message"),
                            "source": "ruff",
                        }
                    )
            except (TypeError, ValueError):
                pass
        if script_paths:
            result = await self.runtime.shell(
                "npx eslint --format json -- "
                + " ".join(_shell_quote(path) for path in script_paths),
                invocation,
                workdir=None,
                env_vars={},
                block_until_ms=120_000,
            )
            linters["eslint"] = _linter_status(result)
            try:
                values = json.loads(result.get("stdout") or "[]")
                for file_result in values:
                    for value in file_result.get("messages") or []:
                        diagnostics.append(
                            {
                                "path": file_result.get("filePath"),
                                "line": value.get("line"),
                                "column": value.get("column"),
                                "code": value.get("ruleId"),
                                "message": value.get("message"),
                                "source": "eslint",
                            }
                        )
            except (TypeError, ValueError):
                pass
        limit = max(1, max_diagnostics)
        return {
            "success": True,
            "status": "success",
            "diagnostics": diagnostics[:limit],
            "diagnostics_count": len(diagnostics),
            "truncated": len(diagnostics) > limit,
            "linters": linters,
            "skipped_linters": [
                name for name, value in linters.items() if value["status"] == "skipped"
            ],
        }


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _linter_status(result: dict[str, Any]) -> dict[str, Any]:
    output = str(result.get("stdout") or "")
    if result.get("exit_code") == 127 or "command not found" in output:
        return {"status": "skipped", "reason": "linter is not installed"}
    return {
        "status": "completed",
        "exit_code": result.get("exit_code"),
    }

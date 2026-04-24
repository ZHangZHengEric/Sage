#!/usr/bin/env python3
"""
Lint Tool

通过沙箱执行常见 linter（ruff / eslint / tsc），把诊断统一成 LSP 风格。
返回 ``{file, line, col, severity, code, message, source}``。
若 linter 未安装则返回 ``status="skipped"`` 而不是静默成功，避免 agent 误以为没有问题。
"""

from __future__ import annotations

import json
import os
import shlex
from typing import Any, Dict, List, Optional, Tuple

from ..tool_base import tool
from ..error_codes import ToolErrorCode, make_tool_error
from sagents.utils.logger import logger
from sagents.utils.agent_session_helper import get_session_sandbox as _get_session_sandbox_util


_PY_EXTS = {".py", ".pyi"}
_JS_EXTS = {".js", ".jsx", ".mjs", ".cjs"}
_TS_EXTS = {".ts", ".tsx"}
_VUE_EXTS = {".vue"}
_ESLINT_EXTS = _JS_EXTS | _TS_EXTS | _VUE_EXTS


def _classify(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in _PY_EXTS:
        return "python"
    if ext in _TS_EXTS:
        return "ts"
    if ext in _ESLINT_EXTS:
        return "js"
    return "other"


class LintTool:
    """通用 lint 工具：在沙箱中调用 ruff / eslint / tsc。"""

    def _get_sandbox(self, session_id: str):
        return _get_session_sandbox_util(session_id, log_prefix="LintTool")

    async def _run(self, sandbox: Any, command: str, timeout: int = 60) -> Tuple[int, str, str]:
        """在沙箱中执行命令，返回 (return_code, stdout, stderr)。失败时 return_code=-1。"""
        try:
            result = await sandbox.execute_command(command=command, timeout=timeout)
            return (
                int(getattr(result, "return_code", -1) or 0),
                getattr(result, "stdout", "") or "",
                getattr(result, "stderr", "") or "",
            )
        except Exception as exc:
            logger.warning(f"LintTool: 命令执行失败 cmd={command!r} err={exc}")
            return -1, "", str(exc)

    async def _has_command(self, sandbox: Any, name: str) -> bool:
        # 跨平台命令探测：POSIX 用 ``command -v``，Windows 用 ``where``。
        if os.name == "nt":
            cmd = f"where {name}"
        else:
            cmd = f"command -v {shlex.quote(name)}"
        rc, out, _ = await self._run(sandbox, cmd, timeout=5)
        return rc == 0 and bool((out or "").strip())

    async def _lint_python(self, sandbox: Any, paths: List[str]) -> Dict[str, Any]:
        if not await self._has_command(sandbox, "ruff"):
            return {"status": "skipped", "reason": "ruff not installed"}
        joined = " ".join(shlex.quote(p) for p in paths)
        rc, out, err = await self._run(
            sandbox,
            f"ruff check --output-format=json {joined}",
            timeout=60,
        )
        if rc not in (0, 1):  # ruff: 0=clean, 1=有诊断, 其他=工具自身错
            return {"status": "error", "reason": f"ruff exited {rc}: {err.strip() or out.strip()[:200]}"}
        diagnostics: List[Dict[str, Any]] = []
        try:
            payload = json.loads(out) if out.strip() else []
            if isinstance(payload, list):
                for item in payload:
                    loc = (item.get("location") or {}) if isinstance(item, dict) else {}
                    diagnostics.append({
                        "file": item.get("filename"),
                        "line": loc.get("row"),
                        "col": loc.get("column"),
                        "severity": "error",  # ruff check 默认全是 error/violation
                        "code": item.get("code"),
                        "message": item.get("message"),
                        "source": "ruff",
                    })
        except Exception as exc:
            logger.warning(f"LintTool: 解析 ruff 输出失败: {exc}")
            return {"status": "error", "reason": f"parse ruff output failed: {exc}"}
        return {"status": "ok", "diagnostics": diagnostics}

    async def _lint_eslint(self, sandbox: Any, paths: List[str]) -> Dict[str, Any]:
        if not await self._has_command(sandbox, "eslint"):
            return {"status": "skipped", "reason": "eslint not installed"}
        joined = " ".join(shlex.quote(p) for p in paths)
        # eslint 在没有配置时会报错；忽略这种情况返回 skipped
        rc, out, err = await self._run(
            sandbox,
            f"eslint --format json {joined}",
            timeout=120,
        )
        if rc not in (0, 1, 2):
            err_text = (err or out or "").lower()
            if "no eslint configuration" in err_text or "couldn't find a configuration" in err_text:
                return {"status": "skipped", "reason": "no eslint config in project"}
            return {"status": "error", "reason": f"eslint exited {rc}: {err.strip()[:200]}"}
        diagnostics: List[Dict[str, Any]] = []
        try:
            payload = json.loads(out) if out.strip() else []
            if isinstance(payload, list):
                for f in payload:
                    fname = f.get("filePath") if isinstance(f, dict) else None
                    for m in (f.get("messages") or []):
                        diagnostics.append({
                            "file": fname,
                            "line": m.get("line"),
                            "col": m.get("column"),
                            "severity": "error" if m.get("severity") == 2 else "warning",
                            "code": m.get("ruleId"),
                            "message": m.get("message"),
                            "source": "eslint",
                        })
        except Exception as exc:
            logger.warning(f"LintTool: 解析 eslint 输出失败: {exc}")
            return {"status": "error", "reason": f"parse eslint output failed: {exc}"}
        return {"status": "ok", "diagnostics": diagnostics}

    async def _lint_tsc(self, sandbox: Any, paths: List[str]) -> Dict[str, Any]:
        if not await self._has_command(sandbox, "tsc"):
            return {"status": "skipped", "reason": "tsc not installed"}
        # 仅尝试 noEmit；找不到 tsconfig 直接 skip
        # 这里不限定具体 path，由项目 tsconfig 控制
        rc, out, err = await self._run(sandbox, "tsc --noEmit", timeout=180)
        text = out + "\n" + err
        if "Cannot find a tsconfig" in text or "No inputs were found" in text:
            return {"status": "skipped", "reason": "no tsconfig.json found"}
        if rc not in (0, 1, 2):
            return {"status": "error", "reason": f"tsc exited {rc}"}
        diagnostics: List[Dict[str, Any]] = []
        # tsc 输出格式：path(line,col): error TSxxxx: message
        path_set = {os.path.normpath(p) for p in paths}
        for line in text.splitlines():
            line = line.strip()
            if not line or ": error TS" not in line and ": warning TS" not in line:
                continue
            try:
                head, _, message = line.partition(": ")
                if "(" in head and head.endswith(")"):
                    file_part, loc_part = head.rsplit("(", 1)
                    loc_part = loc_part.rstrip(")")
                    line_no_str, col_str = loc_part.split(",", 1)
                    severity_part, _, code_part = message.partition(" ")
                    severity = "error" if severity_part == "error" else "warning"
                    code = code_part.split(":", 1)[0].strip()
                    msg = message.split(":", 1)[1].strip() if ":" in message else message
                    file_norm = os.path.normpath(file_part)
                    if path_set and not any(file_norm.endswith(p) or p.endswith(file_norm) for p in path_set):
                        continue
                    diagnostics.append({
                        "file": file_part,
                        "line": int(line_no_str),
                        "col": int(col_str),
                        "severity": severity,
                        "code": code,
                        "message": msg,
                        "source": "tsc",
                    })
            except Exception:
                continue
        return {"status": "ok", "diagnostics": diagnostics}

    async def _collect_for_paths(
        self,
        sandbox: Any,
        paths: List[str],
        max_diagnostics: int,
    ) -> Dict[str, Any]:
        groups: Dict[str, List[str]] = {"python": [], "js": [], "ts": [], "other": []}
        for p in paths:
            groups[_classify(p)].append(p)

        per_linter: Dict[str, Dict[str, Any]] = {}
        all_diags: List[Dict[str, Any]] = []

        if groups["python"]:
            per_linter["ruff"] = await self._lint_python(sandbox, groups["python"])
            all_diags.extend(per_linter["ruff"].get("diagnostics", []) or [])

        eslint_targets = groups["js"] + groups["ts"]
        if eslint_targets:
            per_linter["eslint"] = await self._lint_eslint(sandbox, eslint_targets)
            all_diags.extend(per_linter["eslint"].get("diagnostics", []) or [])

        if groups["ts"]:
            per_linter["tsc"] = await self._lint_tsc(sandbox, groups["ts"])
            all_diags.extend(per_linter["tsc"].get("diagnostics", []) or [])

        truncated = False
        if len(all_diags) > max_diagnostics:
            all_diags = all_diags[:max_diagnostics]
            truncated = True

        skipped = [k for k, v in per_linter.items() if v.get("status") == "skipped"]
        return {
            "success": True,
            "status": "success",
            "diagnostics": all_diags,
            "diagnostics_count": len(all_diags),
            "truncated": truncated,
            "linters": per_linter,
            "skipped_linters": skipped,
        }

    @tool(
        description_i18n={
            "zh": "对指定文件运行 lint（ruff/eslint/tsc），返回结构化诊断。仅对 .py / .ts(x) / .js(x) / .vue 文件有效；linter 未安装会标记为 skipped 而非静默成功。",
            "en": "Run linters (ruff/eslint/tsc) on the given files and return structured diagnostics. Only effective for .py / .ts(x) / .js(x) / .vue files. Missing linters are reported as skipped instead of being silently treated as clean.",
        },
        param_description_i18n={
            "paths": {"zh": "要 lint 的文件虚拟路径列表", "en": "Virtual paths of files to lint"},
            "max_diagnostics": {"zh": "最多返回的诊断条数，默认 50", "en": "Maximum number of diagnostics to return, default 50"},
            "session_id": {"zh": "会话ID（必填，自动注入）", "en": "Session ID (Required, Auto-injected)"},
        },
        param_schema={
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Virtual paths of files to lint",
            },
            "max_diagnostics": {"type": "integer", "default": 50},
            "session_id": {"type": "string", "description": "Session ID"},
        },
    )
    async def read_lints(
        self,
        paths: List[str],
        max_diagnostics: int = 50,
        session_id: str = None,
    ) -> Dict[str, Any]:
        if not session_id:
            raise ValueError("LintTool: session_id is required")
        if not paths or not isinstance(paths, list):
            return make_tool_error(
                ToolErrorCode.INVALID_ARGUMENT,
                "paths 必须是非空字符串数组",
            )
        try:
            sandbox = self._get_sandbox(session_id)
        except Exception as exc:
            return make_tool_error(
                ToolErrorCode.SANDBOX_ERROR,
                f"获取沙箱失败: {exc}",
            )
        try:
            return await self._collect_for_paths(sandbox, paths, max_diagnostics)
        except Exception as exc:
            logger.error(f"LintTool: 运行失败: {exc}")
            return make_tool_error(
                ToolErrorCode.INTERNAL_ERROR,
                f"运行 lint 失败: {exc}",
            )

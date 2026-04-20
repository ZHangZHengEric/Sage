from __future__ import annotations

import ast
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import tomllib
except Exception:  # pragma: no cover - Python < 3.11 fallback is not expected here
    tomllib = None

try:
    import yaml
except Exception:  # pragma: no cover - yaml should usually be available
    yaml = None


class FileContentValidator:
    """Validate common text file formats after write/update operations."""

    SUPPORTED_EXTENSIONS = {
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".py": "python",
        ".toml": "toml",
        ".js": "javascript",
        ".mjs": "javascript",
        ".cjs": "javascript",
    }

    @staticmethod
    def validate(file_path: str, content: str) -> Dict[str, Any]:
        extension = Path(file_path).suffix.lower()
        validator = FileContentValidator.SUPPORTED_EXTENSIONS.get(extension)
        if not validator:
            return {
                "enabled": False,
                "skipped": True,
                "passed": True,
                "status": "skipped",
                "validator": None,
                "file_extension": extension,
                "message": "该文件后缀未启用内容校验",
                "warnings": [],
                "errors": [],
            }

        if validator == "json":
            return FileContentValidator._validate_json(extension, content)
        if validator == "yaml":
            return FileContentValidator._validate_yaml(extension, content)
        if validator == "python":
            return FileContentValidator._validate_python(extension, content)
        if validator == "toml":
            return FileContentValidator._validate_toml(extension, content)
        if validator == "javascript":
            return FileContentValidator._validate_javascript(extension, content)

        return {
            "enabled": False,
            "skipped": True,
            "passed": True,
            "status": "skipped",
            "validator": validator,
            "file_extension": extension,
            "message": "未找到匹配的校验器",
            "warnings": [],
            "errors": [],
        }

    @staticmethod
    def _success(extension: str, validator: str, message: str = "内容校验通过", warnings: Optional[List[str]] = None) -> Dict[str, Any]:
        return {
            "enabled": True,
            "skipped": False,
            "passed": True,
            "status": "passed" if not warnings else "warning",
            "validator": validator,
            "file_extension": extension,
            "message": message,
            "warnings": warnings or [],
            "errors": [],
        }

    @staticmethod
    def _error(extension: str, validator: str, message: str, warnings: Optional[List[str]] = None) -> Dict[str, Any]:
        return {
            "enabled": True,
            "skipped": False,
            "passed": False,
            "status": "error",
            "validator": validator,
            "file_extension": extension,
            "message": message,
            "warnings": warnings or [],
            "errors": [message],
        }

    @staticmethod
    def _validate_json(extension: str, content: str) -> Dict[str, Any]:
        try:
            json.loads(content)
            return FileContentValidator._success(extension, "json")
        except json.JSONDecodeError as exc:
            message = f"JSON 语法错误: {exc.msg} (line {exc.lineno}, column {exc.colno})"
            return FileContentValidator._error(extension, "json", message)
        except Exception as exc:
            return FileContentValidator._error(extension, "json", f"JSON 校验失败: {exc}")

    @staticmethod
    def _validate_yaml(extension: str, content: str) -> Dict[str, Any]:
        if yaml is None:
            return {
                "enabled": False,
                "skipped": True,
                "passed": True,
                "status": "skipped",
                "validator": "yaml",
                "file_extension": extension,
                "message": "PyYAML 未安装，已跳过 YAML 校验",
                "warnings": [],
                "errors": [],
            }
        try:
            yaml.safe_load(content)
            return FileContentValidator._success(extension, "yaml")
        except yaml.YAMLError as exc:  # type: ignore[attr-defined]
            message = f"YAML 语法错误: {exc}"
            mark = getattr(exc, "problem_mark", None)
            if mark is not None:
                line = getattr(mark, "line", None)
                column = getattr(mark, "column", None)
                if line is not None and column is not None:
                    message = f"YAML 语法错误: {exc} (line {line + 1}, column {column + 1})"
            return FileContentValidator._error(extension, "yaml", message)
        except Exception as exc:
            return FileContentValidator._error(extension, "yaml", f"YAML 校验失败: {exc}")

    @staticmethod
    def _validate_python(extension: str, content: str) -> Dict[str, Any]:
        try:
            ast.parse(content)
            return FileContentValidator._success(extension, "python")
        except SyntaxError as exc:
            line = exc.lineno or 0
            column = exc.offset or 0
            message = f"Python 语法错误: {exc.msg} (line {line}, column {column})"
            return FileContentValidator._error(extension, "python", message)
        except Exception as exc:
            return FileContentValidator._error(extension, "python", f"Python 校验失败: {exc}")

    @staticmethod
    def _validate_toml(extension: str, content: str) -> Dict[str, Any]:
        if tomllib is None:
            return {
                "enabled": False,
                "skipped": True,
                "passed": True,
                "status": "skipped",
                "validator": "toml",
                "file_extension": extension,
                "message": "tomllib 不可用，已跳过 TOML 校验",
                "warnings": [],
                "errors": [],
            }
        try:
            tomllib.loads(content)
            return FileContentValidator._success(extension, "toml")
        except tomllib.TOMLDecodeError as exc:  # type: ignore[attr-defined]
            message = f"TOML 语法错误: {exc}"
            line = getattr(exc, "lineno", None)
            column = getattr(exc, "colno", None)
            if line is not None and column is not None:
                message = f"TOML 语法错误: {exc} (line {line}, column {column})"
            return FileContentValidator._error(extension, "toml", message)
        except Exception as exc:
            return FileContentValidator._error(extension, "toml", f"TOML 校验失败: {exc}")

    @staticmethod
    def _validate_javascript(extension: str, content: str) -> Dict[str, Any]:
        node = shutil.which("node")
        if not node:
            return {
                "enabled": False,
                "skipped": True,
                "passed": True,
                "status": "skipped",
                "validator": "javascript",
                "file_extension": extension,
                "message": "未找到 node，已跳过 JavaScript 语法校验",
                "warnings": [],
                "errors": [],
            }

        suffix = extension if extension in {".js", ".mjs", ".cjs"} else ".js"
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            proc = subprocess.run(
                [node, "--check", tmp_path],
                capture_output=True,
                text=True,
            )
            if proc.returncode == 0:
                return FileContentValidator._success(extension, "javascript")

            stderr = (proc.stderr or proc.stdout or "").strip()
            message = f"JavaScript 语法错误: {stderr or 'node --check failed'}"
            return FileContentValidator._error(extension, "javascript", message)
        except Exception as exc:
            return FileContentValidator._error(extension, "javascript", f"JavaScript 校验失败: {exc}")
        finally:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass

"""
OpenSandbox 远程沙箱实现
"""

import asyncio
import ast
import base64
import json
import os
import re
import shlex
from datetime import timedelta
from typing import Dict, List, Optional

from .base import RemoteSandboxProvider
from ...interface import CommandResult, ExecutionResult, FileInfo
from ...config import MountPath
from sagents.utils.logger import logger


def _get_max_append_bytes() -> int:
    default_bytes = 256 * 1024  # 256KB safety limit for env-based append payloads
    raw = os.environ.get("SAGE_OPENSANDBOX_APPEND_MAX_BYTES")
    if not raw:
        return default_bytes
    try:
        value = int(raw)
        if value <= 0:
            return default_bytes
        return value
    except Exception:
        return default_bytes


MAX_APPEND_BYTES = _get_max_append_bytes()


def _read_host_file_bytes_sync(host_path: str) -> bytes:
    with open(host_path, "rb") as f:
        return f.read()


def _write_host_file_bytes_sync(host_path: str, data: bytes) -> None:
    host_dir = os.path.dirname(host_path)
    if host_dir:
        os.makedirs(host_dir, exist_ok=True)
    with open(host_path, "wb") as f:
        f.write(data)


class OpenSandboxProvider(RemoteSandboxProvider):
    """OpenSandbox 远程沙箱实现"""

    def __init__(
        self,
        sandbox_id: str,
        server_url: str,
        api_key: Optional[str] = None,
        image: str = "opensandbox/code-interpreter:v1.0.2",
        timeout: timedelta = timedelta(minutes=30),
        workspace_mount: Optional[str] = None,
        mount_paths: Optional[List[MountPath]] = None,
        virtual_workspace: str = "/sage-workspace",
        persistent: bool = True,
        sandbox_ttl: int = 3600,
    ):
        super().__init__(
            sandbox_id=sandbox_id,
            workspace_mount=workspace_mount,
            mount_paths=mount_paths,
            virtual_workspace=virtual_workspace,
            timeout=timeout,
        )
        self.server_url = server_url
        self.api_key = api_key
        self.image = image
        self.persistent = persistent
        self.sandbox_ttl = sandbox_ttl
        self._sdk = None

    async def initialize(self) -> None:
        """初始化 OpenSandbox 远程沙箱"""
        try:
            from opensandbox import Sandbox as OSSandbox
            from opensandbox.models import Mount
        except ImportError:
            raise ImportError(
                "opensandbox package is required. "
                "Install with: pip install opensandbox"
            )

        # 构建挂载配置
        mounts = []

        # 工作区挂载
        if self.workspace_mount:
            mounts.append(
                Mount(
                    source=self.workspace_mount,
                    target=self._workspace_path,
                    type="bind",
                )
            )

        # 额外的路径映射
        for mp in self.mount_paths:
            mounts.append(
                Mount(
                    source=mp.host_path,
                    target=mp.sandbox_path,
                    type="bind",
                    read_only=mp.read_only,
                )
            )

        # 如果持久化且已有沙箱ID，尝试连接已有沙箱
        if self.persistent and self._sandbox_id:
            try:
                self._sdk = await OSSandbox.get(
                    self._sandbox_id,
                    server_url=self.server_url,
                    api_key=self.api_key,
                )
                logger.info(f"OpenSandboxProvider: 复用已有沙箱 {self._sandbox_id}")
                self._is_initialized = True
                return
            except Exception as e:
                logger.warning(
                    f"OpenSandboxProvider: 无法复用沙箱 {self._sandbox_id}, 创建新沙箱: {e}"
                )

        # 创建新沙箱
        self._sdk = await OSSandbox.create(
            image=self.image,
            entrypoint=["/opt/opensandbox/code-interpreter.sh"],
            timeout=self.timeout,
            mounts=mounts if mounts else None,
            labels={
                "sandbox_id": self._sandbox_id,
                "persistent": str(self.persistent),
            }
            if self._sandbox_id
            else None,
        )

        self._is_initialized = True
        logger.info(f"OpenSandboxProvider: 沙箱初始化完成 {self._sandbox_id}")

    async def execute_command(
        self,
        command: str,
        workdir: Optional[str] = None,
        timeout: int = 30,
        env_vars: Optional[Dict[str, str]] = None,
        background: bool = False,
    ) -> CommandResult:
        """在远程沙箱执行命令"""
        if not self._is_initialized:
            await self.initialize()

        effective_command = command
        if workdir:
            effective_command = f"cd {shlex.quote(workdir)} && {command}"

        async with self._sdk:
            execution = await self._sdk.commands.run(
                effective_command, timeout=timeout, env=env_vars or {}
            )

            return CommandResult(
                success=execution.exit_code == 0,
                stdout="\n".join([log.text for log in execution.logs.stdout]),
                stderr="\n".join([log.text for log in execution.logs.stderr]),
                return_code=execution.exit_code,
                execution_time=execution.duration,
            )

    async def execute_python(
        self,
        code: str,
        requirements: Optional[List[str]] = None,
        workdir: Optional[str] = None,
        timeout: int = 60,
    ) -> ExecutionResult:
        """在远程沙箱执行 Python 代码"""
        if not self._is_initialized:
            await self.initialize()

        if workdir:
            code = self._inject_workdir(code, workdir)

        try:
            from code_interpreter import CodeInterpreter, SupportedLanguage
        except ImportError:
            raise ImportError(
                "opensandbox-code-interpreter package is required. "
                "Install with: pip install opensandbox-code-interpreter"
            )

        async with self._sdk:
            interpreter = await CodeInterpreter.create(self._sdk)

            result = await interpreter.codes.run(
                code, language=SupportedLanguage.PYTHON, timeout=timeout
            )

            return ExecutionResult(
                success=result.exit_code == 0,
                output=result.result[0].text if result.result else "",
                error=result.logs.stderr[0].text if result.logs.stderr else None,
                execution_time=result.duration,
                installed_packages=requirements or [],
            )

    async def execute_javascript(
        self,
        code: str,
        packages: Optional[List[str]] = None,
        workdir: Optional[str] = None,
        timeout: int = 60,
    ) -> ExecutionResult:
        """在远程沙箱执行 JavaScript 代码"""
        # OpenSandbox 默认镜像可能不包含 Node.js
        # 这里通过命令执行方式实现
        command = f"node -e '{code}'"
        result = await self.execute_command(command, workdir, timeout)
        return ExecutionResult(
            success=result.success,
            output=result.stdout,
            error=result.stderr if not result.success else None,
            execution_time=result.execution_time,
            installed_packages=packages or [],
        )

    async def read_file(self, path: str, encoding: str = "utf-8") -> str:
        """从远程沙箱读取文件"""
        if not self._is_initialized:
            await self.initialize()

        async with self._sdk:
            return await self._sdk.files.read_file(path)

    async def write_file(
        self,
        path: str,
        content: str,
        encoding: str = "utf-8",
        mode: str = "overwrite",
    ) -> None:
        """写入文件到远程沙箱"""
        if not self._is_initialized:
            await self.initialize()

        try:
            from opensandbox.models import WriteEntry
        except ImportError:
            raise ImportError("opensandbox package is required")

        if mode == "append":
            data = content.encode(encoding) if isinstance(content, str) else content
            if len(data) > MAX_APPEND_BYTES:
                raise ValueError(
                    f"append content too large ({len(data)} bytes). "
                    f"Limit is {MAX_APPEND_BYTES} bytes. "
                    "Use overwrite or chunked append."
                )
            data_b64 = base64.b64encode(data).decode("ascii")
            append_cmd = (
                "python - <<'PY'\n"
                "import os, base64\n"
                "path = os.environ.get('SAGE_APPEND_PATH')\n"
                "data = base64.b64decode(os.environ.get('SAGE_APPEND_B64',''))\n"
                "if not path:\n"
                "    raise RuntimeError('Missing SAGE_APPEND_PATH')\n"
                "dir_path = os.path.dirname(path)\n"
                "if dir_path:\n"
                "    os.makedirs(dir_path, exist_ok=True)\n"
                "with open(path, 'ab') as f:\n"
                "    f.write(data)\n"
                "PY"
            )
            await self.execute_command(
                append_cmd,
                env_vars={
                    "SAGE_APPEND_PATH": path,
                    "SAGE_APPEND_B64": data_b64,
                },
            )
            return

        async with self._sdk:
            await self._sdk.files.write_files(
                [WriteEntry(path=path, data=content, mode=644)]
            )

    async def file_exists(self, path: str) -> bool:
        """检查文件是否存在"""
        try:
            await self.read_file(path)
            return True
        except Exception:
            return False

    async def list_directory(
        self,
        path: str,
        include_hidden: bool = False,
    ) -> List[FileInfo]:
        """列出目录内容"""
        # OpenSandbox 可能不直接支持 list_directory，这里通过 Python 输出 JSON 实现，避免解析 ls 文本
        list_cmd = (
            "python - <<'PY'\n"
            "import json, os\n"
            "path = os.environ.get('SAGE_LS_PATH')\n"
            "include_hidden = os.environ.get('SAGE_LS_HIDDEN') == '1'\n"
            "entries = []\n"
            "if path and os.path.isdir(path):\n"
            "    for entry in os.scandir(path):\n"
            "        name = entry.name\n"
            "        if not include_hidden and name.startswith('.'):\n"
            "            continue\n"
            "        try:\n"
            "            st = entry.stat(follow_symlinks=False)\n"
            "        except FileNotFoundError:\n"
            "            continue\n"
            "        entries.append({\n"
            "            'name': name,\n"
            "            'is_file': entry.is_file(follow_symlinks=False),\n"
            "            'is_dir': entry.is_dir(follow_symlinks=False),\n"
            "            'size': st.st_size,\n"
            "            'modified_time': st.st_mtime,\n"
            "        })\n"
            "print(json.dumps(entries))\n"
            "PY"
        )
        result = await self.execute_command(
            list_cmd,
            env_vars={
                "SAGE_LS_PATH": path,
                "SAGE_LS_HIDDEN": "1" if include_hidden else "0",
            },
        )
        if not result.success:
            sample = (result.stderr or result.stdout or "").strip()
            if len(sample) > 300:
                sample = sample[:300] + "..."
            logger.warning(
                "OpenSandboxProvider.list_directory failed for %s: %s",
                path,
                sample or "no output",
            )
            return []

        if not result.stdout.strip():
            return []

        try:
            payload = json.loads(result.stdout.strip())
        except Exception:
            sample = result.stdout.strip()
            if len(sample) > 300:
                sample = sample[:300] + "..."
            logger.warning(
                "OpenSandboxProvider.list_directory JSON parse failed for %s: %s",
                path,
                sample or "empty output",
            )
            return []

        entries: List[FileInfo] = []
        for item in payload:
            try:
                name = item.get("name")
                if not name:
                    continue
                entry_path = os.path.join(path, name)
                entries.append(
                    FileInfo(
                        path=entry_path,
                        is_file=bool(item.get("is_file")),
                        is_dir=bool(item.get("is_dir")),
                        size=int(item.get("size", 0)),
                        modified_time=float(item.get("modified_time", 0.0)),
                    )
                )
            except Exception:
                continue

        return entries

    def _inject_workdir(self, code: str, workdir: str) -> str:
        """在不破坏 future imports / 模块 docstring 的情况下插入 chdir。"""
        if not workdir:
            return code

        lines = code.splitlines(keepends=True)

        prefix_end = 0
        if lines and lines[0].startswith("#!"):
            prefix_end = 1
        if len(lines) > prefix_end and re.match(r"^#.*coding[:=]\s*[-\w.]+", lines[prefix_end]):
            prefix_end += 1

        insert_after = 0
        try:
            tree = ast.parse(code)
            if tree.body:
                first = tree.body[0]
                if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant) and isinstance(first.value.value, str):
                    insert_after = max(insert_after, getattr(first, "end_lineno", first.lineno))
                for node in tree.body:
                    if isinstance(node, ast.ImportFrom) and node.module == "__future__":
                        insert_after = max(insert_after, getattr(node, "end_lineno", node.lineno))
        except Exception:
            insert_after = 0

        insert_line = max(insert_after, prefix_end)
        insert_idx = min(insert_line, len(lines))
        inject = f"import os\nos.chdir({workdir!r})\n"
        lines.insert(insert_idx, inject)
        return "".join(lines)

    async def ensure_directory(self, path: str) -> None:
        """确保目录存在"""
        await self.execute_command(f"mkdir -p {shlex.quote(path)}")

    async def delete_file(self, path: str) -> None:
        """删除文件"""
        await self.execute_command(f"rm -rf {shlex.quote(path)}")

    async def upload_file(self, host_path: str, sandbox_path: str) -> None:
        """上传文件到远程沙箱"""
        if not self._is_initialized:
            await self.initialize()

        try:
            from opensandbox.models import WriteEntry
        except ImportError:
            raise ImportError("opensandbox package is required")

        content = await asyncio.to_thread(_read_host_file_bytes_sync, host_path)

        async with self._sdk:
            await self._sdk.files.write_files(
                [WriteEntry(path=sandbox_path, data=content, mode=644)]
            )

        logger.debug(f"OpenSandboxProvider: 上传文件 {host_path} -> {sandbox_path}")

    async def download_file(self, sandbox_path: str, host_path: str) -> None:
        """从远程沙箱下载文件"""
        if not self._is_initialized:
            await self.initialize()

        async with self._sdk:
            content = await self._sdk.files.read_file(sandbox_path)

        data = content.encode("utf-8") if isinstance(content, str) else content

        await asyncio.to_thread(_write_host_file_bytes_sync, host_path, data)

        logger.debug(f"OpenSandboxProvider: 下载文件 {sandbox_path} -> {host_path}")

    async def cleanup(self) -> None:
        """清理沙箱资源 - 断开连接，不删除沙箱

        远程沙箱保持运行状态，通过 sandbox_id 可以重新连接
        """
        if self._sdk:
            if self.persistent:
                # 持久化沙箱：仅断开连接，保持运行
                logger.info(
                    f"OpenSandboxProvider: 断开连接，保持沙箱 {self._sandbox_id} 运行"
                )
                # 可以在这里调用API更新沙箱TTL
            else:
                # 非持久化沙箱：删除
                logger.info(f"OpenSandboxProvider: 删除沙箱 {self._sandbox_id}")
                await self._sdk.kill()
            self._sdk = None
            self._is_initialized = False

    async def kill(self) -> None:
        """强制删除沙箱"""
        if self._sdk:
            logger.info(f"OpenSandboxProvider: 强制删除沙箱 {self._sandbox_id}")
            await self._sdk.kill()
            self._sdk = None
            self._is_initialized = False

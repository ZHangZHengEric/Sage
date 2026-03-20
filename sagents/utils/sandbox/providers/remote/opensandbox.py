"""
OpenSandbox 远程沙箱实现
"""

import logging
import os
from datetime import timedelta
from typing import Dict, List, Optional

from .base import RemoteSandboxProvider
from ...interface import CommandResult, ExecutionResult, FileInfo
from ...config import MountPath

logger = logging.getLogger(__name__)


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
        persistent: bool = True,
        sandbox_ttl: int = 3600,
    ):
        super().__init__(sandbox_id, workspace_mount, mount_paths, timeout)
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

        async with self._sdk:
            execution = await self._sdk.commands.run(
                command, timeout=timeout, env=env_vars or {}
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
        # OpenSandbox 可能不直接支持 list_directory
        # 这里通过命令实现
        result = await self.execute_command(f"ls -la {path}")
        # 解析 ls 输出... (简化实现)
        return []

    async def ensure_directory(self, path: str) -> None:
        """确保目录存在"""
        await self.execute_command(f"mkdir -p {path}")

    async def delete_file(self, path: str) -> None:
        """删除文件"""
        await self.execute_command(f"rm -rf {path}")

    async def upload_file(self, host_path: str, sandbox_path: str) -> None:
        """上传文件到远程沙箱"""
        if not self._is_initialized:
            await self.initialize()

        try:
            from opensandbox.models import WriteEntry
        except ImportError:
            raise ImportError("opensandbox package is required")

        with open(host_path, "rb") as f:
            content = f.read()

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

        # 确保目录存在
        os.makedirs(os.path.dirname(host_path), exist_ok=True)

        with open(host_path, "wb") as f:
            f.write(content)

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

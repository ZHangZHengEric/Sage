"""
Bubblewrap isolation strategy (Linux).

使用 Linux 的 bubblewrap 进行文件系统隔离。
"""

import asyncio
import os
import shutil
import uuid
from typing import Dict, Any, Optional, List, Mapping
from sagents.utils.logger import logger
from sagents.utils.sandbox.config import VolumeMount
from sagents.utils.sandbox.environment import build_agent_environment
from sagents.utils.sandbox._stdout_echo import run_with_streaming_stdout
from sagents.utils.common_utils import resolve_sandbox_runtime_dir
from .subprocess import (
    _load_pickle_output_sync,
    _prepare_payload_files_sync,
    _remove_file_if_exists_sync,
)

_TRUSTED_BWRAP_EXECUTABLE = (
    shutil.which("bwrap", path=os.defpath) or "/usr/bin/bwrap"
)


class BwrapIsolation:
    """Linux bubblewrap 隔离模式"""

    def __init__(
        self,
        venv_dir: str,
        sandbox_agent_workspace: str,
        sandbox_runtime_dir: Optional[str] = None,
        volume_mounts: Optional[List[VolumeMount]] = None,
        limits: Optional[Dict[str, Any]] = None,
        cleanup_output_payload: bool = False,
    ):
        self.venv_dir = venv_dir
        self.sandbox_agent_workspace = sandbox_agent_workspace
        self.sandbox_runtime_dir = (
            sandbox_runtime_dir
            or resolve_sandbox_runtime_dir(sandbox_agent_workspace)
            or os.path.join(sandbox_agent_workspace, ".sandbox")
        )
        self.volume_mounts = volume_mounts or []
        self.limits = limits or {}
        self.cleanup_output_payload = cleanup_output_payload

    def _build_base_command(
        self,
        *,
        cwd: Optional[str] = None,
        env_vars: Optional[Mapping[str, object]] = None,
    ) -> tuple[List[str], Dict[str, str]]:
        actual_cwd = cwd or self.sandbox_agent_workspace
        agent_env = build_agent_environment(env_vars, home_dir=actual_cwd)
        bwrap_cmd = [
            _TRUSTED_BWRAP_EXECUTABLE,
            "--clearenv",
            "--unshare-pid",
            "--die-with-parent",
            "--bind",
            self.sandbox_agent_workspace,
            self.sandbox_agent_workspace,
            "--bind",
            self.sandbox_runtime_dir,
            self.sandbox_runtime_dir,
            "--ro-bind",
            "/usr",
            "/usr",
            "--ro-bind",
            "/bin",
            "/bin",
            "--ro-bind",
            "/lib",
            "/lib",
            "--ro-bind",
            "/lib64",
            "/lib64",
            "--ro-bind",
            "/etc",
            "/etc",
            "--dev",
            "/dev",
            "--proc",
            "/proc",
            "--tmpfs",
            "/tmp",
            "--chdir",
            actual_cwd,
        ]
        for name, value in agent_env.items():
            bwrap_cmd.extend(["--setenv", name, value])
        for mount in self.volume_mounts:
            if mount.mount_path == self.sandbox_agent_workspace:
                continue
            bind_flag = "--ro-bind" if mount.read_only else "--bind"
            bwrap_cmd.extend([bind_flag, mount.host_path, mount.mount_path])
        return bwrap_cmd, agent_env

    def _limit_command(self, command: List[str]) -> List[str]:
        """Apply v1's configured per-process address-space limit before exec.

        Run trusted prlimit BEFORE bwrap with the launcher's sanitized environment.
        Agent variables (including LD_PRELOAD/LD_AUDIT) are only bwrap --setenv
        arguments until the limits are installed. Both the soft and hard limits
        are inherited across fork/exec; shell commands must not
        bypass this by skipping the Python pickle launcher. This is not an
        aggregate cgroup budget for all processes in a sandbox.
        """
        memory = self.limits.get("memory", 4096 * 1024 * 1024)
        if isinstance(memory, bool) or not isinstance(memory, int) or memory <= 0:
            raise ValueError("SAGE_LOCAL_MEMORY_LIMIT_MB must be a positive integer")
        return ["/usr/bin/prlimit", f"--as={memory}:{memory}", "--", *command]

    def build_shell_command(
        self,
        command: str,
        *,
        cwd: Optional[str] = None,
        env_vars: Optional[Mapping[str, object]] = None,
    ) -> List[str]:
        """Build a bwrap command for an agent-controlled background shell."""

        bwrap_cmd, _ = self._build_base_command(cwd=cwd, env_vars=env_vars)
        bwrap_cmd.extend(["/bin/sh", "-c", command])
        return self._limit_command(bwrap_cmd)

    async def execute(self, payload: Dict[str, Any], cwd: Optional[str] = None) -> Any:
        """
        使用 bwrap 执行 payload。
        """
        if payload.get("mode") == "shell" and not payload.get("background", False):
            return await self._execute_shell(payload, cwd=cwd)

        run_id = str(uuid.uuid4())
        sandbox_dir = self.sandbox_runtime_dir
        input_pkl: Optional[str] = None
        output_pkl: Optional[str] = None
        returncode: Optional[int] = None

        timeout_seconds = float(payload.get("timeout_seconds", 300))
        try:
            input_pkl, output_pkl, launcher_path = await asyncio.to_thread(
                _prepare_payload_files_sync,
                sandbox_dir,
                run_id,
                payload,
            )

            python_bin = os.path.join(self.venv_dir, "bin", "python")
            bwrap_cmd, agent_env = self._build_base_command(
                cwd=cwd,
                env_vars=payload.get("env_vars"),
            )
            bwrap_cmd.extend([python_bin, launcher_path, input_pkl, output_pkl])
            bwrap_cmd = self._limit_command(bwrap_cmd)

            # 流式执行：launcher 内部跑命令时，stdout 实时转发到本进程 stdout
            # （受 SAGE_ECHO_SHELL_OUTPUT 控制），stderr 完整捕获用于报错
            returncode, stdout_text, stderr_text = await asyncio.to_thread(
                run_with_streaming_stdout,
                bwrap_cmd,
                cwd=cwd or self.sandbox_agent_workspace,
                env=build_agent_environment(
                    home_dir=cwd or self.sandbox_agent_workspace
                ),
                timeout=timeout_seconds,
            )

            if returncode != 0:
                raise Exception(f"Bwrap execution failed: {stderr_text}")

            res = await asyncio.to_thread(_load_pickle_output_sync, output_pkl)

            if res["status"] == "success":
                logger.info(
                    "[BwrapIsolation] 执行完成: "
                    f"command={payload.get('command')!r}, return_code={returncode}"
                )
                return res["result"]
            else:
                raise Exception(f"Error in bwrap: {res.get('error')}")

        except Exception as exc:
            rendered_returncode = (
                str(returncode) if returncode is not None else "unknown"
            )
            logger.error(
                "[BwrapIsolation] 执行失败: "
                f"command={payload.get('command')!r}, "
                f"return_code={rendered_returncode}, error={exc}"
            )
            raise

        finally:
            if input_pkl is not None:
                try:
                    await asyncio.to_thread(_remove_file_if_exists_sync, input_pkl)
                except Exception:
                    pass
            if self.cleanup_output_payload and output_pkl is not None:
                try:
                    await asyncio.to_thread(_remove_file_if_exists_sync, output_pkl)
                except Exception:
                    pass

    async def _execute_shell(
        self, payload: Dict[str, Any], cwd: Optional[str] = None
    ) -> Dict[str, Any]:
        """Execute a shell command directly inside bubblewrap."""
        actual_cwd = cwd or self.sandbox_agent_workspace
        command = self.build_shell_command(
            str(payload.get("command", "")),
            cwd=actual_cwd,
            env_vars=payload.get("env_vars"),
        )
        timeout_seconds = float(payload.get("timeout_seconds", 300))
        returncode, stdout_text, stderr_text = await asyncio.to_thread(
            run_with_streaming_stdout,
            command,
            cwd=actual_cwd,
            env=build_agent_environment(home_dir=actual_cwd),
            timeout=timeout_seconds,
        )
        if returncode != 0 and stderr_text.lstrip().startswith("bwrap:"):
            error = RuntimeError(f"Bwrap execution failed: {stderr_text}")
            logger.error(
                "[BwrapIsolation] 执行失败: "
                f"command={payload.get('command')!r}, "
                f"return_code={returncode}, error={error}"
            )
            raise error
        logger.info(
            "[BwrapIsolation] 执行完成: "
            f"command={payload.get('command')!r}, return_code={returncode}"
        )
        return {
            "success": returncode == 0,
            "output": stdout_text,
            "stderr": stderr_text,
            "return_code": returncode,
        }

    def execute_background(
        self, command: str, cwd: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        后台执行命令。
        """
        logger.warning(
            "[BwrapIsolation.execute_background] bwrap 模式下不建议使用后台任务"
        )

        # 使用 subprocess 模式执行
        from .subprocess import SubprocessIsolation

        subproc = SubprocessIsolation(
            venv_dir=self.venv_dir,
            sandbox_agent_workspace=self.sandbox_agent_workspace,
            sandbox_runtime_dir=self.sandbox_runtime_dir,
            volume_mounts=self.volume_mounts,
            limits=self.limits,
        )
        return subproc.execute_background(command, cwd)  # pyright: ignore[reportReturnType]

"""
Bubblewrap isolation strategy (Linux).

使用 Linux 的 bubblewrap 进行文件系统隔离。
"""
import asyncio
import subprocess
import os
import uuid
from typing import Dict, Any, Optional, List
from sagents.utils.logger import logger
from sagents.utils.sandbox.config import VolumeMount
from sagents.utils.sandbox._stdout_echo import run_with_streaming_stdout
from sagents.utils.common_utils import resolve_sandbox_runtime_dir
from .subprocess import (
    _load_pickle_output_sync,
    _prepare_payload_files_sync,
    _remove_file_if_exists_sync,
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
    ):
        self.venv_dir = venv_dir
        self.sandbox_agent_workspace = sandbox_agent_workspace
        self.sandbox_runtime_dir = sandbox_runtime_dir or resolve_sandbox_runtime_dir(sandbox_agent_workspace) or os.path.join(sandbox_agent_workspace, ".sandbox")
        self.volume_mounts = volume_mounts or []
        self.limits = limits or {}
        
    async def execute(self, payload: Dict[str, Any], cwd: Optional[str] = None) -> Any:
        """
        使用 bwrap 执行 payload。
        """
        logger.info(f"[BwrapIsolation] 开始执行")
        
        run_id = str(uuid.uuid4())
        sandbox_dir = self.sandbox_runtime_dir
        input_pkl, output_pkl, launcher_path = await asyncio.to_thread(
            _prepare_payload_files_sync,
            sandbox_dir,
            run_id,
            payload,
        )

        python_bin = os.path.join(self.venv_dir, "bin", "python")

        bwrap_cmd = [
            "bwrap",
            "--ro-bind", self.sandbox_agent_workspace, self.sandbox_agent_workspace,
            "--bind", sandbox_dir, sandbox_dir,
            "--ro-bind", "/usr", "/usr",
            "--ro-bind", "/bin", "/bin",
            "--ro-bind", "/lib", "/lib",
            "--ro-bind", "/lib64", "/lib64",
            "--ro-bind", "/etc", "/etc",
            "--dev", "/dev",
            "--proc", "/proc",
            "--tmpfs", "/tmp",
        ]
        
        for mount in self.volume_mounts:
            if mount.mount_path != self.sandbox_agent_workspace:
                bwrap_cmd.extend(["--ro-bind", mount.host_path, mount.mount_path])
        
        bwrap_cmd.extend([python_bin, launcher_path, input_pkl, output_pkl])
        
        logger.info(f"[BwrapIsolation] 执行命令: {' '.join(bwrap_cmd[:5])}...")
        
        try:
            # 流式执行：launcher 内部跑命令时，stdout 实时转发到本进程 stdout
            # （受 SAGE_ECHO_SHELL_OUTPUT 控制），stderr 完整捕获用于报错
            returncode, stdout_text, stderr_text = await asyncio.to_thread(
                run_with_streaming_stdout,
                bwrap_cmd,
                cwd=cwd or self.sandbox_agent_workspace,
                timeout=300,
            )

            logger.info(f"[BwrapIsolation] 返回码: {returncode}")

            if returncode != 0:
                logger.error(f"[BwrapIsolation] 执行失败: {stderr_text[:500]}")
                raise Exception(f"Bwrap execution failed: {stderr_text}")
            
            res = await asyncio.to_thread(_load_pickle_output_sync, output_pkl)
            
            if res['status'] == 'success':
                return res['result']
            else:
                raise Exception(f"Error in bwrap: {res.get('error')}")
                
        finally:
            try:
                await asyncio.to_thread(_remove_file_if_exists_sync, input_pkl)
            except Exception:
                pass
                    
    def execute_background(self, command: str, cwd: Optional[str] = None) -> Dict[str, Any]:
        """
        后台执行命令。
        """
        logger.warning(f"[BwrapIsolation.execute_background] bwrap 模式下不建议使用后台任务")
        
        # 使用 subprocess 模式执行
        from .subprocess import SubprocessIsolation
        subproc = SubprocessIsolation(
            venv_dir=self.venv_dir,
            sandbox_agent_workspace=self.sandbox_agent_workspace,
            sandbox_runtime_dir=self.sandbox_runtime_dir,
            volume_mounts=self.volume_mounts,
            limits=self.limits,
        )
        return subproc.execute_background(command, cwd)

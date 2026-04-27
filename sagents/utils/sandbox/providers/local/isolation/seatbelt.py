"""
Seatbelt isolation strategy (macOS sandbox-exec).

使用 macOS 的 sandbox-exec 进行文件系统隔离。
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


class SeatbeltIsolation:
    """macOS sandbox-exec 隔离模式"""
    
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
        self.volume_mounts = volume_mounts or []
        self.limits = limits or {}
        self.sandbox_dir = sandbox_runtime_dir or resolve_sandbox_runtime_dir(sandbox_agent_workspace) or os.path.join(sandbox_agent_workspace, ".sandbox")
        os.makedirs(self.sandbox_dir, exist_ok=True)
        
    def _generate_profile(self, output_pkl: str, additional_read_paths: list = None,
                         additional_write_paths: list = None) -> str:
        """生成 seatbelt 配置文件"""
        import tempfile

        # 构建允许的路径
        allowed = [self.sandbox_agent_workspace, self.sandbox_dir, self.venv_dir]
        
        # 添加 volume_mounts 中的路径
        for mount in self.volume_mounts:
            allowed.append(mount.host_path)

        if additional_read_paths:
            allowed.extend(additional_read_paths)
        if additional_write_paths:
            allowed.extend(additional_write_paths)
        
        # 添加系统关键路径（用于 Rosetta 和动态库加载）
        system_paths = [
            "/usr/lib",
            "/usr/local/lib",
            "/System/Library",
            "/Library/Apple/usr/lib",
            "/Library/Apple/usr/share",
            "/var/db/dyld",  # dyld 共享缓存
            "/private/var/db/dyld",
        ]
        allowed.extend(system_paths)
        
        # 添加 conda 环境路径（如果 Python 在 conda 中）
        conda_base = os.environ.get("CONDA_PREFIX") or os.environ.get("CONDA_ROOT")
        if conda_base:
            allowed.append(conda_base)
            allowed.append(os.path.dirname(conda_base))  # envs 目录
        
        # 去重
        allowed = list(set(allowed))
        
        # 构建 sandbox profile
        # 策略：
        #   - 系统调用 / IPC / 进程 / mach / sysctl / iokit 全部放行（否则
        #     Python 启动会 SIGABRT 或卡死在系统服务上，而我们关心的不是限制系统调用）
        #   - 文件读取默认放开（沙箱目的不是机密读保护，而是防止误写/越权写）
        #   - 文件写入默认 deny，仅放行 workspace / sandbox_dir / volume_mounts /
        #     系统临时目录 / /dev 等必要位置
        lines = [
            "(version 1)",
            "(deny default)",
            "(allow process*)",
            "(allow signal)",
            "(allow mach*)",
            "(allow iokit*)",
            "(allow sysctl*)",
            "(allow ipc*)",
            "(allow system-socket)",
            "(allow network*)",
            # 文件读全放开（保留 file-write 的细粒度限制即可）
            "(allow file-read*)",
            # /dev 下必备的写
            '(allow file-write* '
            '(literal "/dev/null") (literal "/dev/zero") '
            '(literal "/dev/dtracehelper") (literal "/dev/tty") '
            '(literal "/dev/stdout") (literal "/dev/stderr"))',
            # 系统临时目录写权限（tempfile、Python 缓存等）
            '(allow file-write* (subpath "/private/tmp"))',
            '(allow file-write* (subpath "/private/var/folders"))',
        ]

        # 用户允许写入的路径（workspace、sandbox_dir、volume_mounts 等）
        for path in allowed:
            if not path:
                continue
            if os.path.isdir(path):
                lines.append(f"(allow file-write* (subpath \"{path}\"))")
            elif os.path.isfile(path):
                lines.append(f"(allow file-write* (literal \"{path}\"))")
        
        profile_content = "\n".join(lines)
        
        # 写入临时文件
        profile_fd, profile_path = tempfile.mkstemp(suffix=".sb")
        with os.fdopen(profile_fd, "w") as f:
            f.write(profile_content)
            
        return profile_path
        
    async def execute(self, payload: Dict[str, Any], cwd: Optional[str] = None) -> Any:
        """
        使用 sandbox-exec 执行 payload。
        """
        logger.info(f"[SeatbeltIsolation] 开始执行")
        
        run_id = str(uuid.uuid4())
        input_pkl, output_pkl, launcher_path = await asyncio.to_thread(
            _prepare_payload_files_sync,
            self.sandbox_dir,
            run_id,
            payload,
        )
        
        # 使用沙箱的 venv Python（解析符号链接获取真实路径）
        python_bin = os.path.join(self.venv_dir, "bin", "python")
        python_bin_dir = None
        if os.path.islink(python_bin):
            python_bin = os.path.realpath(python_bin)
            python_bin_dir = os.path.dirname(python_bin)
            logger.info(f"[SeatbeltIsolation] Python 是符号链接，已解析为真实路径: {python_bin}")
        additional_write = [cwd] if cwd else []
        additional_read = [input_pkl]
        if python_bin_dir:
            additional_read.append(python_bin_dir)
        profile_path = await asyncio.to_thread(
            self._generate_profile,
            output_pkl,
            additional_read_paths=additional_read,
            additional_write_paths=additional_write,
        )
        
        cmd = [
            "sandbox-exec", "-f", profile_path,
            python_bin, launcher_path,
            input_pkl, output_pkl
        ]
        
        logger.info(f"[SeatbeltIsolation] 执行命令: {' '.join(cmd[:4])}...")
        
        try:
            try:
                # 用流式 helper：launcher 内部跑命令时实时把 stdout 转发到本进程
                # stdout（受 SAGE_ECHO_SHELL_OUTPUT 控制），stderr 完整捕获用于报错
                returncode, stdout_text, stderr_text = await asyncio.to_thread(
                    run_with_streaming_stdout,
                    cmd,
                    cwd=cwd or self.sandbox_dir,
                    timeout=300,
                )
            except subprocess.TimeoutExpired as te:
                # 超时通常意味着 sandbox profile 缺权限导致 Python 启动卡死
                logger.error(
                    f"[SeatbeltIsolation] 执行超时(300s)，profile 保留以便排查: {profile_path}\n"
                    f"stderr(部分): {(te.stderr or '')[:500]!r}"
                )
                # 保留 profile 不删，便于人工 cat 查看
                profile_path = None
                raise

            logger.info(f"[SeatbeltIsolation] 返回码: {returncode}")

            if returncode != 0:
                logger.error(
                    f"[SeatbeltIsolation] 执行失败 rc={returncode}\n"
                    f"stderr: {stderr_text[:1000]}\n"
                    f"stdout: {stdout_text[:500]}"
                )
                raise Exception(f"Seatbelt execution failed: {stderr_text}")
            
            res = await asyncio.to_thread(_load_pickle_output_sync, output_pkl)
            
            if res['status'] == 'success':
                return res['result']
            else:
                raise Exception(f"Error in seatbelt: {res.get('error')}")
                
        finally:
            try:
                await asyncio.to_thread(_remove_file_if_exists_sync, input_pkl)
            except Exception:
                pass
            try:
                await asyncio.to_thread(_remove_file_if_exists_sync, profile_path)
            except Exception:
                pass
                    
    def execute_background(self, command: str, cwd: Optional[str] = None) -> Dict[str, Any]:
        """
        后台执行命令。
        注意：seatbelt 模式下后台任务会受限。
        """
        logger.warning(f"[SeatbeltIsolation.execute_background] seatbelt 模式下不建议使用后台任务")
        
        # 使用 subprocess 模式执行
        from .subprocess import SubprocessIsolation
        subproc = SubprocessIsolation(
            venv_dir=self.venv_dir,
            sandbox_agent_workspace=self.sandbox_agent_workspace,
            sandbox_runtime_dir=self.sandbox_dir,
            volume_mounts=self.volume_mounts,
            limits=self.limits,
        )
        return subproc.execute_background(command, cwd)

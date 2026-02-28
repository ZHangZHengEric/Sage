"""
Seatbelt isolation strategy (macOS sandbox-exec).

使用 macOS 的 sandbox-exec 进行文件系统隔离。
"""
import subprocess
import os
from typing import Dict, Any, Optional
from sagents.utils.logger import logger


class SeatbeltIsolation:
    """macOS sandbox-exec 隔离模式"""
    
    def __init__(self, venv_dir: str, host_workspace: str, limits: Dict[str, Any], 
                 allowed_paths: list, sandbox_dir: str):
        self.venv_dir = venv_dir
        self.host_workspace = host_workspace
        self.limits = limits
        self.allowed_paths = allowed_paths
        self.sandbox_dir = sandbox_dir
        
    def _generate_profile(self, output_pkl: str, additional_read_paths: list = None, 
                         additional_write_paths: list = None) -> str:
        """生成 seatbelt 配置文件"""
        import tempfile
        
        # 构建允许的路径
        allowed = list(self.allowed_paths)
        allowed.append(self.host_workspace)
        allowed.append(self.sandbox_dir)
        
        if additional_read_paths:
            allowed.extend(additional_read_paths)
        if additional_write_paths:
            allowed.extend(additional_write_paths)
        
        # 去重
        allowed = list(set(allowed))
        
        # 构建 sandbox profile
        lines = [
            "(version 1)",
            "(deny default)",
            "(allow process-fork)",
            "(allow process-exec)",
        ]
        
        # 添加路径权限
        for path in allowed:
            if os.path.isdir(path):
                lines.append(f"(allow file* (literal \"{path}\"))")
                lines.append(f"(allow file* (subpath \"{path}\"))")
            elif os.path.isfile(path):
                lines.append(f"(allow file* (literal \"{path}\"))")
        
        # 允许网络
        lines.append("(allow network*)")
        
        profile_content = "\n".join(lines)
        
        # 写入临时文件
        profile_fd, profile_path = tempfile.mkstemp(suffix=".sb")
        with os.fdopen(profile_fd, "w") as f:
            f.write(profile_content)
            
        return profile_path
        
    def execute(self, payload: Dict[str, Any], cwd: Optional[str] = None) -> Any:
        """
        使用 sandbox-exec 执行 payload。
        """
        import pickle
        import uuid
        
        logger.info(f"[SeatbeltIsolation] 开始执行")
        
        run_id = str(uuid.uuid4())
        input_pkl = os.path.join(self.sandbox_dir, f"input_{run_id}.pkl")
        output_pkl = os.path.join(self.sandbox_dir, f"output_{run_id}.pkl")
        
        with open(input_pkl, "wb") as f:
            pickle.dump(payload, f)
        
        # 生成 profile
        additional_write = [cwd] if cwd else []
        profile_path = self._generate_profile(output_pkl, 
                                             additional_read_paths=[input_pkl],
                                             additional_write_paths=additional_write)
        
        # 使用沙箱的 venv Python
        python_bin = os.path.join(self.venv_dir, "bin", "python")
        launcher_path = os.path.join(self.sandbox_dir, "launcher.py")
        
        cmd = [
            "sandbox-exec", "-f", profile_path,
            python_bin, launcher_path,
            input_pkl, output_pkl
        ]
        
        logger.info(f"[SeatbeltIsolation] 执行命令: {' '.join(cmd[:4])}...")
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=cwd or self.sandbox_dir
            )
            
            logger.info(f"[SeatbeltIsolation] 返回码: {result.returncode}")
            
            if result.returncode != 0:
                logger.error(f"[SeatbeltIsolation] 执行失败: {result.stderr[:500]}")
                raise Exception(f"Seatbelt execution failed: {result.stderr}")
            
            if not os.path.exists(output_pkl):
                raise Exception("No output file generated")
            
            with open(output_pkl, "rb") as f:
                res = pickle.load(f)
            
            if res['status'] == 'success':
                return res['result']
            else:
                raise Exception(f"Error in seatbelt: {res.get('error')}")
                
        finally:
            # 清理
            if os.path.exists(input_pkl):
                try:
                    os.remove(input_pkl)
                except:
                    pass
            if os.path.exists(profile_path):
                try:
                    os.remove(profile_path)
                except:
                    pass
                    
    def execute_background(self, command: str, cwd: Optional[str] = None) -> Dict[str, Any]:
        """
        后台执行命令。
        注意：seatbelt 模式下后台任务会受限。
        """
        logger.warning(f"[SeatbeltIsolation.execute_background] seatbelt 模式下不建议使用后台任务")
        
        # 使用 subprocess 模式执行
        from .subprocess import SubprocessIsolation
        subproc = SubprocessIsolation(self.venv_dir, self.host_workspace, self.limits)
        return subproc.execute_background(command, cwd)

"""
Bubblewrap isolation strategy (Linux).

使用 Linux 的 bubblewrap 进行文件系统隔离。
"""
import subprocess
import os
from typing import Dict, Any, Optional
from sagents.utils.logger import logger


class BwrapIsolation:
    """Linux bubblewrap 隔离模式"""
    
    def __init__(self, venv_dir: str, host_workspace: str, limits: Dict[str, Any], 
                 virtual_workspace: str = "/workspace"):
        self.venv_dir = venv_dir
        self.host_workspace = host_workspace
        self.limits = limits
        self.virtual_workspace = virtual_workspace
        
    def execute(self, payload: Dict[str, Any], cwd: Optional[str] = None) -> Any:
        """
        使用 bwrap 执行 payload。
        """
        import pickle
        import uuid
        
        logger.info(f"[BwrapIsolation] 开始执行")
        
        run_id = str(uuid.uuid4())
        sandbox_dir = os.path.join(self.host_workspace, ".sandbox")
        input_pkl = os.path.join(sandbox_dir, f"input_{run_id}.pkl")
        output_pkl = os.path.join(sandbox_dir, f"output_{run_id}.pkl")
        
        with open(input_pkl, "wb") as f:
            pickle.dump(payload, f)
        
        # 使用沙箱的 venv Python
        python_bin = os.path.join(self.venv_dir, "bin", "python")
        launcher_path = os.path.join(sandbox_dir, "launcher.py")
        
        # 构建 bwrap 命令
        bwrap_cmd = [
            "bwrap",
            "--ro-bind", self.host_workspace, self.virtual_workspace,
            "--bind", sandbox_dir, sandbox_dir,
            "--dev", "/dev",
            "--tmpfs", "/tmp",
            python_bin, launcher_path,
            input_pkl, output_pkl
        ]
        
        logger.info(f"[BwrapIsolation] 执行命令: {' '.join(bwrap_cmd[:5])}...")
        
        try:
            result = subprocess.run(
                bwrap_cmd,
                capture_output=True,
                text=True,
                cwd=cwd or self.virtual_workspace,
                timeout=300
            )
            
            logger.info(f"[BwrapIsolation] 返回码: {result.returncode}")
            
            if result.returncode != 0:
                logger.error(f"[BwrapIsolation] 执行失败: {result.stderr[:500]}")
                raise Exception(f"Bwrap execution failed: {result.stderr}")
            
            if not os.path.exists(output_pkl):
                raise Exception("No output file generated")
            
            with open(output_pkl, "rb") as f:
                res = pickle.load(f)
            
            if res['status'] == 'success':
                return res['result']
            else:
                raise Exception(f"Error in bwrap: {res.get('error')}")
                
        finally:
            # 清理
            if os.path.exists(input_pkl):
                try:
                    os.remove(input_pkl)
                except:
                    pass
                    
    def execute_background(self, command: str, cwd: Optional[str] = None) -> Dict[str, Any]:
        """
        后台执行命令。
        """
        logger.warning(f"[BwrapIsolation.execute_background] bwrap 模式下不建议使用后台任务")
        
        # 使用 subprocess 模式执行
        from .subprocess import SubprocessIsolation
        subproc = SubprocessIsolation(self.venv_dir, self.host_workspace, self.limits)
        return subproc.execute_background(command, cwd)

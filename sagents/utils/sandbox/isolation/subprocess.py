"""
Subprocess isolation strategy.

直接使用 subprocess 执行，无文件系统隔离。
Python 依赖通过 venv 隔离。
"""
import subprocess
import os
from typing import Dict, Any, Optional
from sagents.utils.logger import logger


# Launcher 脚本
LAUNCHER_SCRIPT = """#!/usr/bin/env python3
import sys
import os
import pickle
import traceback
import importlib
import importlib.util
import asyncio
import subprocess
import io
import resource
import builtins
import time
from contextlib import redirect_stdout, redirect_stderr

sys.path.insert(0, os.getcwd())

def log_timing(msg):
    try:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        sys.stderr.write(f"[{timestamp}] [LAUNCHER] {msg}\\n")
        sys.stderr.flush()
    except Exception:
        pass

def _apply_limits_internal(limits, restrict_files=True):
    log_timing("Applying limits...")
    if 'cpu_time' in limits:
        target = int(limits['cpu_time'])
        try:
            soft, hard = resource.getrlimit(resource.RLIMIT_CPU)
            if hard != resource.RLIM_INFINITY:
                target = min(target, hard)
            resource.setrlimit(resource.RLIMIT_CPU, (target, hard))
        except Exception:
            pass

    if restrict_files and 'allowed_paths' in limits:
        allowed_paths = limits.get('allowed_paths', [])
        if allowed_paths:
            original_open = open
            def restricted_open(file, mode='r', buffering=-1, encoding=None, errors=None, newline=None, closefd=True, opener=None):
                if isinstance(file, int):
                    return original_open(file, mode, buffering, encoding, errors, newline, closefd, opener)
                try:
                    abs_path = os.path.abspath(file)
                except Exception:
                    raise PermissionError(f"Access to file {file} is denied (Invalid Path).")

                allowed = False
                for path in allowed_paths:
                    if abs_path.startswith(os.path.abspath(path)):
                        allowed = True
                        break
                
                if not allowed:
                    raise PermissionError(f"Access to file {abs_path} is denied (Sandboxed).")
                return original_open(file, mode, buffering, encoding, errors, newline, closefd, opener)
            builtins.open = restricted_open

def main():
    try:
        log_timing("Starting launcher main...")
        if len(sys.argv) < 3:
            raise ValueError("Usage: launcher.py <input_pkl> <output_pkl>")
        
        input_path = sys.argv[1]
        output_path = sys.argv[2]
        
        log_timing(f"Loading payload from {input_path}")
        with open(input_path, 'rb') as f:
            payload = pickle.load(f)
            
        mode = payload['mode']
        args = payload.get('args', [])
        kwargs = payload.get('kwargs', {})
        sys_path = payload.get('sys_path', [])
        limits = payload.get('limits', {})
        apply_file_restrictions = payload.get('apply_file_restrictions', False)

        if limits:
            _apply_limits_internal(limits, restrict_files=apply_file_restrictions)
        
        log_timing("Restoring sys.path...")
        for p in reversed(sys_path):
            if p not in sys.path:
                sys.path.insert(0, p)
        
        result = None
        log_timing(f"Executing mode: {mode}")
        
        if mode == 'library':
            module_name = payload['module_name']
            class_name = payload.get('class_name')
            function_name = payload['function_name']
            
            log_timing(f"Importing module: {module_name}")
            module = importlib.import_module(module_name)
            if class_name:
                log_timing(f"Getting class: {class_name}")
                cls = getattr(module, class_name)
                instance = cls()
                func = getattr(instance, function_name)
            else:
                func = getattr(module, function_name)
                
            log_timing(f"Running function: {function_name}")
            if asyncio.iscoroutinefunction(func):
                result = asyncio.run(func(*args, **kwargs))
            else:
                result = func(*args, **kwargs)
            log_timing("Function execution completed")
                
        elif mode == 'func':
            # 直接执行函数对象
            func = payload.get('func')
            args = payload.get('args', ())
            kwargs = payload.get('kwargs', {})
            
            log_timing("Running function directly")
            if asyncio.iscoroutinefunction(func):
                result = asyncio.run(func(*args, **kwargs))
            else:
                result = func(*args, **kwargs)
            log_timing("Function execution completed")
                
        elif mode == 'module':
            module_path = payload['module_path']
            func_name = payload['func_name']
            
            spec = importlib.util.spec_from_file_location("sandboxed_module", module_path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                func = getattr(module, func_name)
                result = func(*args, **kwargs)
            else:
                raise ImportError(f"Could not load module from {module_path}")

        elif mode == 'script':
            script_path = payload['script_path']
            
            script_dir = os.path.dirname(os.path.abspath(script_path))
            if script_dir not in sys.path:
                sys.path.insert(0, script_dir)
                
            with open(script_path, 'r', encoding='utf-8') as f:
                script_content = f.read()
                
            global_ns = {'__name__': '__main__', '__file__': script_path}
            
            stdout = io.StringIO()
            stderr = io.StringIO()
            
            try:
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    exec(script_content, global_ns)
            except Exception:
                traceback.print_exc(file=stderr)
                raise
                
            result = stdout.getvalue() + stderr.getvalue()

        elif mode == 'shell':
            cmd = payload['command']
            cwd = payload.get('cwd')
            background = payload.get('background', False)
            
            if background:
                # 后台执行
                log_dir = os.path.join(cwd, ".sandbox_logs")
                os.makedirs(log_dir, exist_ok=True)
                log_file = os.path.join(log_dir, f"bg_{os.getpid()}.log")
                
                nohup_cmd = f"nohup {cmd} > {log_file} 2>&1 &"
                proc = subprocess.Popen(
                    nohup_cmd,
                    shell=True,
                    cwd=cwd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
                result = {
                    "success": True,
                    "output": f"[后台任务已启动]\n命令: {cmd}\n进程ID: {proc.pid}\n日志文件: {log_file}",
                    "process_id": f"bg_{proc.pid}",
                    "is_background": True,
                    "log_file": log_file,
                }
            else:
                proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
                if proc.returncode != 0:
                     raise Exception(f"Command failed with code {proc.returncode}: {proc.stderr}")
                result = proc.stdout
        else:
            raise ValueError(f"Unknown mode: {mode}")

        with open(output_path, 'wb') as f:
            pickle.dump({'status': 'success', 'result': result}, f)
            
    except Exception as e:
        try:
            with open(output_path, 'wb') as f:
                pickle.dump({'status': 'error', 'error': str(e), 'traceback': traceback.format_exc()}, f)
        except Exception:
            traceback.print_exc()
            sys.exit(1)

if __name__ == "__main__":
    main()
"""


class SubprocessIsolation:
    """直接执行模式，无文件系统隔离"""
    
    def __init__(self, venv_dir: str, host_workspace: str, limits: Dict[str, Any]):
        self.venv_dir = venv_dir
        self.host_workspace = host_workspace
        self.limits = limits
        
    def execute(self, payload: Dict[str, Any], cwd: Optional[str] = None) -> Any:
        """
        执行 payload。
        
        Args:
            payload: 执行内容，包含 mode, module_path, func_name 等
            cwd: 工作目录
            
        Returns:
            执行结果
        """
        import pickle
        import uuid
        
        logger.info(f"[SubprocessIsolation] 开始执行")
        logger.info(f"  venv_dir: {self.venv_dir}")
        logger.info(f"  cwd: {cwd}")
        
        # 创建临时文件
        run_id = str(uuid.uuid4())
        sandbox_dir = os.path.join(self.host_workspace, ".sandbox")
        input_pkl = os.path.join(sandbox_dir, f"input_{run_id}.pkl")
        output_pkl = os.path.join(sandbox_dir, f"output_{run_id}.pkl")
        
        with open(input_pkl, "wb") as f:
            pickle.dump(payload, f)
        
        # 使用沙箱的 venv Python
        python_bin = os.path.join(self.venv_dir, "bin", "python")
        # 创建 launcher.py 如果不存在
        launcher_path = os.path.join(sandbox_dir, "launcher.py")
        if not os.path.exists(launcher_path):
            with open(launcher_path, "w") as f:
                f.write(LAUNCHER_SCRIPT)
        
        cmd = [python_bin, launcher_path, input_pkl, output_pkl]
        
        # 构建环境变量
        env = os.environ.copy()
        
        # 设置 PATH，优先使用 venv
        venv_bin = os.path.join(self.venv_dir, "bin")
        current_path = env.get("PATH", "")
        env["PATH"] = f"{venv_bin}:{current_path}"
        
        # 设置 PYTHONPATH
        pylibs_dir = os.path.join(self.host_workspace, ".sandbox", ".pylibs")
        env["PIP_TARGET"] = pylibs_dir
        current_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{pylibs_dir}:{self.host_workspace}:{current_pythonpath}"
        
        # 保留原来的 HOME 目录
        env["HOME"] = os.environ.get("HOME", "")
        
        logger.info(f"[SubprocessIsolation] 执行命令: {' '.join(cmd[:3])}...")
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=cwd or self.host_workspace,
                env=env,
                timeout=300  # 5分钟超时
            )
            
            logger.info(f"[SubprocessIsolation] 返回码: {result.returncode}")
            
            if result.returncode != 0:
                logger.error(f"[SubprocessIsolation] 执行失败: {result.stderr[:500]}")
                raise Exception(f"Subprocess execution failed: {result.stderr}")
            
            if not os.path.exists(output_pkl):
                raise Exception("No output file generated")
            
            with open(output_pkl, "rb") as f:
                res = pickle.load(f)
            
            if res['status'] == 'success':
                logger.info(f"[SubprocessIsolation] 执行成功")
                return res['result']
            else:
                logger.error(f"[SubprocessIsolation] 执行错误: {res.get('error')}")
                raise Exception(f"Error in subprocess: {res.get('error')}")
                
        finally:
            # 清理临时文件
            if os.path.exists(input_pkl):
                try:
                    os.remove(input_pkl)
                except:
                    pass
                    
    def execute_background(self, command: str, cwd: Optional[str] = None) -> Dict[str, Any]:
        """
        后台执行命令。
        
        Args:
            command: 要执行的命令
            cwd: 工作目录
            
        Returns:
            包含进程信息的字典
        """
        import uuid
        
        logger.info(f"[SubprocessIsolation.execute_background] 开始后台执行")
        logger.info(f"  command: {command}")
        logger.info(f"  cwd: {cwd}")
        
        actual_cwd = cwd or self.host_workspace
        
        # 构建环境变量
        env = os.environ.copy()
        
        # 保留原来的 HOME 目录
        original_home = os.environ.get("HOME", "")
        
        # 使用 nohup 包装命令
        nohup_command = f"nohup env HOME=\"{original_home}\" {command} > /dev/null 2>&1 &"
        
        logger.info(f"[SubprocessIsolation.execute_background] nohup 命令: {nohup_command[:100]}...")
        
        # 执行
        process = subprocess.Popen(
            nohup_command,
            cwd=actual_cwd,
            shell=True,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        
        logger.info(f"[SubprocessIsolation.execute_background] 进程已启动, PID: {process.pid}")
        
        return {
            "success": True,
            "process_id": f"bg_{process.pid}",
            "pid": process.pid
        }

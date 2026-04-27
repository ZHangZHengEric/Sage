"""
Subprocess isolation strategy.

直接使用 subprocess 执行，无文件系统隔离。
Python 依赖通过 venv 隔离。
"""
import subprocess
import os
import sys
import platform
import asyncio
import pickle
import uuid
from typing import Dict, Any, Optional, List
from sagents.utils.logger import logger
from sagents.utils.sandbox.config import VolumeMount
from sagents.utils.common_utils import resolve_sandbox_runtime_dir


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
import builtins
import time
from contextlib import redirect_stdout, redirect_stderr

# Windows compatibility: resource module is not available
try:
    import resource
except ImportError:
    resource = None

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
    if resource:
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
                # Normalize paths for comparison (handles case sensitivity on Windows)
                abs_path_norm = os.path.normcase(abs_path)
                
                for path in allowed_paths:
                    path_norm = os.path.normcase(os.path.abspath(path))
                    # Ensure directory paths end with separator to avoid partial matches
                    # e.g. /tmp/foo should not match /tmp/foobar
                    if os.path.isdir(path):
                         if not path_norm.endswith(os.sep):
                             path_norm += os.sep
                         if not abs_path_norm.endswith(os.sep) and os.path.isdir(abs_path):
                             abs_path_norm += os.sep
                    
                    if abs_path_norm.startswith(path_norm):
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
                    "output": f"[后台任务已启动]\\n命令: {cmd}\\n进程ID: {proc.pid}\\n日志文件: {log_file}",
                    "process_id": f"bg_{proc.pid}",
                    "is_background": True,
                    "log_file": log_file,
                }
            else:
                # 流式执行：边跑边把命令 stdout 写到本进程 stdout（外层 sandbox parent
                # 已经在用 PIPE 增量读，再转发到 host 的 sys.stdout 实现实时回显）。
                # stderr 单独捕获用于报错；同时把 stdout 缓存到 result 里返回 pickle。
                proc = subprocess.Popen(
                    cmd,
                    shell=True,
                    cwd=cwd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=0,
                )
                stdout_chunks = []
                stderr_chunks = []
                import threading as _t
                def _drain_o():
                    try:
                        while True:
                            b = proc.stdout.read(4096) if proc.stdout else b''
                            if not b:
                                break
                            t = b.decode('utf-8', errors='replace')
                            stdout_chunks.append(t)
                            try:
                                sys.stdout.write(t)
                                sys.stdout.flush()
                            except Exception:
                                pass
                    except Exception:
                        pass
                def _drain_e():
                    try:
                        while True:
                            b = proc.stderr.read(4096) if proc.stderr else b''
                            if not b:
                                break
                            stderr_chunks.append(b.decode('utf-8', errors='replace'))
                    except Exception:
                        pass
                _to = _t.Thread(target=_drain_o, daemon=True)
                _te = _t.Thread(target=_drain_e, daemon=True)
                _to.start(); _te.start()
                proc.wait()
                _to.join(timeout=1.0); _te.join(timeout=1.0)
                stdout_text = ''.join(stdout_chunks)
                stderr_text = ''.join(stderr_chunks)
                if proc.returncode != 0:
                    raise Exception(f"Command failed with code {proc.returncode}: {stderr_text}")
                result = stdout_text
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


def _prepare_payload_files_sync(
    sandbox_dir: str,
    run_id: str,
    payload: Dict[str, Any],
    launcher_script: str = LAUNCHER_SCRIPT,
) -> tuple[str, str, str]:
    os.makedirs(sandbox_dir, exist_ok=True)
    input_pkl = os.path.join(sandbox_dir, f"input_{run_id}.pkl")
    output_pkl = os.path.join(sandbox_dir, f"output_{run_id}.pkl")

    with open(input_pkl, "wb") as f:
        pickle.dump(payload, f)

    launcher_path = os.path.join(sandbox_dir, "launcher.py")
    with open(launcher_path, "w") as f:
        f.write(launcher_script)

    return input_pkl, output_pkl, launcher_path


def _load_pickle_output_sync(output_pkl: str) -> Any:
    if not os.path.exists(output_pkl):
        raise Exception("No output file generated")

    with open(output_pkl, "rb") as f:
        return pickle.load(f)


def _remove_file_if_exists_sync(path: Optional[str]) -> None:
    if path and os.path.exists(path):
        os.remove(path)


def _spawn_background_process_sync(
    command: str,
    actual_cwd: str,
    env: Dict[str, str],
    original_home: str,
) -> Dict[str, Any]:
    if platform.system() == "Windows":
        log_dir = os.path.join(actual_cwd, ".sandbox_logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f"bg_{uuid.uuid4()}.log")

        with open(log_file, "w") as f_log:
            process = subprocess.Popen(
                command,
                cwd=actual_cwd,
                shell=True,
                env=env,
                stdout=f_log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
            )

        return {
            "success": True,
            "process_id": f"bg_{process.pid}",
            "pid": process.pid,
            "log_file": log_file,
        }

    nohup_command = f"nohup env HOME=\"{original_home}\" {command} > /dev/null 2>&1 &"
    process = subprocess.Popen(
        nohup_command,
        cwd=actual_cwd,
        shell=True,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    return {
        "success": True,
        "process_id": f"bg_{process.pid}",
        "pid": process.pid,
    }


class SubprocessIsolation:
    """直接执行模式，无文件系统隔离"""
    
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
        执行 payload。
        
        Args:
            payload: 执行内容，包含 mode, module_path, func_name 等
            cwd: 工作目录
            
        Returns:
            执行结果
        """
        logger.info(f"[SubprocessIsolation] 开始执行")
        logger.info(f"  venv_dir: {self.venv_dir}")
        logger.info(f"  cwd: {cwd}")
        
        # 创建临时文件
        run_id = str(uuid.uuid4())
        sandbox_dir = self.sandbox_runtime_dir
        input_pkl, output_pkl, launcher_path = await asyncio.to_thread(
            _prepare_payload_files_sync,
            sandbox_dir,
            run_id,
            payload,
        )
        
        # 使用沙箱的 venv Python
        python_bin = os.path.join(self.venv_dir, "bin", "python")
        if platform.system() == "Windows":
             python_bin = os.path.join(self.venv_dir, "Scripts", "python.exe")
        
        cmd = [python_bin, launcher_path, input_pkl, output_pkl]
        
        # 构建环境变量
        env = os.environ.copy()
        
        # 设置 PATH，优先使用 venv
        venv_bin = os.path.join(self.venv_dir, "bin")
        if platform.system() == "Windows":
            venv_bin = os.path.join(self.venv_dir, "Scripts")
            
        current_path = env.get("PATH", "")
        env["PATH"] = f"{venv_bin}{os.pathsep}{current_path}"
        
        # 设置 PYTHONPATH
        pylibs_dir = os.path.join(sandbox_dir, ".pylibs")
        env["PIP_TARGET"] = pylibs_dir
        current_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{pylibs_dir}{os.pathsep}{self.sandbox_agent_workspace}{os.pathsep}{current_pythonpath}"
        
        # 保留原来的 HOME 目录
        env["HOME"] = os.environ.get("HOME", "")
        
        logger.info(f"[SubprocessIsolation] 执行命令: {' '.join(cmd[:3])}...")
        
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                cmd,
                capture_output=True,
                text=True,
                cwd=cwd or self.sandbox_agent_workspace,
                env=env,
                timeout=300,  # 5分钟超时
            )
            
            logger.info(f"[SubprocessIsolation] 返回码: {result.returncode}")
            
            if result.returncode != 0:
                logger.error(f"[SubprocessIsolation] 执行失败: {result.stderr[:500]}")
                raise Exception(f"Subprocess execution failed: {result.stderr}")
            
            res = await asyncio.to_thread(_load_pickle_output_sync, output_pkl)
            
            if res['status'] == 'success':
                logger.info(f"[SubprocessIsolation] 执行成功")
                return res['result']
            else:
                logger.error(f"[SubprocessIsolation] 执行错误: {res.get('error')}")
                raise Exception(f"Error in subprocess: {res.get('error')}")
                
        finally:
            # 清理临时文件
            try:
                await asyncio.to_thread(_remove_file_if_exists_sync, input_pkl)
            except Exception:
                pass
                    
    async def execute_background(self, command: str, cwd: Optional[str] = None) -> Dict[str, Any]:
        """
        后台执行命令。
        
        Args:
            command: 要执行的命令
            cwd: 工作目录
            
        Returns:
            包含进程信息的字典
        """
        logger.info(f"[SubprocessIsolation.execute_background] 开始后台执行")
        logger.info(f"  command: {command}")
        logger.info(f"  cwd: {cwd}")
        
        actual_cwd = cwd or self.sandbox_agent_workspace
        
        # 构建环境变量
        env = os.environ.copy()
        
        # 保留原来的 HOME 目录
        original_home = os.environ.get("HOME", "")
        
        process_info = await asyncio.to_thread(
            _spawn_background_process_sync,
            command,
            actual_cwd,
            env,
            original_home,
        )
        logger.info(f"[SubprocessIsolation.execute_background] 进程已启动, PID: {process_info.get('pid')}")
        return process_info

import multiprocessing
import resource
import time
import traceback
from typing import Any, Callable, Dict, Optional, List
import sys
import os
from sagents.utils.logger import logger

class SandboxError(Exception):
    pass

class ResourceLimitExceeded(SandboxError):
    pass

class SecurityViolation(SandboxError):
    pass

def _read_first_line(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.readline().strip()
    except Exception:
        return None

def _get_cgroup_memory_limit_bytes() -> Optional[int]:
    v2_path = "/sys/fs/cgroup/memory.max"
    v1_paths = [
        "/sys/fs/cgroup/memory/memory.limit_in_bytes",
        "/sys/fs/cgroup/memory.limit_in_bytes",
    ]
    line = _read_first_line(v2_path)
    if line and line != "max":
        try:
            value = int(line)
            if value > 0:
                return value
        except Exception:
            pass
    for path in v1_paths:
        line = _read_first_line(path)
        if not line:
            continue
        try:
            value = int(line)
            if value > 0 and value < (1 << 60):
                return value
        except Exception:
            continue
    return None

def _effective_memory_limit(limits: Dict[str, Any]) -> Optional[int]:
    if 'memory' not in limits:
        return None
    try:
        target = int(limits['memory'])
    except Exception:
        return None
    cgroup_limit = _get_cgroup_memory_limit_bytes()
    if cgroup_limit is not None:
        target = min(target, cgroup_limit)
    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    if hard != resource.RLIM_INFINITY:
        target = min(target, hard)
    return target

def _restricted_execution(func: Callable, args: tuple, kwargs: dict, result_queue: multiprocessing.Queue, limits: Dict[str, Any]):
    """
    Internal function to run code in a separate process with resource limits.
    """
    try:
        # Set CPU time limit (in seconds)
        if 'cpu_time' in limits:
            target = int(limits['cpu_time'])
            soft, hard = resource.getrlimit(resource.RLIMIT_CPU)
            
            if hard != resource.RLIM_INFINITY:
                target = min(target, hard)
            
            # Set soft limit to target, keep hard limit
            resource.setrlimit(resource.RLIMIT_CPU, (target, hard))
        
        # Set Memory limit (in bytes)
        if 'memory' in limits:
            target = _effective_memory_limit(limits)
            if target is not None:
                soft, hard = resource.getrlimit(resource.RLIMIT_AS)
                try:
                    resource.setrlimit(resource.RLIMIT_AS, (target, hard))
                except (ValueError, OSError):
                    pass

        # Simple file system restriction (logical)
        # In a real rigorous sandbox, this should be done via chroot or containerization (Docker/nsjail).
        # Here we patch open to restrict access to allowed directories if specified.
        allowed_paths = limits.get('allowed_paths', [])
        if allowed_paths:
            original_open = open
            def restricted_open(file, mode='r', buffering=-1, encoding=None, errors=None, newline=None, closefd=True, opener=None):
                # Resolve absolute path
                if isinstance(file, int):
                    # File descriptor
                    return original_open(file, mode, buffering, encoding, errors, newline, closefd, opener)
                
                abs_path = os.path.abspath(file)
                allowed = False
                for path in allowed_paths:
                    if abs_path.startswith(os.path.abspath(path)):
                        allowed = True
                        break
                
                if not allowed:
                    raise SecurityViolation(f"Access to file {abs_path} is denied.")
                
                return original_open(file, mode, buffering, encoding, errors, newline, closefd, opener)
            
            # Monkey patch builtins.open
            import builtins
            builtins.open = restricted_open

        # Execute the function
        result = func(*args, **kwargs)
        result_queue.put({'status': 'success', 'result': result})

    except Exception as e:
        result_queue.put({'status': 'error', 'error': str(e), 'traceback': traceback.format_exc()})

def _restricted_script_execution(script_path: str, args: list, requirements: Optional[list], install_cmd: Optional[str], result_queue: multiprocessing.Queue, limits: Dict[str, Any], cwd: Optional[str] = None):
    """
    Internal function to run a script in a separate process with resource limits.
    """
    import io
    import sys
    from contextlib import redirect_stdout, redirect_stderr
    
    # Capture stdout/stderr
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()
    
    # Prepare environment variables with mirrors
    env = os.environ.copy()
    env['npm_config_registry'] = 'https://registry.npmmirror.com'
    env['PLAYWRIGHT_DOWNLOAD_HOST'] = 'https://npmmirror.com/mirrors/playwright/'
    # Ensure system path is preserved
    
    try:
        # Switch to script directory or specified cwd
        script_dir = os.path.dirname(os.path.abspath(script_path))
        working_dir = cwd if cwd else script_dir

        if os.path.exists(working_dir):
            os.chdir(working_dir)

        normalized_requirements = _normalize_requirements(requirements)
        if normalized_requirements:
            _install_requirements(normalized_requirements, stdout_capture, stderr_capture)
            
        if install_cmd:
            _run_install_cmd(install_cmd, stdout_capture, stderr_capture, env=env)

        # 自动配置 NODE_PATH 以支持全局安装的 npm 包
        try:
            import subprocess
            npm_proc = subprocess.run(
                ['npm', 'root', '-g'],
                capture_output=True,
                text=True,
                env=env,
                cwd=working_dir
            )
            if npm_proc.returncode == 0:
                global_modules = npm_proc.stdout.strip()
                if global_modules:
                    current_path = env.get('NODE_PATH', '')
                    env['NODE_PATH'] = f"{global_modules}{os.pathsep}{current_path}" if current_path else global_modules
        except Exception:
            pass

        _apply_limits(limits, restrict_files=False)
        
        # Prepare sys.argv
        sys.argv = [script_path] + args
        
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            _, extension = os.path.splitext(script_path)
            extension = extension.lower()
            if extension in {'.js', '.mjs', '.cjs'}:
                import subprocess
                try:
                    result = subprocess.run(
                        ['node', script_path, *args],
                        capture_output=True,
                        text=True,
                        cwd=script_dir,
                        env=env
                    )
                except FileNotFoundError:
                    raise Exception("Node.js environment not found, please install Node.js first (Node.js 环境未找到，请先安装 Node.js)")

                if result.stdout:
                    stdout_capture.write(result.stdout)
                if result.stderr:
                    stderr_capture.write(result.stderr)
                if result.returncode != 0:
                    raise Exception(f"Script exited with code {result.returncode}")
            elif extension in {'.sh', '.bash'}:
                import subprocess
                shell_cmd = '/bin/bash' if extension == '.bash' else '/bin/sh'
                try:
                    result = subprocess.run(
                        [shell_cmd, script_path, *args],
                        capture_output=True,
                        text=True,
                        cwd=script_dir,
                        env=env
                    )
                except FileNotFoundError:
                    raise Exception(f"Shell executable {shell_cmd} not found")

                if result.stdout:
                    stdout_capture.write(result.stdout)
                if result.stderr:
                    stderr_capture.write(result.stderr)
                if result.returncode != 0:
                    raise Exception(f"Script exited with code {result.returncode}")
            else:
                with open(script_path, 'r', encoding='utf-8') as f:
                    script_content = f.read()
                
                # Ensure script directory is in sys.path for local imports
                if script_dir not in sys.path:
                    sys.path.insert(0, script_dir)

                global_ns = {'__name__': '__main__', '__file__': script_path}
                exec(script_content, global_ns)
            
        result_queue.put({
            'status': 'success', 
            'result': stdout_capture.getvalue() + stderr_capture.getvalue()
        })
            
    except Exception as e:
        error_msg = str(e)
        if isinstance(e, MemoryError):
            error_msg = "MemoryError (内存不足或超出限制)"
        result_queue.put({
            'status': 'error', 
            'error': error_msg, 
            'traceback': traceback.format_exc(),
            'output': stdout_capture.getvalue() + stderr_capture.getvalue()
        })

def _restricted_module_execution(module_path: str, func_name: str, requirements: Optional[list], args: tuple, kwargs: dict, result_queue: multiprocessing.Queue, limits: Dict[str, Any]):
    """
    Internal function to run code from a module in a separate process with resource limits.
    """
    import importlib.util
    try:
        normalized_requirements = _normalize_requirements(requirements)
        if normalized_requirements:
            _install_requirements(normalized_requirements, None, None)
            _apply_limits(limits, restrict_files=False)
        else:
            _apply_limits(limits)
        
        spec = importlib.util.spec_from_file_location("sandboxed_module", module_path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            func = getattr(module, func_name)
            
            # Execute
            result = func(*args, **kwargs)
            result_queue.put({'status': 'success', 'result': result})
        else:
            result_queue.put({'status': 'error', 'error': f"Could not load module from {module_path}"})
            
    except Exception as e:
        result_queue.put({'status': 'error', 'error': str(e), 'traceback': traceback.format_exc()})

def _apply_limits(limits: Dict[str, Any], restrict_files: bool = True):
    # Set CPU time limit (in seconds)
    if 'cpu_time' in limits:
        target = int(limits['cpu_time'])
        soft, hard = resource.getrlimit(resource.RLIMIT_CPU)
        
        if hard != resource.RLIM_INFINITY:
            target = min(target, hard)
        
        # Set soft limit to target, keep hard limit
        resource.setrlimit(resource.RLIMIT_CPU, (target, hard))
    
    # Set Memory limit (in bytes)
    if 'memory' in limits:
        target = _effective_memory_limit(limits)
        if target is not None:
            soft, hard = resource.getrlimit(resource.RLIMIT_AS)
            try:
                resource.setrlimit(resource.RLIMIT_AS, (target, hard))
            except (ValueError, OSError):
                pass

    # Simple file system restriction (logical)
    if not restrict_files:
        return
    allowed_paths = limits.get('allowed_paths', [])
    if allowed_paths:
        original_open = open
        def restricted_open(file, mode='r', buffering=-1, encoding=None, errors=None, newline=None, closefd=True, opener=None):
            # Resolve absolute path
            if isinstance(file, int):
                # File descriptor
                return original_open(file, mode, buffering, encoding, errors, newline, closefd, opener)
            
            abs_path = os.path.abspath(file)
            allowed = False
            for path in allowed_paths:
                if abs_path.startswith(os.path.abspath(path)):
                    allowed = True
                    break
            
            if not allowed:
                # raise SecurityViolation(f"Access to file {abs_path} is denied.")
                # Since SecurityViolation is not available in this scope easily without import, use Exception or ensure it is imported
                raise Exception(f"Access to file {abs_path} is denied (Sandboxed).")
            
            return original_open(file, mode, buffering, encoding, errors, newline, closefd, opener)
        
        # Monkey patch builtins.open
        import builtins
        builtins.open = restricted_open

def _normalize_requirements(requirements: Optional[list]) -> List[str]:
    if requirements is None:
        return []
    if isinstance(requirements, str):
        requirements = [requirements]
    if not isinstance(requirements, list):
        raise Exception("requirements 必须是字符串列表")
    return [r.strip() for r in requirements if isinstance(r, str) and r.strip()]

def _install_requirements(requirements: List[str], stdout_capture: Optional[Any], stderr_capture: Optional[Any]):
    if not requirements:
        return
    import subprocess
    python_exec = sys.executable or "python3"
    mirror = "https://mirrors.aliyun.com/pypi/simple"
    for requirement in requirements:
        result = subprocess.run(
            [python_exec, "-m", "pip", "install", requirement, "-i", mirror],
            capture_output=True,
            text=True
        )
        if stdout_capture is not None and result.stdout:
            stdout_capture.write(result.stdout)
        if stderr_capture is not None and result.stderr:
            stderr_capture.write(result.stderr)
        if result.returncode != 0:
            raise Exception(f"依赖安装失败: {requirement}")

def _run_install_cmd(install_cmd: str, stdout_capture: Optional[Any], stderr_capture: Optional[Any], env: Optional[Dict[str, str]] = None):
    import subprocess
    # Use shell=True to allow complex commands
    result = subprocess.run(
        install_cmd,
        shell=True,
        capture_output=True,
        text=True,
        env=env or os.environ.copy()
    )
    if stdout_capture is not None and result.stdout:
        stdout_capture.write(result.stdout)
    if stderr_capture is not None and result.stderr:
        stderr_capture.write(result.stderr)
    if result.returncode != 0:
        raise Exception(f"Install command failed: {install_cmd}")

class Sandbox:
    """
    A secure sandbox execution environment for skills.
    """
    def __init__(self, 
                 cpu_time_limit: int = 10, 
                 memory_limit_mb: int = 2048, 
                 allowed_paths: Optional[list] = None):
        """
        Initialize the sandbox.
        
        Args:
            cpu_time_limit: Max CPU time in seconds.
            memory_limit_mb: Max memory usage in MB.
            allowed_paths: List of paths allowed to be accessed by file operations.
        """
        self.limits = {
            'cpu_time': cpu_time_limit,
            'memory': memory_limit_mb * 1024 * 1024,
            'allowed_paths': allowed_paths or []
        }

    def run_module_function(self, module_path: str, func_name: str, *args, requirements: Optional[list] = None, **kwargs) -> Any:
        """
        Run a function loaded from a module file in the sandbox.
        """
        result_queue = multiprocessing.Queue()
        process = multiprocessing.Process(
            target=_restricted_module_execution, 
            args=(module_path, func_name, requirements, args, kwargs, result_queue, self.limits)
        )
        
        process.start()
        process.join()
        
        if not result_queue.empty():
            result = result_queue.get()
            if result['status'] == 'success':
                return result['result']
            else:
                output = result.get('output')
                output_block = f"\n{output}" if output else ""
                raise SandboxError(f"Error in sandboxed module: {result.get('error')}\n{result.get('traceback')}{output_block}")
        else:
            if process.exitcode is not None and process.exitcode != 0:
                raise SandboxError(f"Sandboxed process terminated. Exit code: {process.exitcode}")
            raise SandboxError("Sandboxed process died unexpectedly")

    def skill_run_script(self, script_path: str, args: list = None, requirements: Optional[list] = None, install_cmd: Optional[str] = None, cwd: Optional[str] = None) -> str:
        """
        Run a python script file in the sandbox and return stdout.
        """
        args = args or []
        result_queue = multiprocessing.Queue()
        process = multiprocessing.Process(
            target=_restricted_script_execution, 
            args=(script_path, args, requirements, install_cmd, result_queue, self.limits, cwd)
        )
        
        process.start()
        process.join()
        
        if not result_queue.empty():
            result = result_queue.get()
            if result['status'] == 'success':
                return result['result']
            else:
                output = result.get('output')
                output_block = f"\n{output}" if output else ""
                raise SandboxError(f"Error in sandboxed script: {result.get('error')}\n{result.get('traceback')}{output_block}")
        else:
            if process.exitcode is not None and process.exitcode != 0:
                raise SandboxError(f"Sandboxed process terminated. Exit code: {process.exitcode}")
            raise SandboxError("Sandboxed process died unexpectedly")

    def run(self, func: Callable, *args, **kwargs) -> Any:
        """
        Run a function in the sandbox.
        """
        result_queue = multiprocessing.Queue()
        process = multiprocessing.Process(
            target=_restricted_execution, 
            args=(func, args, kwargs, result_queue, self.limits)
        )
        
        process.start()
        process.join()
        
        if not result_queue.empty():
            result = result_queue.get()
            if result['status'] == 'success':
                return result['result']
            else:
                output = result.get('output')
                output_block = f"\n{output}" if output else ""
                raise SandboxError(f"Execution failed: {result.get('error')}\n{result.get('traceback')}{output_block}")
        else:
            if process.exitcode != 0:
                raise SandboxError(f"Process terminated abnormally. Exit code: {process.exitcode}")
            return None

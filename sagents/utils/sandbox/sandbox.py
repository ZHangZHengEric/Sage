import multiprocessing
import resource
import time
import traceback
from typing import Any, Callable, Dict, Optional, List, Union
import sys
import os
import contextvars
import subprocess
import platform
import pickle
import json
import venv
from sagents.utils.logger import logger

_current_sandbox = contextvars.ContextVar('current_sandbox', default=None)

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
    
    # On macOS, RLIMIT_AS (Virtual Memory Size) is strictly enforced and often causes
    # immediate crashes for Python processes (which may reserve large address spaces).
    # We skip strict memory limiting on macOS to prevent "Process died unexpectedly".
    if sys.platform == 'darwin':
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

# --- Launcher Script Content ---
LAUNCHER_SCRIPT = """
import sys
import os
import pickle
import traceback
import importlib
import importlib.util
import asyncio
import subprocess
import io
from contextlib import redirect_stdout, redirect_stderr

# Ensure current directory is in sys.path
sys.path.insert(0, os.getcwd())

def main():
    try:
        if len(sys.argv) < 3:
            raise ValueError("Usage: launcher.py <input_pkl> <output_pkl>")
            
        input_path = sys.argv[1]
        output_path = sys.argv[2]
        
        with open(input_path, 'rb') as f:
            payload = pickle.load(f)
            
        mode = payload['mode']
        args = payload.get('args', [])
        kwargs = payload.get('kwargs', {})
        sys_path = payload.get('sys_path', [])
        
        # Restore sys.path
        for p in reversed(sys_path):
            if p not in sys.path:
                sys.path.insert(0, p)
        
        result = None
        
        if mode == 'library':
            module_name = payload['module_name']
            class_name = payload.get('class_name')
            function_name = payload['function_name']
            
            module = importlib.import_module(module_name)
            if class_name:
                cls = getattr(module, class_name)
                instance = cls()
                func = getattr(instance, function_name)
            else:
                func = getattr(module, function_name)
                
            if asyncio.iscoroutinefunction(func):
                result = asyncio.run(func(*args, **kwargs))
            else:
                result = func(*args, **kwargs)
                
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
            
            # Capture output
            stdout = io.StringIO()
            stderr = io.StringIO()
            
            try:
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    exec(script_content, global_ns)
            except Exception:
                # Print traceback to stderr capture
                traceback.print_exc(file=stderr)
                raise
                
            result = stdout.getvalue() + stderr.getvalue()

        elif mode == 'shell':
            cmd = payload['command']
            cwd = payload.get('cwd')
            # For shell, we use subprocess inside the sandbox
            proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
            if proc.returncode != 0:
                 raise Exception(f"Command failed with code {proc.returncode}: {proc.stderr}")
            result = proc.stdout

        with open(output_path, 'wb') as f:
            pickle.dump({'status': 'success', 'result': result}, f)
            
    except Exception as e:
        try:
            with open(output_path, 'wb') as f:
                pickle.dump({'status': 'error', 'error': str(e), 'traceback': traceback.format_exc()}, f)
        except Exception:
            # Fallback if writing fails
            traceback.print_exc()
            sys.exit(1)

if __name__ == "__main__":
    main()
"""

# Deleted duplicate class definition




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

        # Setup isolated environment
        _setup_sandbox_env(working_dir, env)

        normalized_requirements = _normalize_requirements(requirements)
        if normalized_requirements:
            _install_requirements(normalized_requirements, stdout_capture, stderr_capture, env=env)
            
        if install_cmd:
            _run_install_cmd(install_cmd, stdout_capture, stderr_capture, env=env)

        # 自动配置 NODE_PATH 以支持全局安装的 npm 包 (Retain logic but adapt to new env if needed, though _setup_sandbox_env handles PATH)
        # Note: _setup_sandbox_env sets NPM_CONFIG_PREFIX, so `npm install -g` goes there.
        # We still check for NODE_PATH compatibility just in case.
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
                        cwd=working_dir,
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
            elif extension == '.py':
                import subprocess
                python_exec = sys.executable or 'python3'
                try:
                    result = subprocess.run(
                        [python_exec, script_path, *args],
                        capture_output=True,
                        text=True,
                        cwd=working_dir,
                        env=env
                    )
                except FileNotFoundError:
                    raise Exception("Python environment not found, please install Python first (Python 环境未找到，请先安装 Python)")

                if result.stdout:
                    stdout_capture.write(result.stdout)
                if result.stderr:
                    stderr_capture.write(result.stderr)
                if result.returncode != 0:
                    raise Exception(f"Script exited with code {result.returncode}")
            elif extension == '.go':
                import subprocess
                try:
                    result = subprocess.run(
                        ['go', 'run', script_path, *args],
                        capture_output=True,
                        text=True,
                        cwd=working_dir,
                        env=env
                    )
                except FileNotFoundError:
                    raise Exception("Go environment not found, please install Go first (Go 环境未找到，请先安装 Go)")

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
                        cwd=working_dir,
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

def _restricted_shell_execution(command: str, result_queue: multiprocessing.Queue, limits: Dict[str, Any], cwd: Optional[str] = None):
    """
    Internal function to run shell command in a separate process.
    """
    import io
    import subprocess
    from contextlib import redirect_stdout, redirect_stderr
    
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()
    
    env = os.environ.copy()
    env['npm_config_registry'] = 'https://registry.npmmirror.com'
    env['PLAYWRIGHT_DOWNLOAD_HOST'] = 'https://npmmirror.com/mirrors/playwright/'

    try:
        working_dir = cwd if cwd else os.getcwd()
        if os.path.exists(working_dir):
            os.chdir(working_dir)
            
        # Setup isolated environment
        _setup_sandbox_env(working_dir, env)
            
        _apply_limits(limits, restrict_files=False)
        
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=working_dir,
            env=env
        )
        
        if result.stdout:
            stdout_capture.write(result.stdout)
        if result.stderr:
            stderr_capture.write(result.stderr)
            
        if result.returncode != 0:
             raise Exception(f"Command exited with code {result.returncode}")
             
        result_queue.put({
            'status': 'success', 
            'result': stdout_capture.getvalue() + stderr_capture.getvalue()
        })
        
    except Exception as e:
        result_queue.put({
            'status': 'error', 
            'error': str(e), 
            'traceback': traceback.format_exc(),
            'output': stdout_capture.getvalue() + stderr_capture.getvalue()
        })

def _restricted_module_execution(module_path: str, func_name: str, requirements: Optional[list], args: tuple, kwargs: dict, result_queue: multiprocessing.Queue, limits: Dict[str, Any]):
    """
    Internal function to run code from a module in a separate process with resource limits.
    """
    import importlib.util
    try:
        # For module execution, we assume the module's directory is the working directory for env setup
        working_dir = os.path.dirname(os.path.abspath(module_path))
        
        # Setup env (though we can't easily change os.environ for the current process effectively for importlib 
        # if libraries are already loaded, but we can update sys.path)
        env = os.environ.copy()
        _setup_sandbox_env(working_dir, env)
        
        # Add isolated pylibs to sys.path
        pylibs_dir = env.get('PIP_TARGET')
        if pylibs_dir and pylibs_dir not in sys.path:
            sys.path.insert(0, pylibs_dir)
            
        normalized_requirements = _normalize_requirements(requirements)
        if normalized_requirements:
            _install_requirements(normalized_requirements, None, None, env=env)
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

def _restricted_library_execution(module_name: str, class_name: Optional[str], function_name: str, args: tuple, kwargs: dict, result_queue: multiprocessing.Queue, limits: Dict[str, Any], cwd: Optional[str], sys_path: List[str]):
    """
    Internal function to run a library function in a separate process.
    """
    import sys
    import importlib
    import asyncio
    
    # Restore sys.path to ensure we can find the project modules
    if sys_path:
        for p in reversed(sys_path):
            if p not in sys.path:
                sys.path.insert(0, p)
                
    # Setup cwd
    if cwd and os.path.exists(cwd):
        os.chdir(cwd)
        
    try:
        # Apply limits (including monkey patching open)
        _apply_limits(limits)
        
        # Import module
        module = importlib.import_module(module_name)
        
        # Get function
        if class_name:
            cls = getattr(module, class_name)
            # Instantiate class (assuming no-arg constructor for Tool classes)
            instance = cls()
            func = getattr(instance, function_name)
        else:
            func = getattr(module, function_name)
            
        # Execute
        if asyncio.iscoroutinefunction(func):
            result = asyncio.run(func(*args, **kwargs))
        else:
            result = func(*args, **kwargs)
            
        result_queue.put({'status': 'success', 'result': result})
        
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

def _setup_sandbox_env(working_dir: str, env: Dict[str, str]):
    """
    Setup isolated environment variables for the sandbox.
    """
    # Node.js isolation
    npm_global_dir = os.path.join(working_dir, ".npm_global")
    npm_bin_dir = os.path.join(npm_global_dir, "bin")
    env['NPM_CONFIG_PREFIX'] = npm_global_dir
    
    # Python isolation
    # We use PIP_TARGET to install packages into a local directory
    # and add it to PYTHONPATH.
    pylibs_dir = os.path.join(working_dir, ".pylibs")
    env['PIP_TARGET'] = pylibs_dir
    
    # Update PATH and PYTHONPATH
    current_path = env.get('PATH', '')
    env['PATH'] = f"{npm_bin_dir}{os.pathsep}{pylibs_dir}/bin{os.pathsep}{current_path}"
    
    current_pythonpath = env.get('PYTHONPATH', '')
    env['PYTHONPATH'] = f"{pylibs_dir}{os.pathsep}{working_dir}{os.pathsep}{current_pythonpath}"
    
    # Set non-interactive mode for apt-get
    env['DEBIAN_FRONTEND'] = 'noninteractive'

def _install_requirements(requirements: List[str], stdout_capture: Optional[Any], stderr_capture: Optional[Any], env: Optional[Dict[str, str]] = None):
    if not requirements:
        return
    import subprocess
    python_exec = sys.executable or "python3"
    mirror = "https://mirrors.aliyun.com/pypi/simple"
    
    install_env = env or os.environ.copy()
    
    for requirement in requirements:
        # Note: If env contains PIP_TARGET, pip will automatically use it.
        cmd = [python_exec, "-m", "pip", "install", requirement, "-i", mirror]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=install_env
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

from sagents.utils.sandbox.filesystem import SandboxFileSystem

class Sandbox:
    def __init__(self, cpu_time_limit: int = 10, memory_limit_mb: int = 1024, allowed_paths: Optional[List[str]] = None, host_workspace: Optional[str] = None, virtual_workspace: str = "/workspace", linux_isolation_mode: str = 'bwrap'):
        """
        Initialize the Sandbox.

        Args:
            cpu_time_limit: CPU time limit in seconds.
            memory_limit_mb: Memory limit in MB.
            allowed_paths: List of allowed paths (for Seatbelt/Sandbox).
            host_workspace: The host workspace path.
            virtual_workspace: The virtual workspace path inside the sandbox.
            linux_isolation_mode: Isolation mode for Linux ('auto', 'chroot', 'bwrap', 'subprocess'). Default is 'bwrap'.
                                  - 'auto': Automatically detect available isolation method (bwrap -> subprocess).
                                  - 'chroot': Use chroot for isolation (requires root or configured chroot env).
                                  - 'bwrap': Use bubblewrap for isolation (unprivileged).
                                  - 'subprocess': Direct execution in venv (no FS isolation).
        """
        # Default allowed system paths required for common libraries (e.g., pandas/dateutil need zoneinfo, openpyxl/mimetypes need mime.types)
        default_allowed_paths = [
            "/usr/share/zoneinfo",
            "/etc/localtime",
            "/etc/mime.types",
            "/etc/apache2/mime.types",
            "/etc/httpd/mime.types",
            "/usr/local/etc/mime.types"
        ]
        
        # Merge allowed_paths with default_allowed_paths
        final_allowed_paths = list(set((allowed_paths or []) + default_allowed_paths))
        
        self.limits = {
            'cpu_time': cpu_time_limit,
            'memory': memory_limit_mb * 1024 * 1024,  # Convert to bytes
            'allowed_paths': final_allowed_paths
        }
        self.host_workspace = host_workspace
        self.linux_isolation_mode = self._resolve_linux_mode(linux_isolation_mode)
        self.virtual_workspace = virtual_workspace
        self.file_system = None

        self.sandbox_dir = None
        self.venv_dir = None

        if host_workspace:
            # Enable path mapping only on macOS (Darwin).
            # On Linux (future bwrap implementation), we can use bind mounts to map paths natively,
            # eliminating the need for text-based path replacement.
            enable_path_mapping = (sys.platform == 'darwin')
            self.file_system = SandboxFileSystem(
                host_path=host_workspace, 
                virtual_path=virtual_workspace,
                enable_path_mapping=enable_path_mapping
            )
            
            # Ensure host workspace is in allowed paths
            if host_workspace not in self.limits['allowed_paths']:
                self.limits['allowed_paths'].append(host_workspace)
            
            self.sandbox_dir = os.path.join(host_workspace, ".sandbox")
            self.venv_dir = os.path.join(self.sandbox_dir, "venv")
            
            # Ensure sandbox directory exists
            os.makedirs(self.sandbox_dir, exist_ok=True)
            
            # Ensure venv exists
            self._ensure_venv()
            
            # Add sandbox dir to allowed paths
            if self.sandbox_dir not in self.limits['allowed_paths']:
                self.limits['allowed_paths'].append(self.sandbox_dir)

    def _resolve_linux_mode(self, mode: str) -> str:
        if mode != 'auto':
            return mode
            
        # Auto-detect logic
        import shutil
        if shutil.which('bwrap'):
            return 'bwrap'
        else:
            return 'subprocess'

    def _ensure_venv(self):
        if not self.sandbox_dir or not self.venv_dir:
            return

        python_bin = os.path.join(self.venv_dir, "bin", "python")

        # 默认不安装 pip，提升速度
        if not os.path.exists(python_bin):
            venv.create(self.venv_dir, with_pip=False, clear=True)
            
        launcher_path = os.path.join(self.sandbox_dir, "launcher.py")
        if not os.path.exists(launcher_path) or os.path.getsize(launcher_path) != len(LAUNCHER_SCRIPT):
             with open(launcher_path, "w", encoding="utf-8") as f:
                 f.write(LAUNCHER_SCRIPT)

    def ensure_pip(self):
        """Ensure pip is installed in the virtual environment."""
        if not self.venv_dir:
            return

        pip_bin = os.path.join(self.venv_dir, "bin", "pip")
        if os.path.exists(pip_bin):
            return

        logger.info(f"Installing pip in sandbox venv at {self.venv_dir}...")
        try:
             # Use ensurepip to install pip
             python_bin = os.path.join(self.venv_dir, "bin", "python")
             subprocess.run([python_bin, "-m", "ensurepip"], check=True, capture_output=True)
             self._configure_pip_mirror()
        except Exception as e:
             logger.error(f"Failed to install pip via ensurepip: {e}")
             # Fallback to recreation if ensurepip fails
             logger.info("Recreating venv with pip...")
             venv.create(self.venv_dir, with_pip=True, clear=True)
             self._configure_pip_mirror()

    def _configure_pip_mirror(self):
        """配置 venv 的 pip 镜像源，解决 SSL 和网络问题"""
        pip_conf_path = os.path.join(self.venv_dir, "pip.conf")
        # 如果 pip.conf 不存在，则创建
        if not os.path.exists(pip_conf_path):
            config_content = """[global]
index-url = https://pypi.tuna.tsinghua.edu.cn/simple
trusted-host = pypi.tuna.tsinghua.edu.cn
timeout = 120
"""
            with open(pip_conf_path, "w") as f:
                f.write(config_content)


    def _generate_seatbelt_profile(self, output_path: str, additional_read_paths: List[str] = [], additional_write_paths: List[str] = []) -> str:
        profile_path = os.path.join(self.sandbox_dir, "profile.sb")
        
        sb_lines = [
            "(version 1)",
            "(deny default)",
            "(allow process-exec*)",
            "(allow process-fork)",
            "(allow signal)",
            "(allow sysctl-read)",
            "(allow ipc-posix-shm)",
            "(allow network*)",
            '(allow file-read* (subpath "/"))', 
            f'(allow file-write* (subpath "{self.sandbox_dir}"))',
            '(allow file-write* (subpath "/private/var/folders"))',
            '(allow file-write* (subpath "/tmp"))',
            '(allow file-write* (subpath "/dev/null"))',
        ]
        
        for p in self.limits.get('allowed_paths', []) + additional_write_paths:
             if p:
                sb_lines.append(f'(allow file-write* (subpath "{os.path.abspath(p)}"))')
        
        sb_content = "\n".join(sb_lines)
        
        with open(profile_path, "w") as f:
            f.write(sb_content)
            
        return profile_path

    def _run_with_seatbelt(self, payload: dict, cwd: Optional[str] = None) -> Any:
        if not self.sandbox_dir:
             raise SandboxError("Sandbox directory not initialized")

        import uuid
        run_id = str(uuid.uuid4())
        input_pkl = os.path.join(self.sandbox_dir, f"input_{run_id}.pkl")
        output_pkl = os.path.join(self.sandbox_dir, f"output_{run_id}.pkl")
        
        with open(input_pkl, "wb") as f:
            pickle.dump(payload, f)
            
        # Determine logger directory to allow write access
        from sagents.utils.logger import logger
        log_dir = getattr(logger, 'log_dir', None)
        additional_write_paths = [cwd] if cwd else []
        if log_dir:
            additional_write_paths.append(log_dir)

        profile_path = self._generate_seatbelt_profile(
            output_path=output_pkl,
            additional_read_paths=[input_pkl],
            additional_write_paths=additional_write_paths
        )
        
        python_bin = os.path.join(self.venv_dir, "bin", "python")
        launcher_path = os.path.join(self.sandbox_dir, "launcher.py")
        
        cmd = [
            "sandbox-exec", "-f", profile_path,
            python_bin, launcher_path,
            input_pkl, output_pkl
        ]
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=cwd or self.sandbox_dir
            )
            
            if result.returncode != 0:
                 raise SandboxError(f"Sandbox execution failed (code {result.returncode}):\nStdout: {result.stdout}\nStderr: {result.stderr}")
                 
            if not os.path.exists(output_pkl):
                 raise SandboxError("Sandbox execution produced no output file")
                 
            with open(output_pkl, "rb") as f:
                res = pickle.load(f)
                
            if res['status'] == 'success':
                return res['result']
            else:
                raise SandboxError(f"Error in sandbox: {res.get('error')}\n{res.get('traceback')}")
                
        finally:
            if os.path.exists(input_pkl):
                try: os.remove(input_pkl)
                except: pass
            if os.path.exists(output_pkl):
                try: os.remove(output_pkl)
                except: pass
            if os.path.exists(profile_path):
                try: os.remove(profile_path)
                except: pass

    def _run_with_subprocess(self, payload: dict, cwd: Optional[str] = None) -> Any:
        """
        Run the payload in a subprocess using the sandbox venv (no filesystem isolation).
        """
        if not self.sandbox_dir:
             raise SandboxError("Sandbox directory not initialized")

        import uuid
        run_id = str(uuid.uuid4())
        input_pkl = os.path.join(self.sandbox_dir, f"input_{run_id}.pkl")
        output_pkl = os.path.join(self.sandbox_dir, f"output_{run_id}.pkl")
        
        with open(input_pkl, "wb") as f:
            pickle.dump(payload, f)
            
        python_bin = os.path.join(self.venv_dir, "bin", "python")
        launcher_path = os.path.join(self.sandbox_dir, "launcher.py")
        
        cmd = [
            python_bin, launcher_path,
            input_pkl, output_pkl
        ]
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=cwd or self.host_workspace
            )
            
            if result.returncode != 0:
                 raise SandboxError(f"Sandbox execution failed (code {result.returncode}):\nStdout: {result.stdout}\nStderr: {result.stderr}")
                 
            if not os.path.exists(output_pkl):
                 raise SandboxError("Sandbox execution produced no output file")
                 
            with open(output_pkl, "rb") as f:
                res = pickle.load(f)
                
            if res['status'] == 'success':
                return res['result']
            else:
                raise SandboxError(f"Error in sandbox: {res.get('error')}\n{res.get('traceback')}")
                
        finally:
            if os.path.exists(input_pkl):
                try: os.remove(input_pkl)
                except: pass
            if os.path.exists(output_pkl):
                try: os.remove(output_pkl)
                except: pass

    def _run_with_chroot(self, payload: dict, cwd: Optional[str] = None) -> Any:
        """
        Run the payload using chroot. 
        Note: This requires the sandbox_dir to be a valid root filesystem or at least contain 
        necessary libraries for the venv python to run.
        """
        if not self.sandbox_dir:
             raise SandboxError("Sandbox directory not initialized")

        import uuid
        run_id = str(uuid.uuid4())
        input_pkl = os.path.join(self.sandbox_dir, f"input_{run_id}.pkl")
        output_pkl = os.path.join(self.sandbox_dir, f"output_{run_id}.pkl")
        
        with open(input_pkl, "wb") as f:
            pickle.dump(payload, f)
            
        # Paths relative to the new root (sandbox_dir)
        inner_launcher = "/launcher.py"
        inner_input = f"/input_{run_id}.pkl"
        inner_output = f"/output_{run_id}.pkl"
        inner_python = "/venv/bin/python"
        
        cmd = [
            "chroot",
            self.sandbox_dir,
            inner_python, inner_launcher,
            inner_input, inner_output
        ]
        
        try:
            # We cannot easily set CWD inside chroot with simple `chroot` command without using `sh -c cd ...`
            # For now we ignore CWD for chroot mode or assume the script handles paths.
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                 error_msg = f"Sandbox execution failed (code {result.returncode}):\nStdout: {result.stdout}\nStderr: {result.stderr}"
                 if result.returncode == 127 or "No such file or directory" in result.stderr:
                     error_msg += "\n\n[Hint] 'chroot' mode requires a complete RootFS (libraries, bin, etc.) in the sandbox directory.\n"
                     error_msg += "If you only have a python venv, please use 'bwrap' mode (requires bubblewrap installed) or 'subprocess' mode."
                 raise SandboxError(error_msg)
                 
            if not os.path.exists(output_pkl):
                 raise SandboxError("Sandbox execution produced no output file")
                 
            with open(output_pkl, "rb") as f:
                res = pickle.load(f)
                
            if res['status'] == 'success':
                return res['result']
            else:
                raise SandboxError(f"Error in sandbox: {res.get('error')}\n{res.get('traceback')}")
                
        finally:
            if os.path.exists(input_pkl):
                try: os.remove(input_pkl)
                except: pass
            if os.path.exists(output_pkl):
                try: os.remove(output_pkl)
                except: pass

    def _run_with_bwrap(self, payload: dict, cwd: Optional[str] = None) -> Any:
        if not self.sandbox_dir:
             raise SandboxError("Sandbox directory not initialized")

        import uuid
        run_id = str(uuid.uuid4())
        input_pkl = os.path.join(self.sandbox_dir, f"input_{run_id}.pkl")
        output_pkl = os.path.join(self.sandbox_dir, f"output_{run_id}.pkl")
        
        with open(input_pkl, "wb") as f:
            pickle.dump(payload, f)
            
        python_bin = os.path.join(self.venv_dir, "bin", "python")
        launcher_path = os.path.join(self.sandbox_dir, "launcher.py")
        
        # Build bwrap command
        # We construct a new root filesystem by binding top-level directories from host,
        # instead of binding '/' recursively. This allows us to create new mount points (like /workspace)
        # even if they don't exist on the host, because the root is an implicit tmpfs.
        cmd = [
            "bwrap",
            "--dev", "/dev",                  # Device files
            "--proc", "/proc",                # Process info
            "--tmpfs", "/tmp",                # Temp filesystem
            "--unshare-all",                  # Create new namespaces
            "--share-net",                    # Share network
            "--die-with-parent",              # Cleanup
        ]

        # Bind top-level directories from host
        try:
            for name in os.listdir("/"):
                if name in [".", "..", "dev", "proc", "tmp", "lost+found"]:
                    continue
                
                path = os.path.join("/", name)
                # Skip if path doesn't exist (symlink broken?)
                if not os.path.exists(path) and not os.path.islink(path):
                    continue

                if os.path.islink(path):
                    try:
                        target = os.readlink(path)
                        cmd.extend(["--symlink", target, f"/{name}"])
                    except OSError:
                        pass
                elif os.path.isdir(path):
                    cmd.extend(["--ro-bind", path, f"/{name}"])
        except Exception as e:
            logger.warning(f"Error while constructing bwrap root: {e}")
            # Fallback to simple root bind if listdir fails (unlikely)
            cmd.extend(["--ro-bind", "/", "/"])

        # Bind workspace and sandbox dir
        cmd.extend([
            "--bind", self.host_workspace, self.virtual_workspace,
            "--bind", self.sandbox_dir, self.sandbox_dir
        ])

        cmd.extend(["--chdir", cwd or self.virtual_workspace])
        
        # Add the command to run
        cmd.extend([
            python_bin, launcher_path,
            input_pkl, output_pkl
        ])
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.host_workspace # Run from host workspace so relative paths in bwrap args resolve? Actually bwrap handles absolute paths.
            )
            
            if result.returncode != 0:
                 raise SandboxError(f"Sandbox execution failed (code {result.returncode}):\nStdout: {result.stdout}\nStderr: {result.stderr}")
                 
            if not os.path.exists(output_pkl):
                 raise SandboxError("Sandbox execution produced no output file")
                 
            with open(output_pkl, "rb") as f:
                res = pickle.load(f)
                
            if res['status'] == 'success':
                return res['result']
            else:
                raise SandboxError(f"Error in sandbox: {res.get('error')}\n{res.get('traceback')}")
        
        except FileNotFoundError:
             raise SandboxError("Bubblewrap (bwrap) executable not found. Please install bubblewrap (e.g., `apt install bubblewrap` or `yum install bubblewrap`).")
                
        finally:
            if os.path.exists(input_pkl):
                try: os.remove(input_pkl)
                except: pass
            if os.path.exists(output_pkl):
                try: os.remove(output_pkl)
                except: pass

    def __enter__(self):
        self._token = _current_sandbox.set(self)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if hasattr(self, '_token'):
            _current_sandbox.reset(self._token)
            
    @staticmethod
    def current() -> Optional['Sandbox']:
        return _current_sandbox.get()

    def run_tool(self, tool_func: Callable, kwargs: Dict[str, Any], tool_obj: Any = None) -> Any:
        """
        Runs a tool function within the sandbox.
        """
        # 1. Map paths in kwargs
        host_kwargs = self._map_to_host(kwargs)
        
        # 2. Extract module/function info
        func = tool_func
        if hasattr(func, "__self__"):
            # Bound method
            instance = func.__self__
            module_name = instance.__class__.__module__
            class_name = instance.__class__.__name__
            function_name = func.__name__
        elif tool_obj:
            # Maybe provided explicitly
            module_name = tool_obj.__module__
            class_name = tool_obj.__class__.__name__
            function_name = func.__name__
        else:
            # Unbound function
            module_name = func.__module__
            # Try to guess class if it's a method
            parts = func.__qualname__.split('.')
            if len(parts) > 1:
                class_name = parts[-2]
                function_name = parts[-1]
            else:
                class_name = None
                function_name = func.__name__

        # 3. Run
        result = self.run_library_task(
            module_name=module_name,
            class_name=class_name,
            function_name=function_name,
            args=(),
            kwargs=host_kwargs,
            cwd=self.host_workspace if self.host_workspace else None
        )
        
        # 4. Map paths in result
        return self._map_to_virtual(result)

    def _map_to_host(self, obj: Any) -> Any:
        if not self.file_system:
            return obj
        if isinstance(obj, str):
            # Use map_text_to_host to replace path in commands/scripts/paths
            return self.file_system.map_text_to_host(obj)
        elif isinstance(obj, dict):
            return {k: self._map_to_host(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._map_to_host(item) for item in obj]
        return obj

    def _map_to_virtual(self, obj: Any) -> Any:
        if not self.file_system:
            return obj
        if isinstance(obj, str):
            # Use map_text_to_virtual to hide host paths in output
            return self.file_system.map_text_to_virtual(obj)
        elif isinstance(obj, dict):
            return {k: self._map_to_virtual(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._map_to_virtual(item) for item in obj]
        return obj

    def run_module_function(self, module_path: str, func_name: str, *args, requirements: Optional[list] = None, **kwargs) -> Any:
        """
        Run a function loaded from a module file in the sandbox.
        """
        if (sys.platform == 'darwin' or sys.platform == 'linux') and self.sandbox_dir:
            payload = {
                'mode': 'module',
                'module_path': module_path,
                'func_name': func_name,
                'args': args,
                'kwargs': kwargs,
                'requirements': requirements
            }
            if sys.platform == 'linux':
                if self.linux_isolation_mode == 'bwrap':
                    return self._run_with_bwrap(payload)
                elif self.linux_isolation_mode == 'chroot':
                    return self._run_with_chroot(payload)
                else:
                    return self._run_with_subprocess(payload)
            return self._run_with_seatbelt(payload)

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

    def run_library_task(self, module_name: str, function_name: str, args: tuple = (), kwargs: dict = {}, class_name: Optional[str] = None, cwd: Optional[str] = None) -> Any:
        """
        Run a function from an installed library module in the sandbox.
        
        Args:
            module_name: The dotted name of the module (e.g. 'sagents.tool.impl.file_system_tool')
            function_name: The name of the function to call
            args: Positional arguments for the function
            kwargs: Keyword arguments for the function
            class_name: Optional class name if the function is a method of a class. The class must be instantiable without arguments.
            cwd: Optional current working directory to set in the sandbox
        """
        if (sys.platform == 'darwin' or sys.platform == 'linux') and self.sandbox_dir:
            payload = {
                'mode': 'library',
                'module_name': module_name,
                'class_name': class_name,
                'function_name': function_name,
                'args': args,
                'kwargs': kwargs,
                'sys_path': sys.path
            }
            if sys.platform == 'linux':
                if self.linux_isolation_mode == 'bwrap':
                    return self._run_with_bwrap(payload, cwd=cwd)
                elif self.linux_isolation_mode == 'chroot':
                    return self._run_with_chroot(payload, cwd=cwd)
                else:
                    return self._run_with_subprocess(payload, cwd=cwd)
            return self._run_with_seatbelt(payload, cwd=cwd)

        result_queue = multiprocessing.Queue()
        process = multiprocessing.Process(
            target=_restricted_library_execution, 
            args=(module_name, class_name, function_name, args, kwargs, result_queue, self.limits, cwd, sys.path)
        )
        
        process.start()
        process.join()
        
        if not result_queue.empty():
            result = result_queue.get()
            if result['status'] == 'success':
                return result['result']
            else:
                raise SandboxError(f"Error in sandboxed task: {result.get('error')}\n{result.get('traceback')}")
        else:
             if process.exitcode is not None and process.exitcode != 0:
                raise SandboxError(f"Sandboxed process terminated. Exit code: {process.exitcode}")
             raise SandboxError("Sandboxed process died unexpectedly")

    def skill_run_script(self, script_path: str, args: list = None, requirements: Optional[list] = None, install_cmd: Optional[str] = None, cwd: Optional[str] = None) -> str:
        """
        Run a python script file in the sandbox and return stdout.
        """
        args = args or []
        if (sys.platform == 'darwin' or sys.platform == 'linux') and self.sandbox_dir:
            payload = {
                'mode': 'script',
                'script_path': script_path,
                'args': args,
                'requirements': requirements,
                'install_cmd': install_cmd
            }
            if sys.platform == 'linux':
                if self.linux_isolation_mode == 'bwrap':
                    return self._run_with_bwrap(payload, cwd=cwd)
                elif self.linux_isolation_mode == 'chroot':
                    return self._run_with_chroot(payload, cwd=cwd)
                else:
                    return self._run_with_subprocess(payload, cwd=cwd)
            return self._run_with_seatbelt(payload, cwd=cwd)

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

    def run_shell_command(self, command: str, cwd: Optional[str] = None) -> str:
        """
        Run a raw shell command in the sandbox.
        """
        target_cwd = cwd or self.host_workspace
        
        if (sys.platform == 'darwin' or sys.platform == 'linux') and self.sandbox_dir:
            payload = {
                'mode': 'shell',
                'command': command,
                'cwd': target_cwd
            }
            if sys.platform == 'linux':
                if self.linux_isolation_mode == 'bwrap':
                    return self._run_with_bwrap(payload, cwd=target_cwd)
                elif self.linux_isolation_mode == 'chroot':
                    return self._run_with_chroot(payload, cwd=target_cwd)
                else:
                    return self._run_with_subprocess(payload, cwd=target_cwd)
            return self._run_with_seatbelt(payload, cwd=target_cwd)

        result_queue = multiprocessing.Queue()
        process = multiprocessing.Process(
            target=_restricted_shell_execution, 
            args=(command, result_queue, self.limits, target_cwd)
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
                raise SandboxError(f"Error in sandboxed command: {result.get('error')}\n{result.get('traceback')}{output_block}")
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

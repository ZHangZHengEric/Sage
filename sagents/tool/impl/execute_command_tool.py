#!/usr/bin/env python3
"""
Execute Command Tool

基于 Tool 注解实现的命令执行工具，提供与 mcp_servers/execute_command/execute_command.py 相同的功能。
具备完善的安全机制和错误处理。
"""

import os
import stat
import asyncio
import subprocess
import tempfile
import time
import platform
import shutil
import hashlib
import traceback
from typing import Dict, List, Any, Optional, Tuple, Union

from sagents.utils.common_utils import ensure_list, get_system_python_path
from ..tool_base import tool
from sagents.utils.logger import logger

class SecurityManager:
    """安全管理器 - 负责命令安全检查"""
    
    # 危险命令黑名单
    DANGEROUS_COMMANDS = {
        'format', 'fdisk', 'mkfs',
        'sudo', 'su', 'passwd',
        'shutdown', 'reboot', 'systemctl', 'service',
        'dd', 'crontab', 'at', 'batch'
    }
    
    # 恶意模式检测
    MALICIOUS_PATTERNS = [
        # '&&', '||', ';', '|',
        # '>', '>>', '<',
        # '$(', '`',
        # 'curl', 'wget', 'nc', 'netcat'
    ]
    
    def __init__(self, enable_dangerous_commands: bool = False):
        self.enable_dangerous_commands = enable_dangerous_commands
    
    def is_command_safe(self, command: str) -> Tuple[bool, str]:
        """检查命令是否安全"""
        if not command or not command.strip():
            return False, "命令不能为空"
        
        command = command.strip().lower()
        
        # 检查危险命令
        if not self.enable_dangerous_commands:
            command_parts = command.split()
            if command_parts:
                base_command = command_parts[0].split('/')[-1]  # 处理绝对路径
                if base_command in self.DANGEROUS_COMMANDS or base_command.startswith('mkfs.'):
                    return False, f"危险命令被阻止: {base_command}"
        
        # 检查恶意模式
        for pattern in self.MALICIOUS_PATTERNS:
            if pattern in command:
                if not self.enable_dangerous_commands:
                    return False, f"检测到潜在恶意模式: {pattern}"
        
        return True, "命令安全检查通过"

class ProcessManager:
    """进程管理器 - 负责进程的创建、监控和清理"""
    
    def __init__(self):
        self.running_processes = {}
        self.process_counter = 0
    
    def generate_process_id(self) -> str:
        """生成唯一的进程ID"""
        self.process_counter += 1
        timestamp = int(time.time() * 1000)
        return f"proc_{timestamp}_{self.process_counter}"
    
    def add_process(self, process_id: str, process: subprocess.Popen):
        """添加进程到管理列表"""
        self.running_processes[process_id] = {
            'process': process,
            'start_time': time.time(),
            'pid': process.pid
        }
    
    def remove_process(self, process_id: str):
        """从管理列表中移除进程"""
        if process_id in self.running_processes:
            del self.running_processes[process_id]
    
    def terminate_process(self, process_id: str) -> bool:
        """终止指定进程"""
        if process_id in self.running_processes:
            process_info = self.running_processes[process_id]
            process = process_info['process']
            try:
                process.terminate()
                time.sleep(0.5)
                if process.poll() is None:
                    process.kill()
                return True
            except Exception as e:
                logger.error(f"终止进程失败: {e}")
                return False
        return False
    
    def cleanup_finished_processes(self):
        """清理已完成的进程"""
        finished_processes = []
        for process_id, process_info in self.running_processes.items():
            if process_info['process'].poll() is not None:
                finished_processes.append(process_id)
        
        for process_id in finished_processes:
            self.remove_process(process_id)

class ExecuteCommandTool:
    """命令执行工具集"""
    
    def __init__(self):
        logger.debug("Initializing ExecuteCommandTool")
        # 先初始化必要的组件，再调用父类初始化
        # 启用安全检查，但使用宽松的黑名单（允许 rm/nc 等）
        self.security_manager = SecurityManager(False)
        self.process_manager = ProcessManager()
        # 默认脚本目录不应硬编码为 getcwd，应由调用方传入或回退到临时目录
        self.default_script_dir = None

    def _prepare_script_environment(self, workdir: Optional[str], process_id: str, extension: str, session_id: Optional[str] = None) -> Tuple[str, str]:
        """准备脚本执行环境：确定工作目录和脚本路径
        
        使用 sandbox_utils 统一处理沙箱和非沙箱环境。
        """
        from sagents.utils.sandbox import get_sandbox_workdir
        
        # 获取工作目录
        effective_workdir = get_sandbox_workdir(workdir, session_id)
        
        if not effective_workdir:
            effective_workdir = tempfile.mkdtemp(prefix=f"sage_scripts_{process_id}_")
        
        # 确保目录存在
        os.makedirs(effective_workdir, exist_ok=True)
        
        # 生成脚本路径
        script_name = f"script_{process_id}.{extension}"
        script_path = os.path.join(effective_workdir, script_name)
        
        return script_path, effective_workdir
    
    def _write_script_file(self, file_path: str, content: str, workdir: str = None, session_id: Optional[str] = None):
        """写入脚本文件"""
        
        # 写入文件
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
        except PermissionError:
            # 如果直接写入被拦截，尝试使用命令行写入
            logger.warning(f"直接写入文件被拦截，尝试使用命令行写入: {file_path}")
            if platform.system() == "Windows":
                 # Windows fallback: use type or echo (be careful with special chars)
                 # Better approach: retry with a small delay or different name if locked
                 # But here we assume permission error due to sandbox restrictions? 
                 # If it's a real permission error, echo won't help either usually.
                 pass
            else:
                import shlex
                escaped_content = shlex.quote(content)
                write_cmd = f"printf '%s' {escaped_content} > {file_path}"
                self._execute_shell_command_sync(write_cmd, workdir=workdir, timeout=10, background=False)

    def _log_shell_history(self, command: str, workdir: Optional[str], success: bool, return_code: Optional[int], session_id: Optional[str]):
        """记录 Shell 命令历史"""
        if not session_id:
            return
                
        try:
            from sagents.session_runtime import get_global_session_manager
            session_manager = get_global_session_manager()
            session = session_manager.get(session_id)
            if not session or not session.session_context:
                return
            session_context = session.session_context
            # 获取 host_path
            host_path = None
            if hasattr(session_context, 'agent_workspace_sandbox'):
                host_path = getattr(session_context.agent_workspace_sandbox.file_system, 'host_path', None)
            
            if not host_path:
                return
            
            # 写入历史
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            status = "SUCCESS" if success else "FAILED"
            rc_str = str(return_code) if return_code is not None else "N/A"
            log_entry = f"[{timestamp}] [{status}] [RC:{rc_str}] [WD:{workdir or 'CWD'}] {command}\n"
            
            history_file = os.path.join(host_path, ".shell_history")
            
            with open(history_file, "a", encoding="utf-8") as f:
                f.write(log_entry)
                
        except Exception as e:
            logger.warning(f"记录 Shell 历史失败: {e}")

    @tool(
        description_i18n={
            "zh": "在指定目录执行Shell命令，含安全检查与超时控制",
            "en": "Execute a shell command with safety checks and timeout",
            "pt": "Executar comando shell com verificações de segurança e timeout"
        },
        param_description_i18n={
            "command": {"zh": "待执行的Shell命令字符串", "en": "Shell command to execute", "pt": "Comando shell a executar"},
            "background": {"zh": "是否后台执行。为True时命令在后台运行并立即返回", "en": "Run in background. When True, command runs in background and returns immediately", "pt": "Executar em segundo plano"},
            "workdir": {"zh": "执行目录，默认当前目录", "en": "Working directory, defaults to current", "pt": "Diretório de trabalho, padrão atual"},
            "timeout": {"zh": "超时秒数，默认30", "en": "Timeout in seconds, default 30", "pt": "Tempo limite em segundos, padrão 30"},
            "env_vars": {"zh": "附加环境变量字典", "en": "Additional environment variables dict", "pt": "Dicionário de variáveis de ambiente adicionais"},
            "session_id": {"zh": "会话ID (可选, 自动注入, 无需填写)", "en": "Session ID (Optional, Auto-injected)", "pt": "ID da Sessão (Opcional)"},
        },
        return_data={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "stdout": {"type": "string"},
                "stderr": {"type": "string"},
                "return_code": {"type": "integer"},
                "execution_time": {"type": "number"},
                "is_background": {"type": "boolean", "description": "Whether the command was run in background"}
            },
            "required": ["success"]
        }
    )
    async def execute_shell_command(self, command: str, background: bool,
                                    workdir: Optional[str] = None,
                                    timeout: int = 30,
                                    env_vars: Optional[Dict[str, str]] = None,
                                    session_id: Optional[str] = None,
                                    ) -> Dict[str, Any]:
        return await asyncio.to_thread(
            self._execute_shell_command_sync,
            command,
            background,
            workdir,
            timeout,
            env_vars,
            session_id
        )

    def _execute_shell_command_sync(self, command: str, background: bool,
                                    workdir: Optional[str] = None,
                                    timeout: int = 30,
                                    env_vars: Optional[Dict[str, str]] = None,
                                    session_id: Optional[str] = None,
                                    ) -> Dict[str, Any]:
        """在指定目录执行Shell命令
        
        使用 sandbox_utils 统一处理沙箱路径映射，兼容有沙箱和没有沙箱的环境。
        """
        
        start_time = time.time()
        process_id = self.process_manager.generate_process_id()
        logger.info(f"🖥️ execute_shell_command开始执行 [{process_id}] - command: {command[:100]}{'...' if len(command) > 100 else ''}")
        
        # 获取实际工作目录
        # 优先使用用户传入的 workdir，否则使用 sandbox.file_system.host_path（主机路径）
        actual_workdir = workdir
        logger.debug(f"[execute_shell_command] 原始 workdir: {workdir}, session_id: {session_id}")
        if actual_workdir is None and session_id:
            from sagents.session_runtime import get_global_session_manager
            session_manager = get_global_session_manager()
            session = session_manager.get(session_id)
            if session and session.session_context:
                session_context = session.session_context
                # 优先使用 sandbox.file_system.host_path（这是实际的主机路径）
                if hasattr(session_context, 'agent_workspace_sandbox') and session_context.agent_workspace_sandbox:
                    if hasattr(session_context.agent_workspace_sandbox, 'file_system') and session_context.agent_workspace_sandbox.file_system:
                        actual_workdir = session_context.agent_workspace_sandbox.file_system.host_path  
                        logger.debug(f"[execute_shell_command] 使用 agent_workspace_sandbox.file_system.host_path: {actual_workdir}")
                    else:
                        # 如果没有 file_system，使用 host_workspace
                        actual_workdir = session_context.agent_workspace_sandbox.host_workspace
                        logger.debug(f"[execute_shell_command] 使用 agent_workspace_sandbox.host_workspace: {actual_workdir}")
                # 如果没有 sandbox，再尝试 agent_workspace_sandbox
                elif hasattr(session_context, 'agent_workspace_sandbox'):
                    agent_ws = session_context.agent_workspace_sandbox.file_system
                    if isinstance(agent_ws, str):
                        actual_workdir = agent_ws
                    elif hasattr(agent_ws, 'host_path'):
                        actual_workdir = agent_ws.host_path
                    logger.debug(f"[execute_shell_command] 使用 agent_workspace_sandbox: {actual_workdir}")
        logger.info(f"[execute_shell_command] 最终 actual_workdir: {actual_workdir}")
        
        try:
            logger.debug(f"[execute_shell_command] 开始安全检查")
            # 安全检查
            is_safe, reason = self.security_manager.is_command_safe(command)
            if not is_safe:
                logger.warning(f"[execute_shell_command] 安全检查失败: {reason}")
                return {
                    "success": False,
                    "error": f"安全检查失败: {reason}",
                    "command": command,
                    "process_id": process_id,
                    "execution_time": time.time() - start_time
                }
            logger.debug(f"[execute_shell_command] 安全检查通过")
            
            # 验证工作目录
            logger.debug(f"[execute_shell_command] 验证工作目录: {actual_workdir}")
            if actual_workdir and not os.path.exists(actual_workdir):
                logger.error(f"[execute_shell_command] 工作目录不存在: {actual_workdir}")
                return {
                    "success": False,
                    "error": f"工作目录不存在: {workdir}",
                    "process_id": process_id,
                    "execution_time": time.time() - start_time
                }
            logger.debug(f"[execute_shell_command] 工作目录验证通过")
            
            # 准备环境变量
            logger.debug(f"[execute_shell_command] 准备环境变量")
            env = os.environ.copy()

            # 自动设置沙箱 Python 环境变量（如果存在）
            if session_id:
                from sagents.utils.sandbox import get_sandbox_python_path
                sandbox_python = get_sandbox_python_path(session_id)
                if sandbox_python:
                    env['SANDBOX_PYTHON_PATH'] = sandbox_python
                    # 将沙箱 Python 的目录添加到 PATH 最前面
                    sandbox_bin = os.path.dirname(sandbox_python)
                    current_path = env.get("PATH", "")
                    if sandbox_bin not in current_path:
                        env["PATH"] = f"{sandbox_bin}{os.pathsep}{current_path}"
                        logger.debug(f"[execute_shell_command] 添加沙箱 Python 到 PATH: {sandbox_bin}")

            # 在 PyInstaller 打包环境中，需要显式添加全局 npm 路径
            from sagents.utils.common_utils import is_pyinstaller_frozen
            if is_pyinstaller_frozen():
                # 添加常见的全局 npm 路径
                global_npm_paths = []
                home_dir = os.path.expanduser("~")

                # Sage客户端 预设的 node_modules .bin 路径（优先级最高）
                sage_bin_path = os.path.join(home_dir, ".sage", ".sage_node_env", "node_modules", ".bin")

                if platform.system() == "Darwin":  # macOS
                    global_npm_paths = [
                        sage_bin_path,
                        "/usr/local/bin",
                        "/opt/homebrew/bin",
                        os.path.join(home_dir, ".npm-global/bin"),
                        os.path.join(home_dir, ".nvm/versions/node/*/bin"),

                    ]
                elif platform.system() == "Windows":
                    global_npm_paths = [
                        sage_bin_path,
                        os.path.join(home_dir, "AppData/Roaming/npm"),
                        "C:/Program Files/nodejs",
                    ]
                else:  # Linux
                    global_npm_paths = [
                        sage_bin_path,
                        "/usr/local/bin",
                        "/usr/bin",
                        os.path.join(home_dir, ".npm-global/bin"),
                        os.path.join(home_dir, ".nvm/versions/node/*/bin"),
                    ]

                current_path = env.get("PATH", "")
                # 检查并添加存在的路径
                for npm_path in global_npm_paths:
                    if "*" in npm_path:
                        # 处理通配符路径（如 nvm）
                        import glob
                        matching_paths = glob.glob(npm_path)
                        for matched_path in matching_paths:
                            if os.path.exists(matched_path) and matched_path not in current_path:
                                current_path = f"{matched_path}{os.pathsep}{current_path}"
                                logger.debug(f"[execute_shell_command] 添加全局 npm 路径: {matched_path}")
                    elif os.path.exists(npm_path) and npm_path not in current_path:
                        current_path = f"{npm_path}{os.pathsep}{current_path}"
                        logger.debug(f"[execute_shell_command] 添加全局 npm 路径: {npm_path}")

                env["PATH"] = current_path

            if env_vars:
                env.update(env_vars)
                logger.debug(f"[execute_shell_command] 更新环境变量: {env_vars.keys()}")
            
            # 自动修复权限
            logger.debug(f"[execute_shell_command] 检查执行权限")
            self._fix_execute_permission(command, actual_workdir)
            
            # 处理 npm/npx 命令，添加 --prefix 指向预设的 node_modules 目录
            command = self._prepare_npm_command(command)
            
            # 执行命令
            exec_start_time = time.time()
            logger.debug(f"[execute_shell_command] 准备执行命令, background={background}")
            
            if background:
                logger.debug(f"[execute_shell_command] 调用 _execute_background")
                result = self._execute_background(command, actual_workdir, env, process_id)
            else:
                logger.debug(f"[execute_shell_command] 调用 _execute_normal")
                result = self._execute_normal(command, actual_workdir, env, timeout, process_id)
            
            result["execution_time"] = time.time() - exec_start_time
            logger.info(f"✅ [execute_shell_command] 执行完成 [{process_id}] - success: {result.get('success')}, cost: {result.get('execution_time', 0):.2f}s")
            return result
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "command": command,
                "execution_time": time.time() - start_time,
                "process_id": process_id
            }
    
    def _fix_execute_permission(self, command: str, workdir: Optional[str]):
        """自动修复执行权限"""
        try:
            cmd_parts = command.strip().split()
            if not cmd_parts:
                return
            
            exe_cmd = cmd_parts[0]
            current_cwd = workdir or os.getcwd()
            
            if os.path.isabs(exe_cmd):
                target_file = exe_cmd
            else:
                target_file = os.path.join(current_cwd, exe_cmd)
            
            if target_file and os.path.exists(target_file) and os.path.isfile(target_file):
                if not os.access(target_file, os.X_OK):
                    logger.info(f"🔧 [AutoFix] 修复执行权限: {target_file}")
                    st = os.stat(target_file)
                    os.chmod(target_file, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except Exception:
            pass
    
    def _prepare_npm_command(self, command: str) -> str:
        """处理 npm/npx 命令，如果 SAGE_NODE_MODULES_DIR 环境变量存在，则添加 --prefix 参数
        
        Args:
            command: 原始命令字符串
            
        Returns:
            处理后的命令字符串
        """
        import re
        
        sage_node_modules = os.environ.get("SAGE_NODE_MODULES_DIR")
        if not sage_node_modules:
            return command
        
        # 检查是否是 npm 或 npx 命令
        cmd_trimmed = command.strip()
        
        # 匹配 npm 或 npx 命令（考虑 sudo、nohup 等前缀）
        npm_pattern = r'^(\s*(?:sudo|nohup|time)?\s*)(npm|npx)(\s+)'
        match = re.match(npm_pattern, cmd_trimmed)
        
        if match:
            prefix = match.group(1)  # sudo/nohup 等前缀
            cmd_type = match.group(2)  # npm 或 npx
            space = match.group(3)
            rest = cmd_trimmed[match.end():]
            
            # 检查是否已经有 --prefix 参数
            if '--prefix' in rest:
                return command
            
            # 构建新命令，添加 --prefix 参数
            # npm 命令：npm --prefix <dir> <cmd>
            # npx 命令：npx --prefix <dir> <cmd>
            new_command = f"{prefix}{cmd_type} --prefix {sage_node_modules}{space}{rest}"
            logger.info(f"📝 [NPM] 添加 --prefix 参数: {sage_node_modules}")
            return new_command
        
        return command
    
    def _execute_background(self, command: str, workdir: Optional[str], env: Dict, process_id: str) -> Dict[str, Any]:
        """後台執行"""
        logger.info(f"[_execute_background] 開始, workdir={workdir}")
        log_dir = os.path.join(workdir or os.getcwd(), ".sandbox_logs")
        logger.info(f"[_execute_background] log_dir={log_dir}")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f"bg_{process_id}.log")
        logger.info(f"[_execute_background] log_file={log_file}")
        
        if platform.system() == "Windows":
            logger.info(f"[_execute_background] Windows 模式, cmd={command}")
            
            # Windows: use CREATE_NO_WINDOW and redirect stdout/stderr to log file
            with open(log_file, "w") as f_log:
                process = subprocess.Popen(
                    command,
                    cwd=workdir,
                    shell=True,
                    env=env,
                    stdout=f_log,
                    stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
                )
        else:
            nohup_cmd = f"nohup sh -c '{command}' > {log_file} 2>&1 &"
            logger.info(f"[_execute_background] Unix 模式, nohup_cmd={nohup_cmd}")
            
            logger.info(f"[_execute_background] 啟動 subprocess, cwd={workdir}")
            process = subprocess.Popen(
                nohup_cmd,
                cwd=workdir,
                shell=True,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
        
        logger.info(f"[_execute_background] subprocess 啟動完成, pid={process.pid}")
        
        return {
            "success": True,
            "output": f"[后台任务已启动]\n命令: {command}\n进程ID: {process.pid}\n日志文件: {log_file}",
            "process_id": process_id,
            "is_background": True,
            "log_file": log_file,
        }
    
    def _execute_normal(self, command: str, workdir: Optional[str], env: Dict, timeout: int, process_id: str) -> Dict[str, Any]:
        """普通执行 - 使用临时文件捕获输出，避免 PIPE 缓冲区限制，限制输出不超过10K字符"""
        import tempfile

        MAX_OUTPUT_LENGTH = 10000  # 最大输出长度限制

        # 创建临时文件用于捕获输出
        stdout_fd, stdout_path = tempfile.mkstemp(prefix=f"stdout_{process_id}_", suffix=".log")
        stderr_fd, stderr_path = tempfile.mkstemp(prefix=f"stderr_{process_id}_", suffix=".log")

        # 设置 Python 无缓冲模式，确保输出及时写入文件
        env['PYTHONUNBUFFERED'] = '1'

        try:
            process = subprocess.Popen(
                command,
                cwd=workdir,
                shell=True,
                env=env,
                stdout=stdout_fd,
                stderr=stderr_fd,
                preexec_fn=os.setsid if platform.system() != "Windows" else None
            )

            self.process_manager.add_process(process_id, process)

            # 关闭文件描述符，确保子进程可以正常写入
            os.close(stdout_fd)
            os.close(stderr_fd)
            stdout_fd = -1  # 标记为已关闭
            stderr_fd = -1

            try:
                process.wait(timeout=timeout)
                return_code = process.returncode

                # 读取输出文件
                try:
                    with open(stdout_path, 'r', encoding='utf-8', errors='replace') as f:
                        stdout = f.read()
                except Exception as e:
                    logger.warning(f"读取 stdout 文件失败: {e}")
                    stdout = ""

                try:
                    with open(stderr_path, 'r', encoding='utf-8', errors='replace') as f:
                        stderr = f.read()
                except Exception as e:
                    logger.warning(f"读取 stderr 文件失败: {e}")
                    stderr = ""

                # 检查输出是否超过限制
                truncated = False
                if len(stdout) > MAX_OUTPUT_LENGTH:
                    stdout = stdout[:MAX_OUTPUT_LENGTH] + "\n... [输出已截断，超过10K字符限制，请调整代码减少输出]"
                    truncated = True
                if len(stderr) > MAX_OUTPUT_LENGTH:
                    stderr = stderr[:MAX_OUTPUT_LENGTH] + "\n... [错误输出已截断，超过10K字符限制，请调整代码减少输出]"
                    truncated = True

                result = {
                    "success": return_code == 0,
                    "stdout": stdout,
                    "stderr": stderr,
                    "return_code": return_code,
                }
                if not result["success"]:
                    result["command"] = command
                if truncated:
                    result["output_truncated"] = True
                    result["output_hint"] = "输出超过10K字符限制，已截断显示。如需完整输出，请调整代码将结果写入文件或减少输出量。"

                return result

            except subprocess.TimeoutExpired:
                process.kill()
                return {
                    "success": False,
                    "error": f"命令执行超时 (>{timeout}秒)",
                    "command": command,
                    "timeout": timeout,
                }
            finally:
                self.process_manager.remove_process(process_id)
        finally:
            # 关闭文件描述符（如果还未关闭）
            try:
                if stdout_fd >= 0:
                    os.close(stdout_fd)
            except OSError:
                pass
            try:
                if stderr_fd >= 0:
                    os.close(stderr_fd)
            except OSError:
                pass
            # 删除临时文件
            try:
                os.unlink(stdout_path)
                os.unlink(stderr_path)
            except OSError:
                pass

    # @tool(
    #     description_i18n={
    #         "zh": "在临时文件中运行Python代码，可选依赖安装",
    #         "en": "Run Python code in a temp file, optionally install deps",
    #         "pt": "Execute código Python em arquivo temporário, opcionalmente instale dependências"
    #     },
    #     param_description_i18n={
    #         "code": {"zh": "Python代码文本", "en": "Python code text", "pt": "Texto de código Python"},
    #         "workdir": {"zh": "运行目录，默认临时目录", "en": "Working directory, defaults to temp", "pt": "Diretório de execução, padrão temporário"},
    #         "timeout": {"zh": "超时秒数，默认30", "en": "Timeout in seconds, default 30", "pt": "Tempo limite em segundos, padrão 30"},
    #         "requirement_list": {"zh": "需要安装的包名称列表", "en": "List of packages to install", "pt": "Lista de pacotes para instalar"},
    #         "session_id": {"zh": "会话ID (可选, 自动注入, 无需填写)", "en": "Session ID (Optional, Auto-injected)", "pt": "ID da Sessão (Opcional)"}
    #     }
    # )
    async def execute_python_code(self, code: str, requirement_list: Optional[Union[List[str], str]] = None,
                                  workdir: Optional[str] = None, timeout: int = 60,
                                  session_id: Optional[str] = None) -> Dict[str, Any]:
        return await asyncio.to_thread(
            self._execute_python_code_sync,
            code,
            requirement_list,
            workdir,
            timeout,
            session_id
        )

    def _execute_python_code_sync(self, code: str, requirement_list: Optional[Union[List[str], str]] = None,
                                  workdir: Optional[str] = None, timeout: int = 60,
                                  session_id: Optional[str] = None) -> Dict[str, Any]:
        """在临时文件中运行Python代码，可选依赖安装

        Args:
            code (str): Python代码字符串
            requirement_list (List[str] | str): 依赖包列表
            workdir (str): 工作目录（可选）
            timeout (int): 超时时间（秒）
            session_id (str): 会话ID（可选，由ToolManager注入）

        Returns:
            Dict[str, Any]: 执行结果
        """
        start_time = time.time()
        process_id = self.process_manager.generate_process_id()
        logger.info(f"🐍 execute_python_code开始执行 [{process_id}] - 代码长度: {len(code)} 字符")
        logger.info(f"📁 工作目录: {workdir or '临时目录'}, 超时: {timeout}秒")
        
        temp_file = None
        try:
            # 准备脚本环境：确定路径并确保目录存在
            # 如果未指定workdir，将使用默认脚本目录进行备份和执行
            temp_file, workdir = self._prepare_script_environment(workdir, process_id, "py", session_id)
            
            # 写入代码文件
            self._write_script_file(temp_file, code, workdir, session_id)
            
            # 参数类型校验与依赖处理
            # 优先使用沙箱的 Python
            from sagents.utils.sandbox import get_sandbox_python_path
            python_path = get_sandbox_python_path(session_id)

            if not python_path:
                # 使用 get_system_python_path 来处理 PyInstaller 打包环境
                python_path = get_system_python_path()
                if not python_path:
                    python_path = shutil.which("python") or shutil.which("python3")

            if not python_path:
                raise RuntimeError("未找到Python解释器，请确保Python已正确安装")
            parsed_requirements: List[str] = []
            already_available: List[str] = []
            newly_installed: List[str] = []
            install_failed: List[Dict[str, Any]] = []


            if requirement_list is not None:
                requirement_list = ensure_list(requirement_list)

            if requirement_list:
                parsed_requirements = [str(p).strip() for p in requirement_list if p]
                if parsed_requirements:
                    logger.info(f"📦 依赖包处理: {parsed_requirements}")
                    for package in parsed_requirements:
                        # 提取用于导入的模块名（去掉版本限定）
                        pure_name = package.split("[")[0]
                        for sep in ["==", ">=", "<=", ">", "<", "~=", "!="]:
                            if sep in pure_name:
                                pure_name = pure_name.split(sep)[0]
                                break
                        pure_name = pure_name.strip()
                        # 始终尝试安装，由 pip 处理是否已满足
                        # module_name = pure_name
                        # 移除本地 importlib 检查，因为这检查的是宿主环境而非沙箱环境
                        # 且 pip install 本身是幂等的，如果已安装会跳过
                        install_cmd = f"{python_path} -m pip install {package} -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn"
                        install_result = self._execute_shell_command_sync(
                            install_cmd,
                            workdir=workdir,
                            timeout=120,
                            background=False
                        )
                        if install_result.get("success"):
                            newly_installed.append(package)
                        else:
                            install_failed.append({
                                "package": package,
                                "return_code": install_result.get("return_code"),
                                "stderr": install_result.get("stderr", ""),
                                "stdout": install_result.get("stdout", "")
                            })
            
            # 执行Python代码
            exec_start_time = time.time()
            logger.info(f"🚀 开始执行Python代码 [{process_id}]")
            
            python_cmd = f"{python_path} {temp_file}"
            result = self._execute_shell_command_sync(
                python_cmd,
                workdir=workdir,
                timeout=timeout,
                background=False
            )
            
            execution_time = time.time() - exec_start_time
            total_time = time.time() - start_time
            
            if result["success"]:
                logger.info(f"✅ Python代码执行成功 [{process_id}] - 执行耗时: {execution_time:.2f}秒")
            else:
                logger.error(f"❌ Python代码执行失败 [{process_id}] - 返回码: {result.get('return_code', 'unknown')}")
            
            # 添加额外信息（注意：成功执行时不返回安装失败信息）
            result.update({
                # "temp_file": temp_file,
                "requirements": parsed_requirements or requirement_list,
                "already_available": already_available if requirement_list else None,
                "installed": newly_installed if requirement_list else None,
                # 不在此处加入 install_failed，改为在失败时按需加入
                "total_execution_time": total_time,
                # "process_id": process_id
            })
            # 如果执行失败，尽可能提供详细的错误trace
            if not result.get("success"):
                stderr_text = result.get("stderr") or ""
                if stderr_text:
                    # 直接返回stderr作为错误trace，便于端到端查看
                    result["error_traceback"] = stderr_text
                # 执行失败时才返回依赖安装失败信息，便于定位问题
                if requirement_list:
                    result["install_failed"] = install_failed or None
            # 如果执行失败且存在依赖安装失败，补充原因说明
            if not result.get("success") and install_failed:
                result["error_hint"] = "检测到部分依赖安装失败，当前环境可能无法安装所需依赖包"
                result["install_error"] = "\n".join(
                    [f"{i['package']}: {str(i.get('stderr') or i.get('stdout') or '')}".strip() for i in install_failed]
                )

            return result
            
        except Exception as e:
            error_time = time.time() - start_time
            logger.error(f"💥 Python代码执行异常 [{process_id}] - 错误: {str(e)}")
            logger.error(traceback.format_exc())
            
            return {
                "success": False,
                "error": str(e),
                "error_traceback": traceback.format_exc(),
                "code": code,
                "execution_time": error_time,
                "process_id": process_id
            }
        finally:
            # 脚本文件保留用于备份，不自动删除
            pass

    # @tool(
    #     description_i18n={
    #         "zh": "在临时文件中运行JavaScript代码，可选依赖安装",
    #         "en": "Run JavaScript code in a temp file, optionally install deps",
    #         "pt": "Execute código JavaScript em arquivo temporário, opcionalmente instale dependências"
    #     },
    #     param_description_i18n={
    #         "code": {"zh": "JavaScript代码文本", "en": "JavaScript code text", "pt": "Texto de código JavaScript"},
    #         "workdir": {"zh": "运行目录，默认临时目录", "en": "Working directory, defaults to temp", "pt": "Diretório de execução, padrão temporário"},
    #         "timeout": {"zh": "超时秒数，默认30", "en": "Timeout in seconds, default 30", "pt": "Tempo limite em segundos, padrão 30"},
    #         "npm_packages": {"zh": "需要安装的npm包列表", "en": "List of npm packages to install", "pt": "Lista de pacotes npm para instalar"},
    #         "session_id": {"zh": "会话ID (可选, 自动注入, 无需填写)", "en": "Session ID (Optional, Auto-injected)", "pt": "ID da Sessão (Opcional)"}
    #     }
    # )
    def execute_javascript_code(self, code: str, npm_packages: Optional[Union[List[str], str]] = None, 
                              workdir: Optional[str] = None, timeout: int = 60,
                              session_id: Optional[str] = None) -> Dict[str, Any]:
        """在临时文件中运行JavaScript代码，可选依赖安装
        
        使用 sandbox_utils 统一处理沙箱和非沙箱环境。
        """
        from sagents.utils.sandbox import get_sandbox_host_path
        
        start_time = time.time()
        process_id = self.process_manager.generate_process_id()
        logger.info(f"📜 execute_javascript_code开始执行 [{process_id}]")
        
        try:
            # 检查node环境
            # 在 PyInstaller 打包环境中，需要显式添加全局 npm 路径到 PATH
            from sagents.utils.common_utils import is_pyinstaller_frozen
            search_env = os.environ.copy()

            if is_pyinstaller_frozen():
                # 添加常见的全局 npm 路径到 PATH
                global_npm_paths = []
                home_dir = os.path.expanduser("~")

                # Sage客户端 预设的 node_modules .bin 路径（优先级最高）
                sage_bin_path = os.path.join(home_dir, ".sage", ".sage_node_env", "node_modules", ".bin")

                if platform.system() == "Darwin":  # macOS
                    global_npm_paths = [
                        sage_bin_path,
                        "/usr/local/bin",
                        "/opt/homebrew/bin",
                        os.path.join(home_dir, ".npm-global/bin"),
                    ]
                elif platform.system() == "Windows":
                    global_npm_paths = [
                        sage_bin_path,
                        os.path.join(home_dir, "AppData/Roaming/npm"),
                        "C:/Program Files/nodejs",
                    ]
                else:  # Linux
                    global_npm_paths = [
                        sage_bin_path,
                        "/usr/local/bin",
                        "/usr/bin",
                        os.path.join(home_dir, ".npm-global/bin"),
                    ]

                current_path = search_env.get("PATH", "")
                for npm_path in global_npm_paths:
                    if os.path.exists(npm_path) and npm_path not in current_path:
                        current_path = f"{npm_path}{os.pathsep}{current_path}"
                search_env["PATH"] = current_path

            node_path = shutil.which("node", path=search_env.get("PATH"))
            if not node_path:
                raise RuntimeError("未找到Node.js环境")
            
            # 准备脚本环境
            temp_file, workdir = self._prepare_script_environment(workdir, process_id, "js", session_id)
            
            # 写入代码文件
            self._write_script_file(temp_file, code, workdir, session_id)
            
            newly_installed = []
            
            # 处理npm包依赖
            if npm_packages:
                npm_packages = ensure_list(npm_packages)
                parsed_packages = [str(p).strip() for p in npm_packages if p]
                
                if parsed_packages:
                    # 获取 host_path 检查 package.json
                    host_workdir = get_sandbox_host_path(session_id) or workdir
                    pkg_json_path = os.path.join(host_workdir, "package.json")
                    
                    if not os.path.exists(pkg_json_path):
                        self._execute_shell_command_sync("npm init -y", workdir=workdir, timeout=10, background=False)
                    
                    # 安装依赖
                    npm_registry = "https://registry.npmmirror.com/"
                    npm_cmd = f"npm install --registry={npm_registry} {' '.join(parsed_packages)}"
                    install_result = self._execute_shell_command_sync(npm_cmd, workdir=workdir, timeout=120, background=False)
                    
                    if install_result.get("success"):
                        newly_installed = parsed_packages
            
            # 执行JS代码
            exec_start_time = time.time()
            node_cmd = f"{node_path} {temp_file}"
            result = self._execute_shell_command_sync(node_cmd, workdir=workdir, timeout=timeout, background=False)
            
            result.update({
                "npm_packages": npm_packages,
                "installed": newly_installed if npm_packages else None,
                "execution_time": time.time() - exec_start_time,
                "total_execution_time": time.time() - start_time
            })
            
            return result

        except Exception as e:
            logger.error(f"💥 JavaScript代码执行异常: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "error_traceback": traceback.format_exc(),
                "code": code,
                "execution_time": time.time() - start_time,
                "process_id": process_id
            }

    # @tool(
    #     description_i18n={
    #         "zh": "检查系统命令是否可用及其路径",
    #         "en": "Check whether system commands are available and their paths",
    #         "pt": "Verificar se comandos do sistema estão disponíveis e seus caminhos"
    #     },
    #     param_description_i18n={
    #         "commands": {"zh": "待检查的命令名列表", "en": "List of command names to check", "pt": "Lista de nomes de comando para verificar"}
    #     },
    #     return_data={
    #         "type": "object",
    #         "properties": {
    #             "available": {"type": "boolean"},
    #             "path": {"type": "string"},
    #             "version": {"type": "string"},
    #             "error": {"type": "string"}
    #         },
    #         "required": ["available"]
    #     }
    # )
    def check_command_availability(self, commands: List[str]) -> Dict[str, Any]:
        """检查系统中命令的可用性

        Args:
            commands (list): 要检查的命令列表

        Returns:
            Dict[str, Any]: 包含检查结果的字典
        """
        start_time = time.time()
        check_id = hashlib.md5(f"check_{time.time()}".encode()).hexdigest()[:8]
        logger.info(f"🔍 check_command_availability开始执行 [{check_id}] - 检查命令数: {len(commands)}")
        
        try:
            results = {}

            # 在 PyInstaller 打包环境中，需要显式添加全局 npm 路径到 PATH
            from sagents.utils.common_utils import is_pyinstaller_frozen
            check_env = os.environ.copy()

            if is_pyinstaller_frozen():
                # 添加常见的全局 npm 路径到 PATH
                global_npm_paths = []
                home_dir = os.path.expanduser("~")
                # Sage客户端 预设的 node_modules .bin 路径（优先级最高）
                sage_bin_path = os.path.join(home_dir, ".sage", ".sage_node_env", "node_modules", ".bin")
                
                if platform.system() == "Darwin":  # macOS
                    global_npm_paths = [
                        sage_bin_path,
                        "/usr/local/bin",
                        "/opt/homebrew/bin",
                        os.path.join(home_dir, ".npm-global/bin"),
                    ]
                elif platform.system() == "Windows":
                    global_npm_paths = [
                        sage_bin_path,
                        os.path.join(home_dir, "AppData/Roaming/npm"),
                        "C:/Program Files/nodejs",
                    ]
                else:  # Linux
                    global_npm_paths = [
                        sage_bin_path,
                        "/usr/local/bin",
                        "/usr/bin",
                        os.path.join(home_dir, ".npm-global/bin"),
                    ]

                current_path = check_env.get("PATH", "")
                for npm_path in global_npm_paths:
                    if os.path.exists(npm_path) and npm_path not in current_path:
                        current_path = f"{npm_path}{os.pathsep}{current_path}"
                check_env["PATH"] = current_path
  
            for command in commands:
                logger.debug(f"🔍 检查命令: {command}")

                # 使用 which/where 命令检查
                if platform.system().lower() == "windows":
                    check_cmd = f"where {command}"
                else:
                    check_cmd = f"which {command}"

                try:
                    result = subprocess.run(
                        check_cmd,
                        shell=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=5,
                        env=check_env
                    )
                    
                    if result.returncode == 0:
                        command_path = result.stdout.strip()
                        logger.debug(f"✅ 命令可用: {command} -> {command_path}")
                        results[command] = {
                            "available": True,
                            "path": command_path,
                            "version": None
                        }
                    else:
                        logger.debug(f"❌ 命令不可用: {command}")
                        results[command] = {
                            "available": False,
                            "path": None,
                            "error": result.stderr.strip()
                        }
                        
                except subprocess.TimeoutExpired:
                    logger.warning(f"⏰ 命令检查超时: {command}")
                    results[command] = {
                        "available": False,
                        "path": None,
                        "error": "检查超时"
                    }
                except Exception as e:
                    logger.warning(f"💥 命令检查异常: {command} - {str(e)}")
                    results[command] = {
                        "available": False,
                        "path": None,
                        "error": str(e)
                    }
            
            available_count = sum(1 for result in results.values() if result["available"])
            total_time = time.time() - start_time
            
            logger.info(f"✅ 命令可用性检查完成 [{check_id}] - 可用: {available_count}/{len(commands)}, 耗时: {total_time:.2f}秒")
            
            return {
                "success": True,
                "results": results,
                "summary": {
                    "total_commands": len(commands),
                    "available_commands": available_count,
                    "unavailable_commands": len(commands) - available_count
                },
                "execution_time": total_time,
                "check_id": check_id
            }
            
        except Exception as e:
            error_time = time.time() - start_time
            logger.error(f"💥 命令可用性检查异常 [{check_id}] - 错误: {str(e)}")
            logger.error(traceback.format_exc())
            
            return {
                "success": False,
                "error": str(e),
                "execution_time": error_time,
                "check_id": check_id
            }

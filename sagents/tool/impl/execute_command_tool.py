#!/usr/bin/env python3
"""
Execute Command Tool

基于 Tool 注解实现的命令执行工具，提供与 mcp_servers/execute_command/execute_command.py 相同的功能。
具备完善的安全机制和错误处理。
"""

import os
import sys
import subprocess
import tempfile
import time
import platform
import shutil
import json
import hashlib
import traceback
from typing import Dict, List, Any, Optional, Tuple, Union

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
        
        Args:
            workdir: 用户指定的工作目录。强烈建议由 Agent 传入 Session 相关的 workspace 路径。
            process_id: 进程ID，用于生成文件名
            extension: 脚本扩展名 (如 .py, .js)
            session_id: 会话ID，用于查找默认的 Session Workspace
            
        Returns:
            Tuple[str, str]: (脚本绝对路径, 有效工作目录)
        """
        effective_workdir = None

        if workdir:
            # 用户指定了目录，使用该目录
            effective_workdir = os.path.abspath(workdir)
        elif session_id:
            # 尝试通过 session_id 获取 Session Workspace
            try:
                # 避免循环导入
                from sagents.context.session_context import get_session_context
                session_context = get_session_context(session_id)
                if session_context and hasattr(session_context, 'agent_workspace'):
                    # agent_workspace 是 SandboxFileSystem，host_path 是宿主机路径
                    host_path = getattr(session_context.agent_workspace, 'host_path', None)
                    if host_path:
                        # 默认放在 agent_workspace/scripts 下
                        effective_workdir = os.path.join(host_path, "scripts")
                        logger.debug(f"通过 session_id {session_id} 定位到工作目录: {effective_workdir}")
            except ImportError:
                logger.warning("无法导入 get_session_context，跳过 Session 路径解析")
            except Exception as e:
                logger.warning(f"解析 Session Workspace 失败: {e}")

        if not effective_workdir:
            # 未指定目录且无法解析 Session 路径，为了避免污染项目根目录，回退到系统临时目录
            # 注意：这意味着脚本文件可能不会持久化保留在 Session 目录下
            effective_workdir = tempfile.mkdtemp(prefix=f"sage_agent_scripts_{process_id}_")
            
        # 确保目录存在
        if not os.path.exists(effective_workdir):
            try:
                os.makedirs(effective_workdir, exist_ok=True)
            except Exception as e:
                logger.warning(f"创建目录失败 {effective_workdir}: {e}")
                # 如果创建失败（可能是权限问题），回退到临时目录
                effective_workdir = tempfile.mkdtemp(prefix="agent_scripts_")
                
        # 生成脚本路径
        script_name = f"script_{process_id}.{extension}"
        script_path = os.path.join(effective_workdir, script_name)
        
        return script_path, effective_workdir

    def _write_script_file(self, file_path: str, content: str, workdir: str = None):
        """写入脚本文件，包含沙箱权限处理"""
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
        except PermissionError:
            # 如果直接写入被拦截，尝试使用命令行写入
            logger.warning(f"直接写入文件被拦截，尝试使用命令行写入: {file_path}")
            import shlex
            escaped_content = shlex.quote(content)
            # 使用 printf 写入
            write_cmd = f"printf '%s' {escaped_content} > {file_path}"
            self.execute_shell_command(write_cmd, workdir=workdir, timeout=10)

    def _log_shell_history(self, command: str, workdir: Optional[str], success: bool, return_code: Optional[int], session_id: Optional[str]):
        """记录 Shell 命令历史"""
        if not session_id:
            return

        try:
            # 避免循环导入
            from sagents.context.session_context import get_session_context
            session_context = get_session_context(session_id)
            if not session_context or not hasattr(session_context, 'agent_workspace'):
                return

            host_path = getattr(session_context.agent_workspace, 'host_path', None)
            if not host_path:
                return

            history_file = os.path.join(host_path, ".shell_history")
            
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            status = "SUCCESS" if success else "FAILED"
            rc_str = str(return_code) if return_code is not None else "N/A"
            
            log_entry = f"[{timestamp}] [{status}] [RC:{rc_str}] [WD:{workdir or 'CWD'}] {command}\n"
            
            # 使用 append 模式写入，简单文件锁机制在单 Agent 场景下通常不需要，多线程可能需要注意但此处为 Tool 调用
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
            "workdir": {"zh": "执行目录，默认当前目录", "en": "Working directory, defaults to current", "pt": "Diretório de trabalho, padrão atual"},
            "timeout": {"zh": "超时秒数，默认30", "en": "Timeout in seconds, default 30", "pt": "Tempo limite em segundos, padrão 30"},
            "env_vars": {"zh": "附加环境变量字典", "en": "Additional environment variables dict", "pt": "Dicionário de variáveis de ambiente adicionais"},
            "session_id": {"zh": "会话ID (可选, 自动注入, 无需填写)", "en": "Session ID (Optional, Auto-injected)", "pt": "ID da Sessão (Opcional)"}
        },
        return_data={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "stdout": {"type": "string"},
                "stderr": {"type": "string"},
                "return_code": {"type": "integer"},
                "execution_time": {"type": "number"}
            },
            "required": ["success"]
        }
    )
    def execute_shell_command(self, command: str, workdir: Optional[str] = None, 
                             timeout: int = 30, env_vars: Optional[Dict[str, str]] = None,
                             session_id: Optional[str] = None) -> Dict[str, Any]:
        """在指定目录执行Shell命令，后台执行请通过command 进行设置
        
        Args:
            command (str): 要执行的Shell命令
            workdir (str): 命令执行的工作目录（可选）
            timeout (int): 超时时间，默认30秒
            env_vars (dict): 自定义环境变量（可选）
            session_id (str): 会话ID（可选，由ToolManager注入）

        Returns:
            Dict[str, Any]: 包含执行结果的字典
        """
        start_time = time.time()
        process_id = self.process_manager.generate_process_id()
        logger.info(f"🖥️ execute_shell_command开始执行 [{process_id}] - command: {command[:100]}{'...' if len(command) > 100 else ''}")
        logger.info(f"📁 工作目录: {workdir or '当前目录'}, 超时: {timeout}秒")
        
        try:
            # 安全检查
            is_safe, reason = self.security_manager.is_command_safe(command)
            if not is_safe:
                error_time = time.time() - start_time
                logger.error(f"❌ 安全检查失败 [{process_id}] - 原因: {reason}, 耗时: {error_time:.2f}秒")
                return {
                    "success": False,
                    "error": f"安全检查失败: {reason}",
                    "command": command,
                    "process_id": process_id,
                    "execution_time": error_time
                }
            
            # 验证工作目录
            if workdir:
                if not os.path.exists(workdir):
                    error_time = time.time() - start_time
                    logger.error(f"❌ 工作目录不存在 [{process_id}] - 目录: {workdir}, 耗时: {error_time:.2f}秒")
                    return {
                        "success": False,
                        "error": f"工作目录不存在: {workdir}",
                        # "command": command,
                        "process_id": process_id,
                        "execution_time": error_time
                    }
            
            # 准备环境变量
            env = os.environ.copy()
            if env_vars:
                env.update(env_vars)
            
            # 执行命令
            exec_start_time = time.time()
            logger.info(f"🚀 开始执行命令 [{process_id}]: {command}")
            
            process = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=workdir,
                env=env
            )
            
            # 添加到进程管理器
            self.process_manager.add_process(process_id, process)
            
            try:
                # 等待命令完成
                stdout, stderr = process.communicate(timeout=timeout)
                execution_time = time.time() - exec_start_time
                total_time = time.time() - start_time
                return_code = process.returncode
                
                # 移除进程
                self.process_manager.remove_process(process_id)
                
                # 记录历史
                self._log_shell_history(command, workdir, return_code == 0, return_code, session_id)

                if return_code == 0:
                    logger.info(f"✅ 命令执行成功 [{process_id}] - 返回码: {return_code}, 执行耗时: {execution_time:.2f}秒, 总耗时: {total_time:.2f}秒")
                    
                    return {
                        "success": True,
                        "stdout": stdout,
                        "stderr": stderr,
                        "return_code": return_code,
                        # "command": command,
                        # "workdir": workdir,
                        "execution_time": execution_time,
                        # "total_time": total_time,
                        # "process_id": process_id,
                        # "pid": process.pid
                    }
                else:
                    logger.warning(f"⚠️ 命令执行失败 [{process_id}] - 返回码: {return_code}, 执行耗时: {execution_time:.2f}秒")
                    
                    return {
                        "success": False,
                        "stdout": stdout,
                        "stderr": stderr,
                        "return_code": return_code,
                        "command": command,
                        "workdir": workdir,
                        "execution_time": execution_time,
                        "total_time": total_time,
                        "process_id": process_id,
                        "pid": process.pid
                    }
                    
            except subprocess.TimeoutExpired:
                # 超时处理
                process.kill()
                self.process_manager.remove_process(process_id)
                execution_time = time.time() - exec_start_time
                total_time = time.time() - start_time
                
                # 记录超时历史
                self._log_shell_history(command, workdir, False, -1, session_id)

                logger.error(f"⏰ 命令执行超时 [{process_id}] - 超时时间: {timeout}秒")
                
                return {
                    "success": False,
                    "error": f"命令执行超时 (>{timeout}秒)",
                    "command": command,
                    "timeout": timeout,
                    "execution_time": execution_time,
                    "total_time": total_time,
                    "process_id": process_id,
                    "pid": process.pid
                }
                
        except Exception as e:
            # 清理进程
            if process_id in self.process_manager.running_processes:
                self.process_manager.terminate_process(process_id)
                self.process_manager.remove_process(process_id)
            
            error_time = time.time() - start_time
            # 记录异常历史
            self._log_shell_history(command, workdir, False, -2, session_id)

            logger.error(f"💥 命令执行异常 [{process_id}] - 错误: {str(e)}, 耗时: {error_time:.2f}秒")
            logger.error(traceback.format_exc())
            
            return {
                "success": False,
                "error": str(e),
                "error_traceback": traceback.format_exc(),
                "command": command,
                "execution_time": error_time,
                "process_id": process_id
            }
        finally:
            # 清理已完成的进程
            self.process_manager.cleanup_finished_processes()

    @tool(
        description_i18n={
            "zh": "在临时文件中运行Python代码，可选依赖安装",
            "en": "Run Python code in a temp file, optionally install deps",
            "pt": "Execute código Python em arquivo temporário, opcionalmente instale dependências"
        },
        param_description_i18n={
            "code": {"zh": "Python代码文本", "en": "Python code text", "pt": "Texto de código Python"},
            "workdir": {"zh": "运行目录，默认临时目录", "en": "Working directory, defaults to temp", "pt": "Diretório de execução, padrão temporário"},
            "timeout": {"zh": "超时秒数，默认30", "en": "Timeout in seconds, default 30", "pt": "Tempo limite em segundos, padrão 30"},
            "requirement_list": {"zh": "需要安装的包名称列表", "en": "List of packages to install", "pt": "Lista de pacotes para instalar"},
            "session_id": {"zh": "会话ID (可选, 自动注入, 无需填写)", "en": "Session ID (Optional, Auto-injected)", "pt": "ID da Sessão (Opcional)"}
        }
    )
    def execute_python_code(self, code: str, requirement_list: Optional[Union[List[str], str]] = None, 
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
            self._write_script_file(temp_file, code, workdir)
            
            # 参数类型校验与依赖处理
            python_path = sys.executable
            if not python_path:
                python_path = shutil.which("python") or shutil.which("python3")
            
            if not python_path:
                raise RuntimeError("未找到Python解释器，请确保Python已正确安装")
            parsed_requirements: List[str] = []
            already_available: List[str] = []
            newly_installed: List[str] = []
            install_failed: List[Dict[str, Any]] = []


            if requirement_list is not None:
                # 兼容 JSON 字符串形式的列表
                if isinstance(requirement_list, str):
                    try:
                        requirement_list = json.loads(requirement_list)
                    except json.JSONDecodeError:
                        pass # 将在下面的 isinstance 检查中失败

                if not isinstance(requirement_list, list):
                    return {
                        "success": False,
                        "error": "requirement_list 参数类型错误：仅允许 List[str]",
                        "process_id": process_id,
                    }
            if requirement_list:
                parsed_requirements = [p.strip() for p in requirement_list if isinstance(p, str) and p.strip()]
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
                        module_name = pure_name  # 简单映射
                        try:
                            import importlib.util
                            spec = importlib.util.find_spec(module_name)
                            if spec is not None:
                                already_available.append(package)
                                continue
                        except Exception:
                            pass
                        install_cmd = f"{python_path} -m pip install {package} -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn"
                        install_result = self.execute_shell_command(
                            install_cmd,
                            workdir=workdir,
                            timeout=120
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
            result = self.execute_shell_command(
                python_cmd,
                workdir=workdir,
                timeout=timeout
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

    @tool(
        description_i18n={
            "zh": "在临时文件中运行JavaScript代码，可选依赖安装",
            "en": "Run JavaScript code in a temp file, optionally install deps",
            "pt": "Execute código JavaScript em arquivo temporário, opcionalmente instale dependências"
        },
        param_description_i18n={
            "code": {"zh": "JavaScript代码文本", "en": "JavaScript code text", "pt": "Texto de código JavaScript"},
            "workdir": {"zh": "运行目录，默认临时目录", "en": "Working directory, defaults to temp", "pt": "Diretório de execução, padrão temporário"},
            "timeout": {"zh": "超时秒数，默认30", "en": "Timeout in seconds, default 30", "pt": "Tempo limite em segundos, padrão 30"},
            "npm_packages": {"zh": "需要安装的npm包列表", "en": "List of npm packages to install", "pt": "Lista de pacotes npm para instalar"},
            "session_id": {"zh": "会话ID (可选, 自动注入, 无需填写)", "en": "Session ID (Optional, Auto-injected)", "pt": "ID da Sessão (Opcional)"}
        }
    )
    def execute_javascript_code(self, code: str, npm_packages: Optional[Union[List[str], str]] = None, 
                              workdir: Optional[str] = None, timeout: int = 60,
                              session_id: Optional[str] = None) -> Dict[str, Any]:
        """在临时文件中运行JavaScript代码，可选依赖安装
        
        Args:
            code (str): JavaScript代码文本
            npm_packages (List[str] | str): 需要安装的npm包列表
            workdir (str): 工作目录（可选）
            timeout (int): 超时时间（秒）
            session_id (str): 会话ID（可选，由ToolManager注入）

        Returns:
            Dict[str, Any]: 执行结果
        """
        start_time = time.time()
        process_id = self.process_manager.generate_process_id()
        logger.info(f"📜 execute_javascript_code开始执行 [{process_id}] - 代码长度: {len(code)} 字符")
        logger.info(f"📁 工作目录: {workdir or '临时目录'}, 超时: {timeout}秒")
        
        temp_file = None
        # temp_dir = None
        
        try:
            # 检查node环境
            node_path = shutil.which("node")
            if not node_path:
                raise RuntimeError("未找到Node.js环境，请确保Node.js已正确安装")
            
            # 准备脚本环境：确定路径并确保目录存在
            # 如果未指定workdir，将使用默认脚本目录进行备份和执行
            temp_file, workdir = self._prepare_script_environment(workdir, process_id, "js", session_id)
            
            # 写入代码文件
            self._write_script_file(temp_file, code, workdir)
            
            newly_installed: List[str] = []
            install_failed: List[Dict[str, Any]] = []

            # 处理npm包依赖
            if npm_packages:
                # 兼容 JSON 字符串形式的列表
                if isinstance(npm_packages, str):
                    try:
                        npm_packages = json.loads(npm_packages)
                    except json.JSONDecodeError:
                        pass # 将在下面的 isinstance 检查中失败

                if not isinstance(npm_packages, list):
                     return {
                        "success": False,
                        "error": "npm_packages 参数类型错误：仅允许 List[str]",
                        "process_id": process_id,
                    }
                
                parsed_packages = [p.strip() for p in npm_packages if isinstance(p, str) and p.strip()]
                if parsed_packages:
                    logger.info(f"📦 npm依赖包处理: {parsed_packages}")
                    
                    # 检查是否需要初始化package.json (如果不存在)
                    pkg_json_path = os.path.join(workdir, "package.json")
                    if not os.path.exists(pkg_json_path):
                         self.execute_shell_command("npm init -y", workdir=workdir, timeout=10)
                    
                    # 优化：检查是否所有包都已安装，避免重复运行 npm install
                    packages_to_install = []
                    try:
                        # 简单的检查方式：查看 package.json 中的 dependencies
                        # 更严谨的方式是 check node_modules，但这里先用 package.json 做快速筛选
                        import json
                        with open(pkg_json_path, 'r', encoding='utf-8') as f:
                            pkg_data = json.load(f)
                            dependencies = pkg_data.get('dependencies', {})
                            
                        for pkg in parsed_packages:
                            # 处理带版本的包名 (e.g., "axios@1.0.0")
                            pkg_name = pkg.split('@')[0] if '@' in pkg and not pkg.startswith('@') else pkg
                            if pkg.startswith('@'): # scoped package @scope/pkg@ver
                                parts = pkg.split('@')
                                if len(parts) > 2: # has version
                                    pkg_name = '@' + parts[1]
                                else:
                                    pkg_name = pkg
                            
                            if pkg_name not in dependencies:
                                packages_to_install.append(pkg)
                            elif not os.path.exists(os.path.join(workdir, "node_modules", pkg_name)):
                                # 即使在 package.json 中，如果 node_modules 里没有，也需要安装
                                packages_to_install.append(pkg)
                    except Exception as e:
                        # 如果解析出错，为了安全起见，全部尝试安装
                        logger.warning(f"无法解析 package.json，将尝试安装所有包: {e}")
                        packages_to_install = parsed_packages

                    if packages_to_install:
                        logger.info(f"需要安装的包: {packages_to_install}")
                        # 批量安装，使用国内镜像源加速
                        npm_registry = "https://registry.npmmirror.com/"
                        npm_cmd = f"npm install --registry={npm_registry} {' '.join(packages_to_install)}"
                        install_result = self.execute_shell_command(
                            npm_cmd,
                            workdir=workdir,
                            timeout=120 # 安装依赖给更多时间
                        )
                        
                        if install_result.get("success"):
                            newly_installed.extend(packages_to_install)
                        else:
                            install_failed.append({
                                "packages": packages_to_install,
                                "return_code": install_result.get("return_code"),
                                "stderr": install_result.get("stderr", ""),
                                "stdout": install_result.get("stdout", "")
                            })
                    else:
                        logger.info("所有依赖包已存在，跳过安装")

            # 执行JS代码
            exec_start_time = time.time()
            logger.info(f"🚀 开始执行JavaScript代码 [{process_id}]")
            
            node_cmd = f"{node_path} {temp_file}"
            result = self.execute_shell_command(
                node_cmd,
                workdir=workdir,
                timeout=timeout
            )
            
            execution_time = time.time() - exec_start_time
            total_time = time.time() - start_time
            
            if result["success"]:
                logger.info(f"✅ JavaScript代码执行成功 [{process_id}] - 执行耗时: {execution_time:.2f}秒")
            else:
                logger.error(f"❌ JavaScript代码执行失败 [{process_id}] - 返回码: {result.get('return_code', 'unknown')}")
            
            result.update({
                "npm_packages": npm_packages,
                "installed": newly_installed if npm_packages else None,
                "total_execution_time": total_time
            })
            
             # 如果执行失败，尽可能提供详细的错误trace
            if not result.get("success"):
                stderr_text = result.get("stderr") or ""
                if stderr_text:
                    result["error_traceback"] = stderr_text
                if npm_packages:
                    result["install_failed"] = install_failed or None
            
            if not result.get("success") and install_failed:
                 result["error_hint"] = "检测到依赖安装失败，可能导致运行错误"

            return result

        except Exception as e:
            error_time = time.time() - start_time
            logger.error(f"💥 JavaScript代码执行异常 [{process_id}] - 错误: {str(e)}")
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

    @tool(
        description_i18n={
            "zh": "检查系统命令是否可用及其路径",
            "en": "Check whether system commands are available and their paths",
            "pt": "Verificar se comandos do sistema estão disponíveis e seus caminhos"
        },
        param_description_i18n={
            "commands": {"zh": "待检查的命令名列表", "en": "List of command names to check", "pt": "Lista de nomes de comando para verificar"}
        },
        return_data={
            "type": "object",
            "properties": {
                "available": {"type": "boolean"},
                "path": {"type": "string"},
                "version": {"type": "string"},
                "error": {"type": "string"}
            },
            "required": ["available"]
        }
    )
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
                        timeout=5
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

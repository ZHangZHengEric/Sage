#!/usr/bin/env python3
"""
Execute Command Tool

基于 ToolBase 架构实现的命令执行工具，提供与 mcp_servers/execute_command/execute_command.py 相同的功能。
具备完善的安全机制和错误处理。
"""

import asyncio
import os
import sys
import subprocess
import tempfile
import time
import platform
import shutil
import json
import hashlib
import logging
import traceback
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Union

from .tool_base import ToolBase
from sagents.utils.logger import logger

class SecurityManager:
    """安全管理器 - 负责命令安全检查"""
    
    # 危险命令黑名单
    DANGEROUS_COMMANDS = {
        'rm', 'rmdir', 'del', 'format', 'fdisk', 'mkfs',
        'sudo', 'su', 'chmod', 'chown', 'passwd',
        'shutdown', 'reboot', 'systemctl', 'service',
        'kill', 'killall', 'pkill', 'taskkill',
        'dd', 'crontab', 'at', 'batch'
    }
    
    # 恶意模式检测
    MALICIOUS_PATTERNS = [
        '&&', '||', ';', '|', '>', '>>', '<',
        '$(', '`',
        'curl', 'wget', 'nc', 'netcat'
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
                if base_command in self.DANGEROUS_COMMANDS:
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

class ExecuteCommandTool(ToolBase):
    """命令执行工具集"""
    
    def __init__(self):
        logger.debug("Initializing ExecuteCommandTool")
        # 先初始化必要的组件，再调用父类初始化
        self.security_manager = SecurityManager(False)
        self.process_manager = ProcessManager()
        super().__init__()

    @ToolBase.tool()
    def execute_shell_command(self, command: str, workdir: Optional[str] = None, 
                             timeout: int = 30, env_vars: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """在指定目录执行Shell命令，后台执行请通过command 进行设置

        Args:
            command (str): 要执行的Shell命令
            workdir (str): 命令执行的工作目录（可选）
            timeout (int): 超时时间，默认30秒
            env_vars (dict): 自定义环境变量（可选）

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
            logger.error(f"💥 命令执行异常 [{process_id}] - 错误: {str(e)}, 耗时: {error_time:.2f}秒")
            
            return {
                "success": False,
                "error": str(e),
                "command": command,
                "execution_time": error_time,
                "process_id": process_id
            }
        finally:
            # 清理已完成的进程
            self.process_manager.cleanup_finished_processes()

    @ToolBase.tool()
    def execute_python_code(self, code: str, workdir: Optional[str] = None, 
                           timeout: int = 30, requirements: Optional[Union[str, List[str]]] = None) -> Dict[str, Any]:
        """在临时执行Python代码，会话在执行完后会删除，不具有持久性

        Args:
            code (str): 要执行的Python代码
            workdir (str): 代码执行的工作目录（可选）
            timeout (int): 超时时间，默认30秒
            requirements (list): 需要安装的Python包列表（可选）

        Returns:
            Dict[str, Any]: 包含执行结果的字典
        """
        start_time = time.time()
        process_id = self.process_manager.generate_process_id()
        logger.info(f"🐍 execute_python_code开始执行 [{process_id}] - 代码长度: {len(code)} 字符")
        logger.info(f"📁 工作目录: {workdir or '临时目录'}, 超时: {timeout}秒")
        
        temp_file = None
        try:
            # 创建临时Python文件
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(code)
                temp_file = f.name
            
            # 安装依赖包（如果需要）
            if requirements:
                if isinstance(requirements, str):
                    requirements = [requirements]
                logger.info(f"📦 安装依赖包: {requirements}")
                for package in requirements:
                    install_result = self.execute_shell_command(
                        f"pip install {package}",
                        workdir=workdir,
                        timeout=60
                    )
                    if not install_result["success"]:
                        error_time = time.time() - start_time
                        logger.error(f"❌ 依赖包安装失败 [{process_id}] - 包: {package}")
                        return {
                            "success": False,
                            "error": f"安装依赖包失败: {package}",
                            "install_error": install_result.get("stderr", ""),
                            "execution_time": error_time,
                            "process_id": process_id
                        }
            
            # 执行Python代码
            exec_start_time = time.time()
            logger.info(f"🚀 开始执行Python代码 [{process_id}]")
            
            python_path = shutil.which("python") or shutil.which("python3")
            if not python_path:
                raise RuntimeError("未找到Python解释器，请确保Python已正确安装")
            
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
            
            # 添加额外信息
            result.update({
                # "temp_file": temp_file,
                "requirements": requirements,
                "total_execution_time": total_time,
                # "process_id": process_id
            })
            
            return result
            
        except Exception as e:
            error_time = time.time() - start_time
            logger.error(f"💥 Python代码执行异常 [{process_id}] - 错误: {str(e)}")
            
            return {
                "success": False,
                "error": str(e),
                "code": code,
                "execution_time": error_time,
                "process_id": process_id
            }
        finally:
            # 清理临时文件
            if temp_file and os.path.exists(temp_file):
                try:
                    os.unlink(temp_file)
                    logger.debug(f"🗑️ 临时文件已删除: {temp_file}")
                except Exception as e:
                    logger.warning(f"⚠️ 删除临时文件失败: {str(e)}")

    @ToolBase.tool()
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
            
            return {
                "success": False,
                "error": str(e),
                "execution_time": error_time,
                "check_id": check_id
            }

    @ToolBase.tool()
    def get_system_info(self) -> Dict[str, Any]:
        """获取系统信息

        Returns:
            Dict[str, Any]: 包含系统信息的字典
        """
        try:
            logger.info("🖥️ 获取系统信息")
            
            system_info = {
                "platform": platform.platform(),
                "system": platform.system(),
                "release": platform.release(),
                "version": platform.version(),
                "machine": platform.machine(),
                "processor": platform.processor(),
                "architecture": platform.architecture(),
                "python_version": platform.python_version(),
                "python_implementation": platform.python_implementation(),
                "current_directory": os.getcwd(),
                "environment_variables": dict(os.environ),
                "path_separator": os.pathsep,
                "line_separator": os.linesep
            }
            
            # 添加一些有用的路径信息
            system_info["paths"] = {
                "python_executable": sys.executable,
                "python_path": sys.path,
                "home_directory": os.path.expanduser("~"),
                "temp_directory": tempfile.gettempdir()
            }
            
            # 检查常用命令的可用性
            common_commands = ["git", "npm", "node", "docker", "python", "python3", "pip", "pip3"]
            availability_result = self.check_command_availability(common_commands)
            if availability_result["success"]:
                system_info["command_availability"] = availability_result["results"]
            
            logger.info("✅ 系统信息获取成功")
            
            return {
                "success": True,
                "system_info": system_info,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"💥 获取系统信息失败: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }

    @ToolBase.tool()
    def execute_batch_commands(self, commands: List[str], workdir: Optional[str] = None, 
                              timeout: int = 30, stop_on_error: bool = True) -> Dict[str, Any]:
        """批量执行多个Shell命令

        Args:
            commands (list): 要执行的命令列表
            workdir (str): 命令执行的工作目录（可选）
            timeout (int): 每个命令的超时时间，默认30秒
            stop_on_error (bool): 遇到错误时是否停止执行，默认True

        Returns:
            Dict[str, Any]: 包含所有命令执行结果的字典
        """
        start_time = time.time()
        batch_id = hashlib.md5(f"batch_{time.time()}".encode()).hexdigest()[:8]
        logger.info(f"📋 execute_batch_commands开始执行 [{batch_id}] - 命令数: {len(commands)}")
        
        try:
            results = []
            successful_commands = 0
            failed_commands = 0
            
            for i, command in enumerate(commands):
                logger.info(f"🔄 执行命令 {i+1}/{len(commands)}: {command}")
                
                result = self.execute_shell_command(
                    command=command,
                    workdir=workdir,
                    timeout=timeout
                )
                
                result["command_index"] = i
                result["command_number"] = i + 1
                results.append(result)
                
                if result["success"]:
                    successful_commands += 1
                    logger.info(f"✅ 命令 {i+1} 执行成功")
                else:
                    failed_commands += 1
                    logger.error(f"❌ 命令 {i+1} 执行失败: {result.get('error', 'Unknown error')}")
                    
                    if stop_on_error:
                        logger.warning(f"🛑 遇到错误，停止执行剩余命令")
                        break
            
            total_time = time.time() - start_time
            
            logger.info(f"📋 批量命令执行完成 [{batch_id}] - 成功: {successful_commands}, 失败: {failed_commands}, 总耗时: {total_time:.2f}秒")
            
            return {
                "success": failed_commands == 0,
                "results": results,
                "summary": {
                    "total_commands": len(commands),
                    "executed_commands": len(results),
                    "successful_commands": successful_commands,
                    "failed_commands": failed_commands,
                    "stopped_on_error": stop_on_error and failed_commands > 0
                },
                "execution_time": total_time,
                "batch_id": batch_id
            }
            
        except Exception as e:
            error_time = time.time() - start_time
            logger.error(f"💥 批量命令执行异常 [{batch_id}] - 错误: {str(e)}")
            
            return {
                "success": False,
                "error": str(e),
                "execution_time": error_time,
                "batch_id": batch_id
            }
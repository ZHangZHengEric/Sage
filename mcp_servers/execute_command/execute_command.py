#!/usr/bin/env python3
"""
Execute Command MCP Server

一个安全、强大的命令执行MCP服务器，支持Shell命令执行、Python代码运行等功能。
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
import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Union
import traceback

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.routing import Mount

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 初始化 FastMCP
mcp = FastMCP("Execute Command")

# 解析命令行参数
parser = argparse.ArgumentParser(description='启动命令执行 MCP Server')
parser.add_argument('--port', type=int, default=34010, help='服务器端口')
parser.add_argument('--host', type=str, default='0.0.0.0', help='服务器主机')
parser.add_argument('--max_timeout', type=int, default=300, help='最大超时时间(秒)')
parser.add_argument('--enable_dangerous_commands', action='store_true', 
                   help='启用危险命令执行（生产环境不推荐）')

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

# 全局实例
security_manager = SecurityManager()
process_manager = ProcessManager()

@mcp.tool()
async def execute_shell_command(
    command: str,
    workdir: Optional[str] = None,
    timeout: int = 30,
    env_vars: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    在指定目录执行Shell命令
    
    Args:
        command: 要执行的Shell命令
        workdir: 命令执行的工作目录（可选）
        timeout: 超时时间，默认30秒
        env_vars: 自定义环境变量（可选）
    
    Returns:
        包含执行结果的字典
    """
    start_time = time.time()
    process_id = process_manager.generate_process_id()
    logger.info(f"🖥️ execute_shell_command开始执行 [{process_id}] - command: {command[:100]}{'...' if len(command) > 100 else ''}")
    logger.info(f"📁 工作目录: {workdir or '当前目录'}, 超时: {timeout}秒")
    logger.debug(f"🌍 环境变量: {env_vars if env_vars else '使用默认'}")
    
    try:
        # 安全检查
        logger.debug(f"🔒 开始安全检查")
        is_safe, reason = security_manager.is_command_safe(command)
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
        logger.info(f"✅ 安全检查通过 [{process_id}]")
        
        # 验证工作目录
        if workdir:
            if not os.path.exists(workdir):
                error_time = time.time() - start_time
                logger.error(f"❌ 工作目录不存在 [{process_id}] - 目录: {workdir}, 耗时: {error_time:.2f}秒")
                return {
                    "success": False,
                    "error": f"工作目录不存在: {workdir}",
                    "command": command,
                    "process_id": process_id,
                    "execution_time": error_time
                }
            logger.debug(f"📁 工作目录验证通过: {workdir}")
        
        # 准备环境变量
        env = os.environ.copy()
        if env_vars:
            env.update(env_vars)
            logger.debug(f"🌍 添加了 {len(env_vars)} 个自定义环境变量")
        
        # 记录开始时间
        exec_start_time = time.time()
        
        # 执行命令
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
        process_manager.add_process(process_id, process)
        logger.debug(f"📋 进程已添加到管理器 [{process_id}] - PID: {process.pid}")
        
        try:
            # 等待命令完成
            stdout, stderr = process.communicate(timeout=timeout)
            execution_time = time.time() - exec_start_time
            total_time = time.time() - start_time
            return_code = process.returncode
            
            # 移除进程
            process_manager.remove_process(process_id)
            
            if return_code == 0:
                logger.info(f"✅ 命令执行成功 [{process_id}] - 返回码: {return_code}, 执行耗时: {execution_time:.2f}秒, 总耗时: {total_time:.2f}秒")
                logger.debug(f"📤 输出长度: {len(stdout)} 字符")
                
                return {
                    "success": True,
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
            else:
                logger.warning(f"⚠️ 命令执行失败 [{process_id}] - 返回码: {return_code}, 执行耗时: {execution_time:.2f}秒, 总耗时: {total_time:.2f}秒")
                logger.debug(f"📤 标准输出: {stdout[:200]}{'...' if len(stdout) > 200 else ''}")
                logger.debug(f"📤 错误输出: {stderr[:200]}{'...' if len(stderr) > 200 else ''}")
                
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
            process_manager.remove_process(process_id)
            execution_time = time.time() - exec_start_time
            total_time = time.time() - start_time
            
            logger.error(f"⏰ 命令执行超时 [{process_id}] - 超时时间: {timeout}秒, 执行耗时: {execution_time:.2f}秒, 总耗时: {total_time:.2f}秒")
            
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
        if process_id in process_manager.running_processes:
            process_manager.terminate_process(process_id)
            process_manager.remove_process(process_id)
        
        error_time = time.time() - start_time
        logger.error(f"💥 命令执行异常 [{process_id}] - 错误: {str(e)}, 耗时: {error_time:.2f}秒")
        logger.error(f"🔍 异常详情: {traceback.format_exc()}")
        
        return {
            "success": False,
            "error": str(e),
            "command": command,
            "execution_time": error_time,
            "process_id": process_id
        }
    finally:
        # 清理已完成的进程
        process_manager.cleanup_finished_processes()

@mcp.tool()
async def execute_python_code(
    code: str,
    workdir: Optional[str] = None,
    timeout: int = 30,
    requirements: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    在临时文件中执行Python代码
    
    Args:
        code: 要执行的Python代码
        workdir: 代码执行的工作目录（可选）
        timeout: 超时时间，默认30秒
        requirements: 需要安装的Python包列表（可选）
    
    Returns:
        包含执行结果的字典
    """
    start_time = time.time()
    process_id = process_manager.generate_process_id()
    logger.info(f"🐍 execute_python_code开始执行 [{process_id}] - 代码长度: {len(code)} 字符")
    logger.info(f"📁 工作目录: {workdir or '临时目录'}, 超时: {timeout}秒")
    logger.debug(f"📦 依赖包: {requirements if requirements else '无'}")
    logger.debug(f"📝 Python代码预览: {code[:200]}{'...' if len(code) > 200 else ''}")
    
    temp_file = None
    try:
        # 创建临时Python文件
        logger.debug(f"📄 创建临时Python文件")
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            temp_file = f.name
        
        logger.debug(f"📄 临时文件创建成功: {temp_file}")
        
        # 安装依赖包（如果需要）
        if requirements:
            logger.info(f"📦 安装依赖包: {requirements}")
            for package in requirements:
                logger.debug(f"📦 安装包: {package}")
                install_result = await execute_shell_command(
                    f"pip install {package}",
                    workdir=workdir,
                    timeout=60
                )
                if not install_result["success"]:
                    error_time = time.time() - start_time
                    logger.error(f"❌ 依赖包安装失败 [{process_id}] - 包: {package}, 耗时: {error_time:.2f}秒")
                    return {
                        "success": False,
                        "error": f"安装依赖包失败: {package}",
                        "install_error": install_result["stderr"],
                        "execution_time": error_time,
                        "process_id": process_id
                    }
                logger.info(f"✅ 包安装成功: {package}")
        
        # 执行Python代码
        exec_start_time = time.time()
        logger.info(f"🚀 开始执行Python代码 [{process_id}]")
        
        python_path = shutil.which("python") or shutil.which("python3")
        if not python_path:
            raise RuntimeError("未找到Python解释器，请确保Python已正确安装")
        
        # 使用subprocess直接执行，避免shell解析问题
        logger.debug(f"🐍 执行命令: {python_path} {temp_file}")
        
        try:
            process = subprocess.Popen(
                [python_path, temp_file],  # 使用列表形式，避免shell解析
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=workdir
            )
            
            process_manager.add_process(process_id, process)
            
            # 等待执行完成
            stdout, stderr = process.communicate(timeout=timeout)
            return_code = process.returncode
            
            process_manager.remove_process(process_id)
            
            result = {
                "success": return_code == 0,
                "stdout": stdout,
                "stderr": stderr,
                "return_code": return_code,
                "command": f"{python_path} {temp_file}",
                "workdir": workdir,
                "process_id": process_id,
                "pid": process.pid
            }
            
        except subprocess.TimeoutExpired:
            process.kill()
            process_manager.remove_process(process_id)
            result = {
                "success": False,
                "error": f"Python代码执行超时 (>{timeout}秒)",
                "process_id": process_id,
                "pid": process.pid
            }
        
        execution_time = time.time() - exec_start_time
        total_time = time.time() - start_time
        
        if result["success"]:
            logger.info(f"✅ Python代码执行成功 [{process_id}] - 执行耗时: {execution_time:.2f}秒, 总耗时: {total_time:.2f}秒")
            logger.debug(f"📤 输出长度: {len(result['stdout'])} 字符")
        else:
            logger.error(f"❌ Python代码执行失败 [{process_id}] - 返回码: {result.get('return_code', 'unknown')}, 执行耗时: {execution_time:.2f}秒, 总耗时: {total_time:.2f}秒")
            logger.debug(f"📤 错误输出: {result['stderr'][:200]}{'...' if len(result.get('stderr', '')) > 200 else ''}")
        
        # 添加额外信息
        result.update({
            "code": code,
            "temp_file": temp_file,
            "requirements": requirements,
            "total_execution_time": total_time,
            "process_id": process_id
        })
        
        return result
        
    except Exception as e:
        error_time = time.time() - start_time
        logger.error(f"💥 Python代码执行异常 [{process_id}] - 错误: {str(e)}, 耗时: {error_time:.2f}秒")
        logger.error(f"🔍 异常详情: {traceback.format_exc()}")
        
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

@mcp.tool()
async def check_command_availability(
    commands: List[str]
) -> Dict[str, Any]:
    """
    检查系统中命令的可用性
    
    Args:
        commands: 要检查的命令列表
    
    Returns:
        包含检查结果的字典
    """
    start_time = time.time()
    check_id = hashlib.md5(f"check_{time.time()}".encode()).hexdigest()[:8]
    logger.info(f"🔍 check_command_availability开始执行 [{check_id}] - 检查命令数: {len(commands)}")
    logger.debug(f"📋 命令列表: {commands}")
    
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
                        "version": None  # 可以后续扩展获取版本信息
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
        logger.error(f"💥 命令可用性检查异常 [{check_id}] - 错误: {str(e)}, 耗时: {error_time:.2f}秒")
        logger.error(f"🔍 异常详情: {traceback.format_exc()}")
        
        return {
            "success": False,
            "error": str(e),
            "execution_time": error_time,
            "check_id": check_id
        }

def main():
    """主函数"""
    global security_manager
    
    args = parser.parse_args()
    
    # 初始化安全管理器
    security_manager = SecurityManager(enable_dangerous_commands=args.enable_dangerous_commands)
    
    logger.info(f"启动命令执行 MCP Server")
    logger.info(f"端口: {args.port}")
    logger.info(f"主机: {args.host}")
    logger.info(f"最大超时: {args.max_timeout}秒")
    logger.info(f"危险命令: {'已启用' if args.enable_dangerous_commands else '已禁用'}")
    
    # 创建 Starlette 应用
    app = Starlette(
        routes=[
            Mount('/', app=mcp.sse_app()),
        ]
    )
    
    # 启动服务器
    uvicorn.run(app, host=args.host, port=args.port)

if __name__ == "__main__":
    main()

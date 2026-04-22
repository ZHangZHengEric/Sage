#!/usr/bin/env python3
"""
Execute Command Tool

通过沙箱执行命令的工具，所有命令都在沙箱环境中运行。
"""

from typing import Dict, Any, Optional
from ..tool_base import tool
from sagents.utils.logger import logger
from sagents.utils.sandbox._stdout_echo import echo_header, echo_footer
from sagents.utils.agent_session_helper import get_session_sandbox as _get_session_sandbox_util


class SecurityManager:
    """安全管理器 - 负责命令安全检查"""

    # 危险命令黑名单
    DANGEROUS_COMMANDS = {
        'format', 'fdisk', 'mkfs',
        'sudo', 'su', 'passwd',
        'shutdown', 'reboot', 'systemctl', 'service',
        'dd', 'crontab', 'at', 'batch'
    }

    def is_command_safe(self, command: str) -> tuple[bool, str]:
        """检查命令是否安全"""
        if not command or not command.strip():
            return False, "命令不能为空"

        command = command.strip().lower()
        command_parts = command.split()
        if command_parts:
            base_command = command_parts[0].split('/')[-1]
            if base_command in self.DANGEROUS_COMMANDS or base_command.startswith('mkfs.'):
                return False, f"危险命令被阻止: {base_command}"

        return True, "命令安全检查通过"


class ExecuteCommandTool:
    """命令执行工具 - 通过沙箱执行命令"""

    def __init__(self):
        self.security_manager = SecurityManager()

    def _get_sandbox(self, session_id: str):
        """通过 session_id 获取沙箱。详见
        ``sagents.utils.agent_session_helper.get_session_sandbox``。
        """
        return _get_session_sandbox_util(session_id, log_prefix="ExecuteCommandTool")

    @tool(
        description_i18n={
            "zh": "在沙箱中执行Shell命令，具备安全检查与超时控制。如需后台运行命令（不阻塞立即返回），请使用 nohup 或将输出重定向到文件，例如：nohup your_command > output.log 2>&1 & 或 (your_command) > output.log 2>&1 &",
            "en": "Execute a shell command in sandbox with safety checks and timeout. For background execution (non-blocking, returns immediately), use nohup or redirect output to file, e.g.: nohup your_command > output.log 2>&1 & or (your_command) > output.log 2>&1 &",
        },
        param_description_i18n={
            "command": {"zh": "待执行的Shell命令字符串。如需后台运行，使用 nohup ... > file 2>&1 & 或 (...) > file 2>&1 &", "en": "Shell command to execute. For background execution, use nohup ... > file 2>&1 & or (...) > file 2>&1 &"},
            "workdir": {"zh": "执行目录（虚拟路径），默认沙箱工作区", "en": "Working directory (virtual path), defaults to sandbox workspace"},
            "timeout": {"zh": "超时秒数，默认30", "en": "Timeout in seconds, default 30"},
            "env_vars": {"zh": "附加环境变量字典", "en": "Additional environment variables dict"},
            "session_id": {"zh": "会话ID（必填，自动注入）", "en": "Session ID (Required, Auto-injected)"},
        },
        param_schema={
            "command": {"type": "string", "description": "Shell command to execute"},
            "workdir": {"type": "string", "description": "Working directory (virtual path)"},
            "timeout": {"type": "integer", "default": 30},
            "env_vars": {"type": "string", "description": "Additional environment variables as a JSON object string, e.g. '{\"KEY\": \"VALUE\"}'. Leave empty if not needed."},
            "session_id": {"type": "string", "description": "Session ID"},
        },
        return_data={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "stdout": {"type": "string"},
                "stderr": {"type": "string"},
                "return_code": {"type": "integer"},
                "execution_time": {"type": "number"},
            },
            "required": ["success"]
        }
    )
    async def execute_shell_command(
        self,
        command: str,
        workdir: Optional[str] = None,
        timeout: int = 30,
        env_vars: Optional[str] = None,
        session_id: str = None,
    ) -> Dict[str, Any]:
        """
        在沙箱中执行 Shell 命令

        Args:
            command: Shell 命令字符串
            workdir: 执行目录（虚拟路径）
            timeout: 超时秒数
            env_vars: 附加环境变量（JSON 字符串格式，如 '{"KEY": "VALUE"}'）
            session_id: 会话ID（必填）

        Returns:
            执行结果字典
        """
        if not session_id:
            raise ValueError("ExecuteCommandTool: session_id is required")

        # env_vars 以 JSON 字符串传入，解析为 dict
        parsed_env_vars: Optional[Dict[str, str]] = None
        if env_vars and isinstance(env_vars, str) and env_vars.strip():
            try:
                import json as _json
                parsed_env_vars = _json.loads(env_vars)
            except Exception:
                logger.warning(f"env_vars 解析失败，忽略: {env_vars!r}")
        elif isinstance(env_vars, dict):
            parsed_env_vars = env_vars

        logger.info(f"🖥️ ExecuteCommandTool: {command[:100]}{'...' if len(command) > 100 else ''}")

        # 安全检查
        is_safe, reason = self.security_manager.is_command_safe(command)
        if not is_safe:
            logger.warning(f"安全检查失败: {reason}")
            return {
                "success": False,
                "error": f"安全检查失败: {reason}",
                "command": command,
                "execution_time": 0
            }

        # 获取沙箱
        sandbox = self._get_sandbox(session_id)

        # 头尾打印一行分隔符，方便在 docker logs / 终端里看清是哪条命令
        # （正文 stdout 由沙箱执行层在 read_output 里增量写出，受 SAGE_ECHO_SHELL_OUTPUT 控制）
        echo_header(command)
        result = None
        try:
            result = await sandbox.execute_command(
                command=command,
                workdir=workdir,
                timeout=timeout,
                env_vars=parsed_env_vars,
            )
        finally:
            echo_footer(result.return_code if result is not None else None)

        logger.info(f"✅ ExecuteCommandTool: success={result.success}, rc={result.return_code}")

        # 转换结果格式
        return {
            "success": result.success,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "return_code": result.return_code,
            "execution_time": result.execution_time,
        }

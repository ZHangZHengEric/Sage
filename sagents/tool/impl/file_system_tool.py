import os
import re
from typing import Dict, Any, Optional

from ..tool_base import tool
from sagents.utils.logger import logger


class FileSystemTool:
    """文件系统操作工具集 - 通过沙箱执行"""

    def _get_sandbox(self, session_id: str):
        """通过 session_id 获取沙箱"""
        from sagents.session_runtime import get_global_session_manager
        session_manager = get_global_session_manager()
        session = session_manager.get(session_id)
        if not session or not session.session_context:
            raise ValueError(f"FileSystemTool: Invalid session_id={session_id}")

        sandbox = session.session_context.sandbox
        if not sandbox:
            raise ValueError(f"FileSystemTool: No sandbox available for session_id={session_id}")

        return sandbox

    @tool(
        description_i18n={
            "zh": "读取文本文件指定行范围内容",
            "en": "Read text file within a line range",
        },
        param_description_i18n={
            "file_path": {"zh": "文件虚拟路径", "en": "File virtual path"},
            "start_line": {"zh": "开始行号，默认0", "en": "Start line number, default 0"},
            "end_line": {"zh": "结束行号（不包含），默认400，None表示读取到文件末尾", "en": "End line number (exclusive), default 400, None means read to end"},
            "session_id": {"zh": "会话ID（必填，自动注入）", "en": "Session ID (Required, Auto-injected)"},
        },
        param_schema={
            "file_path": {"type": "string", "description": "File virtual path"},
            "start_line": {"type": "integer", "default": 0},
            "end_line": {"type": "integer", "default": 400},
            "session_id": {"type": "string", "description": "Session ID"},
        }
    )
    async def file_read(
        self,
        file_path: str,
        start_line: int = 0,
        end_line: Optional[int] = 400,
        session_id: str = None,
    ) -> Dict[str, Any]:
        """读取文本文件指定行范围内容

        Args:
            file_path: 文件虚拟路径
            start_line: 开始行号，默认0
            end_line: 结束行号（不包含），默认400
            session_id: 会话ID（必填）

        Returns:
            包含文件内容和元信息
        """
        if not session_id:
            raise ValueError("FileSystemTool: session_id is required")

        sandbox = self._get_sandbox(session_id)

        try:
            content = await sandbox.read_file(file_path, encoding="utf-8")
            lines = content.splitlines()
            total_lines = len(lines)

            if end_line is None:
                end_line = total_lines
            start_line = max(0, start_line)
            end_line = min(total_lines, end_line)

            selected_lines = lines[start_line:end_line]
            selected_content = "\n".join(selected_lines)

            return {
                "status": "success",
                "content": selected_content,
                "total_lines": total_lines,
                "start_line": start_line,
                "end_line": end_line,
                "lines_read": len(selected_lines),
                "file_path": file_path,
            }

        except Exception as e:
            logger.error(f"FileSystemTool: 读取文件失败 {file_path}: {e}")
            return {
                "status": "error",
                "message": f"读取文件失败: {str(e)}",
                "file_path": file_path,
            }

    @tool(
        description_i18n={
            "zh": "写入文本到文件",
            "en": "Write text to file",
        },
        param_description_i18n={
            "file_path": {"zh": "文件虚拟路径", "en": "File virtual path"},
            "content": {"zh": "要写入的文本内容", "en": "Text content to write"},
            "session_id": {"zh": "会话ID（必填，自动注入）", "en": "Session ID (Required, Auto-injected)"},
        },
        param_schema={
            "file_path": {"type": "string", "description": "File virtual path"},
            "content": {"type": "string", "description": "Text content to write"},
            "session_id": {"type": "string", "description": "Session ID"},
        }
    )
    async def file_write(
        self,
        file_path: str,
        content: str,
        session_id: str = None,
    ) -> Dict[str, Any]:
        """写入文本到文件（覆盖模式）

        Args:
            file_path: 文件虚拟路径
            content: 要写入的内容
            session_id: 会话ID（必填）

        Returns:
            操作结果
        """
        if not session_id:
            raise ValueError("FileSystemTool: session_id is required")

        sandbox = self._get_sandbox(session_id)

        try:
            dir_path = os.path.dirname(file_path)
            if dir_path:
                await sandbox.ensure_directory(dir_path)

            await sandbox.write_file(file_path, content, mode="overwrite")

            return {
                "status": "success",
                "message": "文件写入成功",
                "file_path": file_path,
                "content_length": len(content),
            }

        except Exception as e:
            logger.error(f"FileSystemTool: 写入文件失败 {file_path}: {e}")
            return {
                "status": "error",
                "message": f"写入文件失败: {str(e)}",
                "file_path": file_path,
            }

    @tool(
        description_i18n={
            "zh": "修改文件指定内容（搜索替换模式）",
            "en": "Modify specific content in a file (Search & Replace)",
        },
        param_description_i18n={
            "file_path": {"zh": "文件虚拟路径", "en": "File virtual path"},
            "search_pattern": {"zh": "需要被替换的原始内容", "en": "Original content to be replaced"},
            "replacement": {"zh": "新的内容", "en": "New content"},
            "use_regex": {"zh": "是否使用正则表达式匹配", "en": "Use regular expression matching"},
            "session_id": {"zh": "会话ID（必填，自动注入）", "en": "Session ID (Required, Auto-injected)"},
        },
        param_schema={
            "file_path": {"type": "string", "description": "File virtual path"},
            "search_pattern": {"type": "string", "description": "Original content to be replaced"},
            "replacement": {"type": "string", "description": "New content"},
            "use_regex": {"type": "boolean", "default": False},
            "session_id": {"type": "string", "description": "Session ID"},
        }
    )
    async def file_update(
        self,
        file_path: str,
        search_pattern: str,
        replacement: str,
        use_regex: bool = False,
        session_id: str = None,
    ) -> Dict[str, Any]:
        """更新文件中匹配的文本内容（Search & Replace）

        Args:
            file_path: 文件虚拟路径
            search_pattern: 要搜索的模式
            replacement: 替换文本
            use_regex: 是否使用正则表达式
            session_id: 会话ID（必填）

        Returns:
            替换结果统计
        """
        if not session_id:
            raise ValueError("FileSystemTool: session_id is required")

        sandbox = self._get_sandbox(session_id)

        try:
            content = await sandbox.read_file(file_path)

            if use_regex:
                pattern = re.compile(search_pattern)
                new_content, replace_count = pattern.subn(replacement, content)
            else:
                new_content = content.replace(search_pattern, replacement)
                replace_count = content.count(search_pattern)

            if replace_count == 0:
                return {
                    "status": "error",
                    "message": "未找到匹配项，未进行任何替换",
                    "replacements": 0,
                }

            await sandbox.write_file(file_path, new_content, mode="overwrite")

            return {
                "status": "success",
                "message": f"成功替换 {replace_count} 处匹配项",
                "replacements": replace_count,
                "original_length": len(content),
                "new_length": len(new_content),
            }

        except Exception as e:
            logger.error(f"FileSystemTool: 文件更新失败 {file_path}: {e}")
            return {
                "status": "error",
                "message": f"文件更新失败: {str(e)}",
                "file_path": file_path,
            }

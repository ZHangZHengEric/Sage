"""基于工具的用户记忆驱动实现

使用ToolManager调用底层的记忆工具（可能是本地工具或MCP工具）。

"""

import json
import os
from typing import List, Optional, Dict, Any
from datetime import datetime
from sagents.utils.logger import logger
from ..interfaces import IMemoryDriver
from ..schemas import MemoryEntry, MemoryType
class ToolMemoryDriver(IMemoryDriver):
    """基于ToolManager的记忆驱动实现"""

    def __init__(self):
        """
        Args:
            tool_manager: 工具管理器实例
        """
        from sagents.tool.tool_manager import get_tool_manager
        self.tool_manager = get_tool_manager()
        self._available = False
        self._check_availability()

    def _check_availability(self):
        """检查记忆工具是否可用"""
        try:
            if not self.tool_manager:
                self._available = False
                logger.warning("ToolManager 未初始化，记忆驱动不可用")
                return

            # 检查必需的记忆工具是否可用
            required_tools = ['remember_user_memory', 'recall_user_memory', 'forget_user_memory']
            missing_tools = []

            all_tools = self.tool_manager.list_all_tools_name()
            for tool_name in required_tools:
                if tool_name not in all_tools:
                    missing_tools.append(tool_name)

            if missing_tools:
                logger.error(f"部分记忆工具不可用: {missing_tools}")
                self._available = False
            else:
                self._available = True
                logger.debug(f"记忆驱动验证成功，可用工具: {required_tools}")

        except Exception as e:
            logger.error(f"记忆工具验证失败: {e}")
            self._available = False

    def is_available(self) -> bool:
        """检查记忆工具是否可用"""
        # 基础检查：工具管理器是否初始化
        if not self._available:
            return False

        # 环境变量检查：如果没有设置MEMORY_ROOT_PATH，视为不可用
        # 这确保了UserMemoryManager能正确感知记忆功能状态
        if os.getenv('MEMORY_ROOT_PATH') is None:
            return False

        return True

    async def remember(self, user_id: str, memory_key: str, content: str, memory_type: str, tags: str, session_id: Optional[str] = None, session_context: Optional[Any] = None) -> str:
        if not self._available:
            return "记忆功能不可用"

        try:
            return await self.tool_manager.run_tool_async(
                tool_name='remember_user_memory',
                session_context=session_context,
                session_id=session_id,
                user_id=user_id,
                memory_key=memory_key,
                content=content,
                memory_type=memory_type,
                tags=tags
            )
        except Exception as e:
            logger.error(f"记住记忆失败: {e}")
            return f"记住记忆失败：{str(e)}"

    async def forget(self, user_id: str, memory_key: str, session_id: Optional[str] = None, session_context: Optional[Any] = None) -> str:
        if not self._available:
            return "记忆功能不可用"

        try:
            return await self.tool_manager.run_tool_async(
                tool_name='forget_user_memory',
                session_context=session_context,
                session_id=session_id,
                user_id=user_id,
                memory_key=memory_key
            )
        except Exception as e:
            logger.error(f"忘记记忆失败: {e}")
            return f"忘记记忆失败：{str(e)}"

    def _convert_memories_to_entries(self, memories_data: List[Dict]) -> List[MemoryEntry]:
        """将记忆数据转换为MemoryEntry对象列表"""
        entries = []
        for memory_data in memories_data:
            try:
                # 补充缺失的字段
                entry_data = {
                    'key': memory_data.get('key', ''),
                    'content': memory_data.get('content', ''),
                    'memory_type': MemoryType.EXPERIENCE,  # 默认为经验类型
                    'created_at': datetime.fromisoformat(memory_data.get('created_at', datetime.now().isoformat())),
                    'updated_at': datetime.fromisoformat(memory_data.get('updated_at', datetime.now().isoformat())),
                    'importance': memory_data.get('importance', 0.5),
                    'tags': memory_data.get('tags', []),
                    'access_count': memory_data.get('access_count', 0),
                    'version': memory_data.get('version', 1)
                }

                # 尝试转换 memory_type 字符串为枚举
                if 'memory_type' in memory_data:
                    try:
                        entry_data['memory_type'] = MemoryType(memory_data['memory_type'])
                    except ValueError:
                        pass # 保持默认或处理错误

                entries.append(MemoryEntry(**entry_data))
            except Exception as e:
                logger.warning(f"转换记忆条目失败: {e}, 数据: {memory_data}")
                continue
        return entries

    def _parse_tool_result(self, result: Any) -> List[Dict]:
        """解析工具返回的JSON结果"""
        try:
            # 首先尝试解析外层JSON
            if isinstance(result, str):
                try:
                    outer_data = json.loads(result)
                except json.JSONDecodeError:
                    # 如果不是JSON，可能直接是错误信息或空
                    return []

                if 'content' in outer_data and isinstance(outer_data['content'], str):
                    # 解析嵌套的JSON字符串 (MCP工具常见返回格式)
                    try:
                        content_data = json.loads(outer_data['content'])
                    except json.JSONDecodeError:
                        content_data = outer_data
                else:
                    content_data = outer_data
            elif isinstance(result, dict):
                if 'content' in result and isinstance(result['content'], str):
                    try:
                        content_data = json.loads(result['content'])
                    except json.JSONDecodeError:
                        content_data = result
                else:
                    content_data = result
            else:
                return []

            if content_data.get('success', False):
                return content_data.get('memories', [])

            return []

        except Exception as e:
            logger.warning(f"解析记忆搜索结果失败: {e}")
            return []

    async def recall(self, user_id: str, query: str, limit: int, session_id: Optional[str] = None, session_context: Optional[Any] = None) -> List[MemoryEntry]:
        if not self._available:
            return []

        try:
            result = await self.tool_manager.run_tool_async(
                tool_name='recall_user_memory',
                session_context=session_context,
                session_id=session_id,
                user_id=user_id,
                query=query,
                limit=limit
            )

            memories_data = self._parse_tool_result(result)
            return self._convert_memories_to_entries(memories_data)

        except Exception as e:
            logger.error(f"回忆记忆失败: {e}")
            return []

    async def recall_by_type(self, user_id: str, memory_type: str, query: str, limit: int, session_id: Optional[str] = None, session_context: Optional[Any] = None) -> List[MemoryEntry]:
        if not self._available:
            return []

        try:
            result = await self.tool_manager.run_tool_async(
                tool_name='recall_user_memory_by_type',
                session_context=session_context,
                session_id=session_id,
                user_id=user_id,
                memory_type=memory_type,
                query=query,
                limit=limit
            )

            memories_data = self._parse_tool_result(result)
            return self._convert_memories_to_entries(memories_data)

        except Exception as e:
            logger.error(f"按类型回忆记忆失败: {e}")
            return []

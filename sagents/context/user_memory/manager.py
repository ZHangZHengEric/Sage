"""用户记忆管理器

提供用户记忆的存储、检索、管理功能，支持多种存储后端。
"""

import traceback
import os
from typing import Dict, List, Any, Optional
from sagents.utils.logger import logger
from .schemas import MemoryEntry
from .interfaces import IMemoryDriver
from .drivers.tool import ToolMemoryDriver
from .extractor import MemoryExtractor


class UserMemoryManager:
    """用户记忆管理器
    
    作为统一的记忆管理入口，通过IMemoryDriver接口与具体的记忆后端交互。
    以user_id为索引，自动选择最佳的记忆工具实现。
    """

    def __init__(
        self,
        driver: Optional[IMemoryDriver] = None,
        model: Any = None,
        memory_root: str = "/workspace/user_memories",
    ):
        """
        初始化用户记忆管理器
        
        Args:
            driver: 自定义的记忆驱动实例（可选，如果提供则优先使用）
            model: LLM模型实例（用于记忆提取）
            memory_root: 记忆存储根目录
        """
        self.memory_root = memory_root
        if self.memory_root:
            os.environ["MEMORY_ROOT_PATH"] = self.memory_root
            logger.info(f"UserMemoryManager: 设置MEMORY_ROOT_PATH环境变量: {self.memory_root}")

        self.driver = driver
        if not self.driver:
            logger.info("UserMemoryManager 初始化完成，使用默认驱动, ToolMemoryDriver")
        else:
            logger.info(f"UserMemoryManager 初始化完成，使用自定义驱动: {self.driver.__class__.__name__}    ")

        # 初始化记忆提取器
        self.extractor = MemoryExtractor(model) if model else None

    def _get_driver(self, tool_manager: Any = None) -> Optional[IMemoryDriver]:
        """获取记忆驱动
        
        优先使用初始化的driver，如果未初始化则尝试使用tool_manager创建ToolMemoryDriver
        """
        if self.driver:
            return self.driver

        if tool_manager:
            return ToolMemoryDriver(tool_manager)

        return None

    def is_enabled(self, tool_manager: Any = None) -> bool:
        """检查记忆功能是否可用"""
        driver = self._get_driver(tool_manager)
        return driver.is_available() if driver else False

    def get_user_memory_usage_description(self) -> str:
        """获取用户记忆的使用说明"""
        return """
## 用户记忆工具使用指南

**remember_user_memory**: 记录用户偏好、个人信息、特殊要求、重要上下文、活动、和用户主动告知的信息。使用相同的key可以进行记忆的更新覆盖。
**recall_user_memory**: 检索记忆以提供个性化回答和保持对话连续性
**forget_user_memory**: 删除过时、错误或用户要求删除的记忆

**使用原则**: 主动识别有价值信息，适度记录长期内容，及时更新变化
**标签建议**: preference, work, learning, project, personal, requirement
"""

    async def extract_and_save(self, session_context: Any, session_id: str):
        """提取并保存记忆
        
        Args:
            session_context: 会话上下文
            session_id: 会话ID
        """
        if self.extractor:
            await self.extractor.extract_and_save(session_context, session_id)
        else:
            logger.debug("Memory extractor not initialized (no model provided), skipping extraction")

    def _format_memories_for_llm(self, memories: List[MemoryEntry]) -> str:
        """将MemoryEntry列表格式化为大模型友好的字符串
        
        Args:
            memories: MemoryEntry对象列表
            
        Returns:
            格式化的字符串，便于大模型理解和使用
        """
        if not memories:
            return "没有找到相关记忆。"

        formatted_lines = []
        formatted_lines.append(f"找到 {len(memories)} 条相关记忆：")
        formatted_lines.append("")

        for i, memory in enumerate(memories, 1):
            # 格式化时间
            created_time = "Unknown"
            if memory.created_at:
                created_time = memory.created_at.strftime("%Y-%m-%d %H:%M")

            # 构建简化的记忆条目
            memory_line = f"{i}. 【{memory.key}】{memory.content} ({created_time})"

            formatted_lines.append(memory_line)
            formatted_lines.append("")  # 空行分隔

        return "\n".join(formatted_lines)

    # ========== 核心记忆操作接口 ==========

    async def remember(self, user_id: str, memory_key: str, content: str, memory_type: str = "experience", tags: str = "", session_id: Optional[str] = None, session_context: Optional[Any] = None, tool_manager: Any = None) -> str:
        """记住某个记忆
        
        Args:
            user_id: 用户ID
            memory_key: 记忆键（唯一标识）
            content: 记忆内容
            memory_type: 记忆类型
            tags: 标签（逗号分隔）
            session_id: 会话ID
            session_context: 会话上下文
            tool_manager: 工具管理器（用于创建临时驱动）
            
        Returns:
            操作结果描述
        """
        driver = self._get_driver(tool_manager)
        if not driver or not driver.is_available():
            return "记忆功能已禁用：未配置记忆存储路径且无可用的MCP记忆服务"

        try:
            return await driver.remember(
                user_id=user_id,
                memory_key=memory_key,
                content=content,
                memory_type=memory_type,
                tags=tags,
                session_id=session_id,
                session_context=session_context
            )

        except Exception as e:
            logger.error(f"记住记忆失败: {e}")
            return f"记住记忆失败：{str(e)}"

    async def recall(self, user_id: str, query: str, limit: int = 5, session_id: Optional[str] = None, session_context: Optional[Any] = None, tool_manager: Any = None) -> str:
        """获取相似的记忆
        
        Args:
            user_id: 用户ID
            query: 查询内容（关键词）
            limit: 返回结果数量限制
            session_id: 会话ID
            session_context: 会话上下文
            tool_manager: 工具管理器
            
        Returns:
            格式化的记忆字符串，便于大模型理解和使用
        """
        driver = self._get_driver(tool_manager)
        if not driver or not driver.is_available():
            return "记忆功能已禁用：未配置记忆存储路径且无可用的MCP记忆服务"

        try:
            # 通过驱动获取记忆对象列表
            memory_entries = await driver.recall(
                user_id=user_id,
                query=query,
                limit=limit,
                session_id=session_id,
                session_context=session_context
            )

            if not memory_entries:
                return f"未找到与 '{query}' 相关的记忆。"

            # 格式化为大模型友好的字符串
            return self._format_memories_for_llm(memory_entries)

        except Exception as e:
            logger.error(f"回忆记忆失败: {e}")
            return f"回忆记忆失败：{str(e)}"

    async def forget(self, user_id: str, memory_key: str, session_id: Optional[str] = None, session_context: Optional[Any] = None, tool_manager: Any = None) -> str:
        """忘掉某个记忆
        
        Args:
            user_id: 用户ID
            memory_key: 要删除的记忆键
            session_id: 会话ID（可选）
            session_context: 会话上下文
            tool_manager: 工具管理器
            
        Returns:
            操作结果描述
        """
        driver = self._get_driver(tool_manager)
        if not driver or not driver.is_available():
            return "记忆功能已禁用：未配置记忆存储路径且无可用的MCP记忆服务"

        try:
            return await driver.forget(
                user_id=user_id,
                memory_key=memory_key,
                session_id=session_id,
                session_context=session_context
            )

        except Exception as e:
            logger.error(f"忘记记忆失败: {e}")
            return f"忘记记忆失败：{str(e)}"

    async def get_system_memories(self, user_id: str, session_id: Optional[str] = None, session_context: Optional[Any] = None, tool_manager: Any = None) -> dict:
        """获取系统级记忆并格式化
        
        Args:
            user_id: 用户ID
            session_id: 会话ID
            session_context: 会话上下文
            tool_manager: 工具管理器
            
        Returns:
            格式化的系统级记忆字典
        """
        driver = self._get_driver(tool_manager)
        if not driver or not driver.is_available():
            logger.info("记忆功能已禁用，跳过系统级记忆获取")
            return {}

        try:
            # 系统级记忆类型
            system_memory_types = ['preference', 'requirement', 'persona', 'constraint']
            system_memories = {}
            effective_session_id = session_id or f"memory_session_{user_id}"

            for memory_type in system_memory_types:
                try:
                    # 使用驱动按类型查询记忆
                    memories = await driver.recall_by_type(
                        user_id=user_id,
                        memory_type=memory_type,
                        query="",
                        limit=10,
                        session_id=effective_session_id,
                        session_context=session_context
                    )

                    if memories:
                        # 格式化记忆内容
                        formatted_memories = []
                        for memory in memories:
                            formatted_memories.append(f"- {memory.key}: {memory.content}")

                        if formatted_memories:
                            system_memories[memory_type] = "\n".join(formatted_memories)
                            logger.debug(f"获取了 {len(memories)} 条 {memory_type} 类型的系统记忆")

                except Exception as e:
                    logger.error(traceback.format_exc())
                    logger.warning(f"查询 {memory_type} 类型记忆失败: {e}")
                    continue

            logger.info(f"成功获取 {len(system_memories)} 种类型的系统级记忆")
            return system_memories

        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f"获取系统级记忆失败: {e}")
            return {}

    def format_system_memories_for_context(self, system_memories: dict) -> str:
        """将系统级记忆格式化为适合注入system_context的字符串
        
        Args:
            system_memories: 系统级记忆字典
            
        Returns:
            格式化的记忆字符串
        """
        if not system_memories:
            return ""

        memory_context = []

        if 'preference' in system_memories:
            memory_context.append(f"## 用户偏好\n{system_memories['preference']}")

        if 'requirement' in system_memories:
            memory_context.append(f"## 用户要求\n{system_memories['requirement']}")

        if 'persona' in system_memories:
            memory_context.append(f"## 用户人设\n{system_memories['persona']}")

        if 'constraint' in system_memories:
            memory_context.append(f"## 约束条件\n{system_memories['constraint']}")

        return "\n\n".join(memory_context) if memory_context else ""

    async def get_system_memories_summary(self, user_id: str, session_id: Optional[str] = None, tool_manager: Any = None) -> str:
        """获取系统级记忆的摘要
        
        Args:
            user_id: 用户ID
            session_id: 会话ID
            tool_manager: 工具管理器
            
        Returns:
            系统级记忆的摘要字符串
        """
        system_memories = await self.get_system_memories(user_id, session_id=session_id, tool_manager=tool_manager)
        return self.format_system_memories_for_context(system_memories)

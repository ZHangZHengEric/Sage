"""用户记忆管理器

提供用户记忆的存储、检索、管理功能，支持多种存储后端。

Author: Eric ZZ
Date: 2024-12-21
"""

import traceback
from typing import Dict, Any, List, Union
from sagents.tool.tool_manager import ToolManager
from sagents.tool.tool_proxy import ToolProxy
from sagents.utils.logger import logger
from .memory_types import MemoryEntry, MemoryType
from datetime import datetime
import json


class UserMemoryManager:
    """用户记忆管理器
    
    作为本地记忆工具和MCP记忆工具的统一使用接口。
    以user_id为索引，自动选择最佳的记忆工具实现。
    """
    
    def __init__(self, user_id: str, tool_manager: Union[ToolManager, ToolProxy] = None):
        """
        初始化用户记忆管理器
        
        Args:
            user_id: 用户唯一标识
            tool_manager: 工具管理器实例
        """
        self.user_id = user_id
        self.tool_manager = tool_manager
        
        # 验证记忆工具是否可用
        self._verify_memory_tools()
        
        logger.info(f"UserMemoryManager initialized for user: {user_id}")
    
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

    def _verify_memory_tools(self):
        """验证记忆工具是否可用"""
        try:
            if not self.tool_manager:
                self.memory_disabled = True
                logger.warning("ToolManager 未初始化，记忆工具验证跳过")
                return
            # 检查必需的记忆工具是否可用
            required_tools = ['remember_user_memory', 'recall_user_memory', 'forget_user_memory']
            missing_tools = []
            unavailable_tools = []
            
            all_tools = self.tool_manager.list_all_tools_name()
            for tool_name in required_tools:
                if tool_name not in all_tools:
                    missing_tools.append(tool_name)
                else:
                    # 检查是否为本地工具且环境变量未设置
                    tool_spec = self.tool_manager.get_tool(tool_name)
                    # 如果是本地工具（ToolSpec类型）且MEMORY_ROOT_PATH未设置
                    if hasattr(tool_spec, 'func') and not hasattr(tool_spec, 'server_name'):
                        # 这是本地工具
                        import os
                        if not os.getenv('MEMORY_ROOT_PATH'):
                            unavailable_tools.append(tool_name)
                            logger.warning(f"本地记忆工具 {tool_name} 不可用：未设置MEMORY_ROOT_PATH环境变量")
            # 计算实际不可用的工具数量
            total_unavailable = len(missing_tools) + len(unavailable_tools)
            
            if total_unavailable > 0:
                # 检查是否完全禁用记忆功能
                if total_unavailable == len(required_tools):
                    logger.warning(f"所有记忆工具都不可用，记忆功能已禁用")
                    self.memory_disabled = True
                    return
                else:
                    error_msg = []
                    if missing_tools:
                        error_msg.append(f"缺失工具: {missing_tools}")
                    if unavailable_tools:
                        error_msg.append(f"环境变量未配置: {unavailable_tools}")
                    logger.error(f"部分记忆工具不可用: {'; '.join(error_msg)}")
                    raise RuntimeError(f"记忆工具未完全配置: {'; '.join(error_msg)}")
            
            self.memory_disabled = False
            logger.info(f"记忆工具验证成功，可用工具: {required_tools}")
            
        except Exception as e:
            logger.error(f"记忆工具验证失败: {e}")
            raise
    
    # ========== 辅助方法 ==========
    
    def _convert_memories_to_entries(self, memories_data: List[Dict]) -> List[MemoryEntry]:
        """将记忆数据转换为MemoryEntry对象列表
        
        Args:
            memories_data: 从工具返回的记忆数据列表
        
        Returns:
            MemoryEntry对象列表
        """
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
                entries.append(MemoryEntry(**entry_data))
            except Exception as e:
                logger.warning(f"转换记忆条目失败: {e}, 数据: {memory_data}")
                continue
        return entries
    
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
            created_time = memory.created_at.strftime("%Y-%m-%d %H:%M")
            
            # 构建简化的记忆条目
            memory_line = f"{i}. 【{memory.key}】{memory.content} ({created_time})"
            
            formatted_lines.append(memory_line)
            formatted_lines.append("")  # 空行分隔
        
        return "\n".join(formatted_lines)
    
    # ========== 核心记忆操作接口 ==========
    
    def remember(self, memory_key: str, content: str, memory_type: str = "experience", tags: str = "", session_id: str = None) -> str:
        """记住某个记忆
        
        Args:
            memory_key: 记忆键（唯一标识）
            content: 记忆内容
            memory_type: 记忆类型（preference/requirement/persona/constraint/experience/pattern/context/note/bookmark/project/workflow/learning/skill）
            tags: 标签（逗号分隔）
            session_id: 会话ID

        Returns:
            操作结果描述
        """
        # 检查记忆功能是否被禁用
        if getattr(self, 'memory_disabled', False):
            return "记忆功能已禁用：未配置记忆存储路径且无可用的MCP记忆服务"
        
        try:
            # 统一通过tool manager调用记忆工具
            return self.tool_manager.run_tool(
                tool_name='remember_user_memory',
                session_context=None,
                session_id=session_id,
                user_id=self.user_id,
                memory_key=memory_key,
                content=content,
                memory_type=memory_type,
                tags=tags
            )
                      
        except Exception as e:
            logger.error(f"记住记忆失败: {e}")
            return f"记住记忆失败：{str(e)}"
    
    def recall(self, query: str, limit: int = 5, session_id: str = None) -> str:    
        """获取相似的记忆
        
        Args:
            query: 查询内容（关键词）
            limit: 返回结果数量限制
            session_id: 会话ID

        Returns:
            格式化的记忆字符串，便于大模型理解和使用
        """
        # 检查记忆功能是否被禁用
        if getattr(self, 'memory_disabled', False):
            return "记忆功能已禁用：未配置记忆存储路径且无可用的MCP记忆服务"
        
        try:
            # 统一通过tool manager调用记忆工具
            result = self.tool_manager.run_tool(
                tool_name='recall_user_memory',
                session_context=None,
                session_id=session_id,
                user_id=self.user_id,
                query=query,
                limit=limit
            )
            
            # 解析返回的JSON结果
            try:
                # 首先尝试解析外层JSON
                if isinstance(result, str):
                    outer_data = json.loads(result)
                    if 'content' in outer_data:
                        # 解析嵌套的JSON字符串
                        content_data = json.loads(outer_data['content'])
                    else:
                        content_data = outer_data
                elif isinstance(result, dict):
                    if 'content' in result:
                        content_data = json.loads(result['content'])
                    else:
                        content_data = result
                else:
                    return str(result)
                
                if content_data.get('success', False):
                    memories_data = content_data.get('memories', [])
                    if memories_data:
                        # 转换为MemoryEntry对象
                        memory_entries = self._convert_memories_to_entries(memories_data)
                        # 格式化为大模型友好的字符串
                        return self._format_memories_for_llm(memory_entries)
                    else:
                        return f"未找到与 '{query}' 相关的记忆。"
                else:
                    error_msg = content_data.get('error', '未知错误')
                    return f"搜索记忆失败：{error_msg}"
                    
            except (json.JSONDecodeError, KeyError) as parse_error:
                logger.warning(f"解析记忆搜索结果失败: {parse_error}")
                return str(result)
                     
        except Exception as e:
            logger.error(f"回忆记忆失败: {e}")
            return f"回忆记忆失败：{str(e)}"
    
    def forget(self, memory_key: str, session_id: str = None) -> str:
        """忘掉某个记忆
        
        Args:
            memory_key: 要删除的记忆键
        
        Returns:
            操作结果描述
        """
        # 检查记忆功能是否被禁用
        if getattr(self, 'memory_disabled', False):
            return "记忆功能已禁用：未配置记忆存储路径且无可用的MCP记忆服务"
        
        try:
            # 统一通过tool manager调用记忆工具
            return self.tool_manager.run_tool(
                tool_name='forget_user_memory',
                session_context=None,
                session_id=session_id,
                user_id=self.user_id,
                memory_key=memory_key
            )
                    
        except Exception as e:
            logger.error(f"忘记记忆失败: {e}")
            return f"忘记记忆失败：{str(e)}"
    
    def get_system_memories(self, session_id: str = None) -> dict:
        """获取系统级记忆并格式化
        
        Args:
            session_id: 会话ID
        
        Returns:
            格式化的系统级记忆字典
        """
        # 检查记忆功能是否被禁用
        if getattr(self, 'memory_disabled', False):
            logger.info("记忆功能已禁用，跳过系统级记忆获取")
            return {}
        
        try:
            # 系统级记忆类型
            system_memory_types = ['preference', 'requirement', 'persona', 'constraint']
            system_memories = {}
            effective_session_id = session_id or f"memory_session_{self.user_id}"
            
            for memory_type in system_memory_types:
                try:
                    # 使用工具管理器调用按类型查询记忆的方法
                    result = self.tool_manager.run_tool(
                        tool_name='recall_user_memory_by_type',
                        session_context=None,
                        session_id=effective_session_id,
                        user_id=self.user_id,
                        memory_type=memory_type,
                        query="",
                        limit=10
                    )
                    
                    if result and isinstance(result, str):
                        import json
                        try:
                            # 首先解析外层结构
                            outer_result = json.loads(result)
                            
                            # 检查是否有content字段（工具管理器的包装）
                            if 'content' in outer_result:
                                inner_result = json.loads(outer_result['content'])
                            else:
                                inner_result = outer_result
                            
                            if inner_result.get('success') and inner_result.get('memories'):
                                memories = inner_result['memories']
                                if memories:
                                    # 格式化记忆内容
                                    formatted_memories = []
                                    for memory in memories:
                                        formatted_memories.append(f"- {memory['key']}: {memory['content']}")
                                    
                                    if formatted_memories:
                                        system_memories[memory_type] = "\n".join(formatted_memories)
                                        logger.debug(f"获取了 {len(memories)} 条 {memory_type} 类型的系统记忆")
                        except json.JSONDecodeError as e:
                            logger.error(traceback.format_exc())
                            logger.warning(f"解析 {memory_type} 记忆结果失败: {e}")
                        except Exception as e:
                            logger.error(traceback.format_exc())
                            logger.warning(f"处理 {memory_type} 记忆结果时出错: {e}")
                            
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
    
    # 注意：记忆提取和冲突处理功能已迁移到MemoryExtractionAgent
    # 这些功能现在由sagents层面直接调用MemoryExtractionAgent来处理
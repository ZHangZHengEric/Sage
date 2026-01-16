"""记忆提取器

负责从对话中提取记忆并处理记忆冲突。
作为独立服务运行，不依赖Agent框架。

"""

import json
import re
import uuid
import traceback
from typing import List, Dict, Any, Optional, Union, cast
from openai import AsyncOpenAI

from sagents.utils.logger import logger
from sagents.context.session_context import SessionContext
from sagents.context.messages.message_manager import MessageManager
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.utils.prompt_manager import PromptManager


class MemoryExtractor:
    """记忆提取服务"""

    def __init__(self, model: AsyncOpenAI):
        """
        初始化记忆提取器
        
        Args:
            model: AsyncOpenAI实例
        """
        self.model = model

    async def extract_and_save(self, session_context: SessionContext, session_id: str):
        """提取并保存记忆（异步任务入口）
        
        Args:
            session_context: 会话上下文
            session_id: 会话ID
        """
        try:
            logger.info(f"MemoryExtractor: 开始后台记忆提取任务, session_id: {session_id}")
            
            # 获取最近的对话历史
            # 优化：只获取一次，使用最近的10轮对话，确保上下文足够但不过长
            message_manager = session_context.message_manager
            recent_messages = message_manager.extract_all_context_messages(recent_turns=10, last_turn_user_only=False)
            recent_messages_str = MessageManager.convert_messages_to_str(recent_messages)
            
            # 1. 提取记忆
            extracted_memories = await self.extract_memories_from_conversation(
                recent_messages_str, 
                session_id, 
                session_context
            )
            
            if not extracted_memories:
                logger.info("MemoryExtractor: 未提取到新记忆")
                return

            # 2. 保存新记忆
            memory_manager = session_context.user_memory_manager
            user_id = session_context.user_id
            
            if not memory_manager or not user_id:
                logger.warning("MemoryExtractor: user_memory_manager或user_id未初始化，跳过保存")
                return

            # 内部去重
            deduplicated_memories = self.deduplicate_memories(extracted_memories)
            
            for memory in deduplicated_memories:
                try:
                    await memory_manager.remember(
                        user_id=user_id,
                        memory_key=memory['key'],
                        content=memory['content'],
                        memory_type=memory['type'],
                        tags=memory.get('tags', []),
                        session_id=session_id,
                        session_context=session_context,
                        tool_manager=session_context.tool_manager
                    )
                    logger.debug(f"MemoryExtractor: 已保存记忆 {memory['key']}")
                except Exception as e:
                    logger.error(f"MemoryExtractor: 保存记忆失败 {memory.get('key')}: {e}")

            # 3. 检查并删除重复的旧记忆
            # 获取现有系统级记忆
            existing_memories = await memory_manager.get_system_memories(
                user_id=user_id,
                session_id=session_id, 
                session_context=session_context,
                tool_manager=session_context.tool_manager
            )
            
            if existing_memories:
                duplicate_keys = await self._check_and_delete_duplicate_memories(
                    existing_memories, 
                    session_id, 
                    session_context
                )
                
                # 删除重复的旧记忆
                for key in duplicate_keys:
                    await memory_manager.forget(
                        user_id=user_id,
                        memory_key=key, 
                        session_id=session_id, 
                        session_context=session_context,
                        tool_manager=session_context.tool_manager
                    )
                    
                logger.info(f"MemoryExtractor: 任务完成。提取 {len(deduplicated_memories)} 条，删除 {len(duplicate_keys)} 条重复")
            else:
                logger.info(f"MemoryExtractor: 任务完成。提取 {len(deduplicated_memories)} 条")

        except Exception as e:
            logger.error(f"MemoryExtractor: 记忆提取任务异常: {e}\n{traceback.format_exc()}")

    async def extract_memories_from_conversation(self, recent_message_str: str, session_id: str, session_context: SessionContext) -> List[Dict]:
        """从对话历史中提取潜在的系统级记忆"""
        if not recent_message_str:
            return []
            
        try:
            lang = session_context.get_language()
            
            # 构建Prompt
            system_message = self._prepare_system_message(session_context, session_id)
            extraction_prompt = PromptManager().get_agent_prompt_auto('memory_extraction_template', language=lang).format(
                formatted_conversation=recent_message_str,
                system_context=system_message
            )

            messages = [
                {"role": "user", "content": extraction_prompt}
            ]

            # 调用LLM
            response = await self.model.chat.completions.create(
                model="gpt-4o", # 优先使用更智能的模型进行提取，或者使用默认配置
                messages=messages,
                response_format={"type": "json_object"}
            )
            
            content = response.choices[0].message.content
            if not content:
                return []
                
            return self._parse_extraction_result(content)

        except Exception as e:
            logger.error(f"MemoryExtractor: LLM调用失败: {e}")
            return []

    async def _check_and_delete_duplicate_memories(self, existing_memories: Dict, session_id: str, session_context: SessionContext) -> List[str]:
        """检查并删除重复的旧记忆"""
        if not existing_memories:
            return []
            
        try:
            lang = session_context.get_language()
            
            # 格式化现有记忆用于Prompt
            # existing_memories 是 dict {type: content_str}
            # 我们需要把它传给 prompt
            
            system_message = self._prepare_system_message(session_context, session_id)
            dedup_prompt = PromptManager().get_agent_prompt_auto('memory_deduplication_template', language=lang).format(
                existing_memories=json.dumps(existing_memories, ensure_ascii=False)
            )
            
            messages = [
                {"role": "system", "content": system_message},
                {"role": "user", "content": dedup_prompt}
            ]
            
            response = await self.model.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                response_format={"type": "json_object"}
            )
            
            content = response.choices[0].message.content
            if not content:
                return []
                
            try:
                result = json.loads(content)
                return result.get('duplicate_keys', [])
            except json.JSONDecodeError:
                return []
                
        except Exception as e:
            logger.error(f"MemoryExtractor: 重复检测失败: {e}")
            return []

    def _prepare_system_message(self, session_context: SessionContext, session_id: str) -> str:
        """准备系统提示词"""
        lang = session_context.get_language()
        prefix = PromptManager().get_agent_prompt_auto('memory_extraction_system_prefix', language=lang)
        return prefix

    def _parse_extraction_result(self, llm_result: str) -> List[Dict]:
        """解析LLM的记忆提取结果"""
        try:
            try:
                data = json.loads(llm_result)
            except json.JSONDecodeError:
                # 尝试提取JSON部分
                json_match = re.search(r'\{.*\}', llm_result, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group())
                else:
                    return []

            extracted_memories = data.get('extracted_memories', [])
            
            valid_memories = []
            for memory in extracted_memories:
                if self._validate_memory_format(memory):
                    valid_memories.append(memory)
            
            return valid_memories
            
        except Exception as e:
            logger.error(f"MemoryExtractor: 解析结果失败: {e}")
            return []

    def _validate_memory_format(self, memory: Dict) -> bool:
        """验证记忆格式"""
        required_fields = ['key', 'content', 'type']
        for field in required_fields:
            if field not in memory or not str(memory[field]).strip():
                return False
        return True

    def deduplicate_memories(self, memories: List[Dict]) -> List[Dict]:
        """列表内去重"""
        unique_memories = []
        seen_keys = set()

        for memory in memories:
            if memory['key'] not in seen_keys:
                unique_memories.append(memory)
                seen_keys.add(memory['key'])

        return unique_memories

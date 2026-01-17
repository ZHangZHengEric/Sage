"""记忆提取器

负责从对话中提取记忆并处理记忆冲突。
作为独立服务运行，不依赖Agent框架。

"""

import json
import re
import uuid
import traceback
from typing import List, Dict, Any, Optional, Union, cast

from sagents.utils.logger import logger
from sagents.context.session_context import SessionContext
from sagents.context.messages.message_manager import MessageManager
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.utils.prompt_manager import PromptManager


class MemoryExtractor:
    """记忆提取服务"""

    def __init__(self, model: Any):
        """
        初始化记忆提取器
        
        Args:
            model: AsyncOpenAI实例
        """
        self.model = model

    async def extract_memories(self, recent_message_str: str, session_id: str, session_context: SessionContext) -> List[Dict]:
        """从对话历史中提取潜在的系统级记忆
        
        Args:
            recent_message_str: 最近的对话历史字符串
            session_id: 会话ID
            session_context: 会话上下文
            
        Returns:
            提取到的记忆列表
        """
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
                model=self.model.model_name,
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

    async def identify_duplicates(self, existing_memories: Dict, session_id: str, session_context: SessionContext) -> List[str]:
        """检查并识别重复的旧记忆
        
        Args:
            existing_memories: 现有的系统级记忆字典
            session_id: 会话ID
            session_context: 会话上下文
            
        Returns:
            需要删除的重复记忆key列表
        """
        if not existing_memories:
            return []
            
        try:
            lang = session_context.get_language()
            
            # 格式化现有记忆用于Prompt
            system_message = self._prepare_system_message(session_context, session_id)
            dedup_prompt = PromptManager().get_agent_prompt_auto('memory_deduplication_template', language=lang).format(
                existing_memories=json.dumps(existing_memories, ensure_ascii=False)
            )
            
            messages = [
                {"role": "system", "content": system_message},
                {"role": "user", "content": dedup_prompt}
            ]
            
            response = await self.model.chat.completions.create(
                model=self.model.model_name,
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

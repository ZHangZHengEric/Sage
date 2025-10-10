#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
记忆提取Agent

专门负责从对话中提取记忆和处理记忆冲突的Agent。
直接访问大模型，提供智能化的记忆管理服务。

Author: Eric ZZ
Date: 2024-12-21
"""

import traceback
from sagents.context.messages.message_manager import MessageManager
from .agent_base import AgentBase
from typing import Any, Dict, List, Optional, Generator
from sagents.utils.logger import logger
from sagents.tool.tool_manager import ToolManager
from sagents.context.messages.message import MessageChunk, MessageRole,MessageType
from sagents.context.session_context import SessionContext
from sagents.context.tasks.task_base import TaskBase
from sagents.context.tasks.task_manager import TaskManager
from sagents.utils.prompt_manager import PromptManager
import json
import uuid,re
from copy import deepcopy
from openai import OpenAI



class MemoryExtractionAgent(AgentBase):
    """记忆提取Agent
    
    专门负责：
    1. 从对话历史中提取潜在的系统级记忆
    2. 检测和处理记忆冲突
    3. 提供智能化的记忆管理建议
    """
    
    def __init__(self, model: Optional[OpenAI] = None, model_config: Dict[str, Any] = ..., system_prefix: str = "", max_model_len: int = 64000):
        super().__init__(model, model_config, system_prefix, max_model_len)
        self.SYSTEM_PREFIX_FIXED = PromptManager().get_agent_prompt_auto('memory_extraction_system_prefix')
        self.agent_name = "MemoryExtractionAgent"
        self.agent_description = "专门负责记忆提取和冲突处理的智能Agent"
    
    def run_stream(self, session_context: SessionContext, tool_manager: ToolManager = None, session_id: str = None) -> Generator[List[MessageChunk], None, None]:
        # 重新获取系统前缀，使用正确的语言
        self.SYSTEM_PREFIX_FIXED = PromptManager().get_agent_prompt_auto('memory_extraction_system_prefix', language=session_context.get_language())
        
        message_manager = session_context.message_manager
        memory_manager = session_context.memory_manager

        # 获取最近的对话历史
        recent_messages = message_manager.extract_all_context_messages(recent_turns=5, max_length=self.max_history_context_length)
        
        # 提取记忆
        extracted_memories = self.extract_memories_from_conversation(recent_messages, session_context)
        
        if extracted_memories:
            # 去重处理
            deduplicated_memories = self.deduplicate_memories(extracted_memories, memory_manager, session_context)
            
            # 存储记忆
            for memory in deduplicated_memories:
                memory_manager.add_memory(memory)
            
            # 返回提取结果
            result_content = f"成功提取并存储了 {len(deduplicated_memories)} 条记忆"
            yield [MessageChunk(
                role=MessageRole.ASSISTANT.value,
                content=result_content,
                message_type=MessageType.NORMAL.value
            )]
        else:
            yield [MessageChunk(
                role=MessageRole.ASSISTANT.value,
                content="未发现需要提取的新记忆",
                message_type=MessageType.NORMAL.value
            )]
        # 现获取执行的提问和执行的历史
        message_manager = session_context.message_manager
        conversation_messages = message_manager.extract_all_context_messages(recent_turns=1,max_length=self.max_history_context_length,last_turn_user_only=False)
        
        logger.debug(f"MemoryExtractionAgent: 从对话中提取记忆，对话历史: {conversation_messages}")
        recent_message_str = MessageManager.convert_messages_to_str(conversation_messages)
        # 先提取对话中的记忆
        extracted_memories = self.extract_memories_from_conversation(recent_message_str, session_id, session_context)
        # 将提取的记忆通过 session_context.user_memory_manager 存储起来
        for memory in extracted_memories:
            session_context.user_memory_manager.remember(
                memory_key=memory['key'],
                content=memory['content'],
                memory_type=memory['type'],
                tags=memory.get('tags', []),
                session_id=session_id
            )
        
        # 在现有的记忆中，判断是否要删除重复的旧的记忆
        existing_memories = session_context.user_memory_manager.get_system_memories(session_id)

        # 调用模型判断是否要删除重复的旧记忆
        duplicate_keys = self._check_and_delete_duplicate_memories(existing_memories, session_id, session_context)
        # 删除重复的旧记忆
        for key in duplicate_keys:
            session_context.user_memory_manager.forget(memory_key=key, session_id=session_id)

        # 记录执行结果到日志
        logger.info(f"MemoryExtractionAgent: 提取了 {len(extracted_memories)} 个记忆，删除了 {len(duplicate_keys)} 个重复记忆")
        
        # 输出一个表示完成的消息块，然后返回空结果
        message_id = str(uuid.uuid4())
        yield [MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="",  # 空内容，不显示给用户
            message_id=message_id,
            show_content="",  # 空显示内容
            message_type=MessageType.MEMORY_EXTRACTION.value
        )]

    # 在现有的记忆中，判断是否要删除重复的旧的记忆
    def _check_and_delete_duplicate_memories(self, existing_memories: List[Dict], session_id: str, session_context: SessionContext):
        """检查并删除重复的旧记忆"""
        if not existing_memories:
            return
        try:

            llm_request_message = [
                self.prepare_unified_system_message(session_id=session_id),
                MessageChunk(
                    role=MessageRole.USER.value,
                    content=PromptManager().get_agent_prompt_auto('memory_deduplication_template', language=session_context.get_language()).format(existing_memories=existing_memories),
                    message_id=str(uuid.uuid4()),
                    show_content=PromptManager().get_agent_prompt_auto('memory_deduplication_template', language=session_context.get_language()).format(existing_memories=existing_memories),
                    message_type=MessageType.MEMORY_EXTRACTION.value
                )
            ]
            all_response_chunks_content=  ''
            for llm_repsonse_chunk in self._call_llm_streaming(
                messages=llm_request_message,
                session_id=session_id,
                step_name="memory_duplicate_check"
            ):
                if len(llm_repsonse_chunk.choices) == 0:
                    continue
                if llm_repsonse_chunk.choices[0].delta.content:
                    if len(llm_repsonse_chunk.choices[0].delta.content) > 0:
                        all_response_chunks_content += llm_repsonse_chunk.choices[0].delta.content
                
            # 解析LLM返回结果
            try:
                duplicate_keys = json.loads(MessageChunk.extract_json_from_markdown(all_response_chunks_content))['duplicate_keys']
            except:
                logger.error(f"MemoryExtractionAgent: 解析重复记忆失败: {traceback.format_exc()}")
                logger.error(f"MemoryExtractionAgent: 解析重复记忆失败: {all_response_chunks_content}")
                duplicate_keys = []
            return duplicate_keys
        except:
            logger.error(f"MemoryExtractionAgent: 检查重复记忆失败: {traceback.format_exc()}")
            return []

    def extract_memories_from_conversation(self, recent_message_str: str, session_id: str, session_context: SessionContext) -> List[Dict]:
        """从对话历史中提取潜在的系统级记忆
        
        Args:
            recent_message_str: 最近的对话消息字符串
            session_id: 会话ID
            session_context: 会话上下文
        
        Returns:
            提取的记忆列表
        """
        if not recent_message_str:
            logger.info(f"MemoryExtractionAgent: 对话历史为空，无法提取记忆")
            return []
        try:            
            # 构建记忆提取的prompt
            extraction_prompt = PromptManager().get_agent_prompt_auto('memory_extraction_template', language=session_context.get_language()).format(
                formatted_conversation=recent_message_str,
                system_context=self.prepare_unified_system_message(session_id=session_id).content)
            
            llm_request_message = [
                # self.prepare_unified_system_message(session_id=session_id),
                MessageChunk(
                    role=MessageRole.USER.value,
                    content=extraction_prompt,
                    message_id=str(uuid.uuid4()),
                    show_content=extraction_prompt,
                    message_type=MessageType.MEMORY_EXTRACTION.value
                )
            ]
            
            all_extraction_chunks_content=  ''
            for llm_repsonse_chunk in self._call_llm_streaming(
                messages=llm_request_message,
                session_id=session_id,
                step_name="memory_extraction"
            ):
                if len(llm_repsonse_chunk.choices) == 0:
                    continue
                if llm_repsonse_chunk.choices[0].delta.content:
                    if len(llm_repsonse_chunk.choices[0].delta.content) > 0:
                        all_extraction_chunks_content += llm_repsonse_chunk.choices[0].delta.content
                
                # 解析LLM返回结果
            extracted_memories = self._parse_extraction_result(all_extraction_chunks_content)
            
            logger.info(f"MemoryExtractionAgent: 从对话中提取了 {len(extracted_memories)} 条潜在记忆")
            return extracted_memories
                
        except Exception as e:
            logger.error(f"MemoryExtractionAgent: 提取对话记忆失败: {traceback.format_exc()}")
            return []
            
    def _parse_extraction_result(self, llm_result: str) -> List[Dict]:
        """解析LLM的记忆提取结果"""
        try:
            # 处理可能的嵌套JSON结构
            inner_result = self._extract_json_from_response(llm_result)
            
            extracted_memories = inner_result.get('extracted_memories', [])
            
            # 验证提取的记忆格式
            valid_memories = []
            for memory in extracted_memories:
                if self._validate_memory_format(memory):
                    valid_memories.append(memory)
                else:
                    logger.warning(f"MemoryExtractionAgent: 跳过格式无效的记忆: {memory}")
            
            return valid_memories
            
        except Exception as e:
            logger.error(f"MemoryExtractionAgent: 解析记忆提取结果失败: {e}")
            return []
    
    def _extract_json_from_response(self, response: str) -> Dict:
        """从LLM响应中提取JSON内容"""
        try:
            # 首先尝试直接解析
            return json.loads(MessageChunk.extract_json_from_markdown(response))
        except json.JSONDecodeError:
            try:
                # 尝试提取JSON部分
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group())
                else:
                    logger.warning(f"MemoryExtractionAgent: 无法从响应中提取JSON: {response[:200]}...")
                    return {}
            except json.JSONDecodeError as e:
                logger.error(f"MemoryExtractionAgent: JSON解析失败: {e}")
                return {}
    
    def _validate_memory_format(self, memory: Dict) -> bool:
        """验证记忆格式是否正确"""
        required_fields = ['key', 'content', 'type']
        
        # 检查必需字段
        for field in required_fields:
            if field not in memory:
                return False
        
        # 检查记忆类型不为空（接受所有类型）
        if not memory['type'] or not memory['type'].strip():
            return False
        
        # 检查内容不为空
        if not memory['content'].strip():
            return False
        
        # 检查key不为空
        if not memory['key'] or not memory['key'].strip():
            return False
        
        return True
    
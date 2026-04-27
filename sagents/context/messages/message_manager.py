"""
MessageManager 优化版消息管理器

专门管理非system消息，提供完整的消息管理功能：
- 增加message chunk
- 增加完整message
- 合并message (参考agent_base.py实现)
- 过滤和压缩消息
- 获取所有消息

注意：此类不处理system消息，所有system消息会被过滤掉

作者: Eric ZZ
版本: 2.0 (优化版)
"""

import datetime
import time
import re
import uuid
import hashlib
from typing import Dict, List, Optional, Any, Union, Sequence, Tuple
from copy import deepcopy
from dataclasses import replace
from sagents.utils.logger import logger
from sagents.context.messages.context_budget import ContextBudgetManager
from .message import MessageRole, MessageType, MessageChunk

# 全局动态 token 比例计算（所有 MessageManager 实例共享）
_global_token_ratio_samples: List[Dict[str, float]] = []  # 存储字符数和token数的样本
_global_max_ratio_samples = 10  # 最多保留10个样本
_global_default_token_ratio = 0.4  # 默认比例（中文约0.6，英文约0.25，混合约0.4）

# 协议性状态工具：可持久化在 messages.json，但不参与发往 LLM 的 tool_calls/tool 对（见 strip_turn_status_from_llm_context）
TURN_STATUS_TOOL_NAME = "turn_status"


class MessageManager:
    """
    优化版消息管理器
    
    专门管理非system消息，提供完整的消息管理功能。
    不允许保存system消息，所有system消息会被自动过滤。
    """
    
    def __init__(self, session_id: Optional[str] = None,
                 max_token_limit: int = 8000,
                 compression_threshold: float = 0.7,
                 context_budget_config: Optional[Dict[str, Any]] = None):
        """
        初始化消息管理器

        Args:
            session_id: 会话ID
            max_token_limit: 最大token限制
            compression_threshold: 压缩阈值
            context_budget_config: 上下文预算管理器配置，包含以下键：
                - max_model_len: 模型最大token长度，默认 40000
                - history_ratio: 历史消息的比例（0-1之间），默认 0.2 (20%)
                - active_ratio: 活跃消息的比例（0-1之间），默认 0.3 (30%)
                - max_new_message_ratio: 新消息的比例（0-1之间），默认 0.5 (50%)
        """
        self.session_id = session_id or f"session_{uuid.uuid4().hex[:8]}"
        self.max_token_limit = max_token_limit
        self.compression_threshold = compression_threshold

        if context_budget_config is None:
            context_budget_config = {}

        self.context_budget_manager = ContextBudgetManager(
            max_model_len=context_budget_config.get('max_model_len') or 40000,
            history_ratio=context_budget_config.get('history_ratio') or 0.2,
            active_ratio=context_budget_config.get('active_ratio') or 0.3,
            max_new_message_ratio=context_budget_config.get('max_new_message_ratio') or 0.5,
        )

        # 消息存储（只存储非system消息）
        self.messages: List[MessageChunk] = []
        
        # 兼容性：保留pending_chunks属性（现在已不使用）
        self.pending_chunks: List[Any] = []

        self.active_start_index: Optional[int] = None

        # 统计信息
        self.stats: Dict[str, Any] = {
            'total_messages': 0,
            'total_chunks': 0,
            'merged_messages': 0,
            'filtered_messages': 0,
            'compressed_messages': 0,
            'system_messages_rejected': 0,
            'duplicate_content_rejected': 0,
            'created_at': datetime.datetime.now().isoformat(),
            'last_updated': datetime.datetime.now().isoformat()
        }

        # 跨 Agent 调用的签名历史（用于检测循环模式）
        # 存储最近几轮 SimpleAgent 执行的签名，支持跨调用检测 AAAA/ABAB 等模式
        self._recent_loop_signatures: List[str] = []
        self._max_loop_signatures = 24  # 保留最近24个签名
        
    
    def update_messages(self, messages: Union[MessageChunk, List[MessageChunk]]) -> None:
        """
        根据message 的id 来更新消息列表
        
        Args:
            messages: 消息列表
        """
        if isinstance(messages, MessageChunk):
            messages = [messages]
        for message in messages:
            for i, old_message in enumerate(self.messages):
                if old_message.message_id == message.message_id:
                    self.messages[i] = message
                    break

    def set_active_start_index(self, index: Optional[int]) -> None:
        """
        设置活跃消息的起始索引
        
        活跃消息指的是固定加入上下文的连续对话，从此索引开始的消息将被视为活跃消息。
        索引之前的消息将被视为历史消息，可用于相似度检索。
        
        Args:
            index: 活跃消息的起始索引，None表示所有消息都是活跃消息
        """  
        self.active_start_index = index
        logger.debug(f"MessageManager: 设置 active_start_index = {index}，"
                   f"历史消息: {index if index else 0}条，"
                   f"活跃消息: {len(self.messages) - (index if index else 0)}条")
    
    def prepare_history_split(self, agent_config: Dict[str, Any]) -> Dict[str, Any]:
        """计算 token 预算并刷新历史锚点。

        说明：active_start_index 不再由 token budget 驱动（避免在 LLM 上下文层做硬截断）。
        其语义已变更为：指向"最近一次 compress_conversation_history 工具调用"的位置，
        仅供 memory 工具划定 RAG 检索范围使用；没有压缩调用时为 None。
        本方法保留以维持 budget_info 计算（多个辅助 Agent 仍依赖它做局部规则压缩）。
        """
        budget_info = self.context_budget_manager.calculate_budget(agent_config)
        self._refresh_history_anchor_index()
        return {'budget_info': budget_info}

    def compute_history_anchor_index(self) -> Optional[int]:
        """扫描 self.messages 找到最近一次 compress_conversation_history 调用的位置。

        Returns:
            该 Assistant 调用消息的索引；未找到时返回 None。
            索引之前的消息视为"已被工具总结过的历史"，可作为 memory 检索范围；
            索引及之后的消息（含工具结果）视为活跃段。
        """
        for i in range(len(self.messages) - 1, -1, -1):
            if self._is_compress_history_tool_call(self.messages[i]):
                return i
        return None

    def _refresh_history_anchor_index(self) -> None:
        """根据最新压缩工具调用位置刷新 active_start_index（仅供 memory 使用）。"""
        self.set_active_start_index(self.compute_history_anchor_index())
    
    

    def get_recent_loop_signatures(self) -> List[str]:
        """
        获取最近的循环签名历史
        
        供 SimpleAgent 在 _execute_loop 开始时加载历史签名
        
        Returns:
            List[str]: 最近的签名列表
        """
        return self._recent_loop_signatures.copy()
    
    def add_loop_signature(self, signature: str) -> None:
        """
        添加循环签名到历史记录
        
        供 SimpleAgent 在每轮执行后记录签名
        
        Args:
            signature: 签名字符串
        """
        self._recent_loop_signatures.append(signature)
        
        # 限制列表大小，避免内存无限增长
        if len(self._recent_loop_signatures) > self._max_loop_signatures:
            self._recent_loop_signatures = self._recent_loop_signatures[-self._max_loop_signatures:]

    def clear_loop_signatures(self) -> None:
        """
        清除循环签名历史
        
        在会话重置或需要重新开始检测时调用
        """
        self._recent_loop_signatures.clear()

    def add_messages(self, messages: Union[MessageChunk, List[MessageChunk]], agent_name: Optional[str] = None) -> bool:
        """
        添加消息或消息列表
        
        Args:
            messages: 消息实例或消息列表
            agent_name: 智能体名称
        """
        if isinstance(messages, MessageChunk):
            messages = [messages]
        
        for message in messages:
            
            try:
                # 过滤system消息
                if message.role == MessageRole.SYSTEM.value:
                    self.stats['system_messages_rejected'] += 1
                    continue
                # 过滤 content 以及 tool_calls 都是空字符串或者None的消息
                if not message.content and not message.tool_calls:
                    self.stats['filtered_messages'] += 1
                    continue
            except Exception:
                logger.error(f"MessageManager: 添加消息失败，消息内容: {message}")
                continue

            self.messages = MessageManager.merge_new_message_old_messages(message,self.messages)

        self.stats['total_messages'] = len(self.messages)
        self.stats['total_chunks'] += len(messages)
        self.stats['last_updated'] = datetime.datetime.now().isoformat()

        # 新消息可能包含 compress_conversation_history 工具调用，刷新锚点
        self._refresh_history_anchor_index()
        return True
    @staticmethod
    def merge_new_messages_to_old_messages(new_messages: List[ Union[MessageChunk, Dict]],old_messages: List[Union[MessageChunk, Dict]]) -> List[MessageChunk]:
        """
        合并新消息列表和旧消息列表
        
        Args:
            new_messages: 新消息列表
            old_messages: 旧消息列表
        """
        new_messages_chunks = [MessageChunk.from_dict(msg) if isinstance(msg, dict) else msg for msg in new_messages]
        old_messages_chunks = [MessageChunk.from_dict(msg) if isinstance(msg, dict) else msg for msg in old_messages]
        for new_message in new_messages_chunks:
            old_messages_chunks = MessageManager.merge_new_message_old_messages(new_message,old_messages_chunks)
        return old_messages_chunks

    @staticmethod
    def calculate_messages_token_length(messages: Sequence[Union[MessageChunk,Dict]]) -> int:
        """
        计算消息列表的token长度, 只计算content字段
        优先使用动态比例计算，如果没有样本则使用静态规则
        
        Args:
            messages: 消息列表
            
        Returns:
            int: 消息列表的token长度
        """
        # 如果有动态比例样本，优先使用动态计算
        if _global_token_ratio_samples:
            return MessageManager._calculate_messages_token_length_dynamic(messages)
        
        # 否则使用静态规则计算
        token_length = 0
        total_chars = 0
        image_count = 0
        for message in messages:
            if isinstance(message, dict):
                message = MessageChunk.from_dict(message)
            content = message.get_content()
            # 使用 calculate_str_token_length 处理多模态消息（包含图片）
            msg_tokens = MessageManager.calculate_str_token_length(content)
            token_length += msg_tokens
            
            # 统计字符数（用于日志）
            if isinstance(content, str):
                total_chars += len(content)
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        if item.get('type') == 'text':
                            total_chars += len(item.get('text', ''))
                        elif item.get('type') == 'image_url':
                            image_count += 1
                            # 估算 base64 图片的字符数（用于日志）
                            image_url = item.get('image_url', {})
                            if isinstance(image_url, dict):
                                url = image_url.get('url', '')
                            else:
                                url = str(image_url)
                            if url.startswith('data:'):
                                base64_data = url.split(',')[-1] if ',' in url else url
                                total_chars += len(base64_data)
        
        logger.info(f"[TokenCalc] 静态计算: chars={total_chars}, tokens={token_length}, msg_count={len(messages)}, images={image_count}")
        return token_length

    @staticmethod
    def _calculate_str_token_length_static(content: str) -> int:
        """
        使用静态规则计算字符串的token长度
        一个中文等于0.6 个token，
        一个英文等于0.25个token，
        一个数字等于0.2 token
        其他符号等于0.4 token
        
        Args:
            content: 字符串内容
            
        Returns:
            int: 字符串的token长度
        """
        # 处理None或空字符串的情况
        if not content:
            return 0
            
        token_length = 0.0
        for char in content:
            # 判断是否是中文字符 (CJK统一表意文字)
            if '\u4e00' <= char <= '\u9fff':
                token_length += 0.6
            elif char.isalpha():
                token_length += 0.25
            elif char.isdigit():
                token_length += 0.2
            else:
                token_length += 0.4
        return int(token_length)

    @staticmethod
    def _extract_text_from_content(content: Union[str, List[Dict[str, Any]], None]) -> str:
        """
        从消息内容中提取文本
        支持多模态消息格式

        Args:
            content: 字符串或多模态列表

        Returns:
            str: 提取的文本内容
        """
        if content is None:
            return ""

        if isinstance(content, str):
            return content

        if isinstance(content, list):
            # 从多模态列表中提取文本内容
            text_parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
            return " ".join(text_parts)

        return str(content)

    @staticmethod
    def calculate_str_token_length(content: Union[str, List[Dict[str, Any]], None]) -> int:
        """
        计算字符串的token长度（公共静态方法）
        优先使用动态比例，如果没有样本则使用静态规则
        支持多模态消息格式（包含图片token估算）

        Args:
            content: 字符串内容或多模态列表

        Returns:
            int: 字符串的token长度
        """
        # 处理多模态消息格式
        if isinstance(content, list):
            total_tokens = 0
            for item in content:
                if isinstance(item, dict):
                    if item.get('type') == 'text':
                        # 文本内容
                        text = item.get('text', '')
                        total_tokens += MessageManager._calculate_text_token_length(text)
                    elif item.get('type') == 'image_url':
                        # 图片内容 - 估算token
                        # 对于 base64 图片，根据数据长度估算
                        # 通常一张 512x512 的图片大约需要 1000-2000 tokens
                        image_url = item.get('image_url', {})
                        if isinstance(image_url, dict):
                            url = image_url.get('url', '')
                        else:
                            url = str(image_url)

                        if url.startswith('data:'):
                            # base64 图片：根据数据长度估算
                            # base64 每4个字符 = 3字节，大约 0.75 token/字符
                            base64_data = url.split(',')[-1] if ',' in url else url
                            # 估算：base64长度 / 4 * 3 ≈ 原始字节数，再按一定比例算token
                            estimated_tokens = max(500, int(len(base64_data) * 0.2))
                            total_tokens += min(estimated_tokens, 2000)  # 上限2000 tokens
                        else:
                            # 远程URL：估算为固定值
                            total_tokens += 1000
            return total_tokens

        # 纯文本内容
        return MessageManager._calculate_text_token_length(content)

    @staticmethod
    def _calculate_text_token_length(text: Union[str, None]) -> int:
        """
        计算文本的token长度

        Args:
            text: 文本内容

        Returns:
            int: token长度
        """
        if not text:
            return 0

        text_str = str(text)

        # 如果有动态比例样本，使用动态比例
        if _global_token_ratio_samples:
            ratio = MessageManager.get_dynamic_token_ratio()
            return int(len(text_str) * ratio)

        # 否则使用静态规则
        return MessageManager._calculate_str_token_length_static(text_str)

    def update_token_ratio(self, char_count: int, actual_token_count: int) -> None:
        """
        根据实际的 LLM 响应更新 token 比例
        
        Args:
            char_count: 字符数（输入+输出的总字符数）
            actual_token_count: 实际的 token 数（从 LLM 响应中获取）
        """
        if char_count <= 0 or actual_token_count <= 0:
            return

        ratio = actual_token_count / char_count

        # 添加到全局样本列表
        global _global_token_ratio_samples
        _global_token_ratio_samples.append({
            'char_count': char_count,
            'token_count': actual_token_count,
            'ratio': ratio,
            'timestamp': time.time()
        })

        # 限制样本数量
        if len(_global_token_ratio_samples) > _global_max_ratio_samples:
            _global_token_ratio_samples.pop(0)

        logger.info(f"[TokenRatio] 更新 token 比例样本: chars={char_count}, tokens={actual_token_count}, ratio={ratio:.4f}, 总样本数={len(_global_token_ratio_samples)}")

    @staticmethod
    def get_dynamic_token_ratio() -> float:
        """
        获取动态的 token 比例（静态方法，所有实例共享）

        Returns:
            float: 基于历史样本的平均 token 比例，如果没有样本则返回默认值
        """
        global _global_token_ratio_samples, _global_default_token_ratio

        if not _global_token_ratio_samples:
            return _global_default_token_ratio

        # 计算加权平均（最近的样本权重更高）
        total_weight = 0
        weighted_sum = 0

        for i, sample in enumerate(_global_token_ratio_samples):
            weight = i + 1  # 越新的样本权重越高
            weighted_sum += sample['ratio'] * weight
            total_weight += weight

        avg_ratio = weighted_sum / total_weight if total_weight > 0 else _global_default_token_ratio

        # 限制在合理范围内（防止异常值）
        avg_ratio = max(0.1, min(1.0, avg_ratio))

        return avg_ratio

    @staticmethod
    def _calculate_messages_token_length_dynamic(messages: Sequence[Union[MessageChunk, Dict]]) -> int:
        """
        使用动态比例计算消息列表的 token 长度（静态方法）
        注意：动态比例只适用于文本内容，图片使用固定估算

        Args:
            messages: 消息列表

        Returns:
            int: 估算的 token 长度
        """
        ratio = MessageManager.get_dynamic_token_ratio()
        text_chars = 0
        image_tokens = 0
        image_count = 0

        for message in messages:
            if isinstance(message, dict):
                message = MessageChunk.from_dict(message)
            content = message.get_content()

            if isinstance(content, str):
                text_chars += len(content)
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        if item.get('type') == 'text':
                            text_chars += len(item.get('text', ''))
                        elif item.get('type') == 'image_url':
                            image_count += 1
                            # 图片使用固定估算（与静态计算一致）
                            image_url = item.get('image_url', {})
                            if isinstance(image_url, dict):
                                url = image_url.get('url', '')
                            else:
                                url = str(image_url)
                            if url.startswith('data:'):
                                base64_data = url.split(',')[-1] if ',' in url else url
                                estimated = max(500, int(len(base64_data) * 0.2))
                                image_tokens += min(estimated, 2000)
                            else:
                                image_tokens += 1000

        # 文本使用动态比例，图片使用固定估算
        text_tokens = int(text_chars * ratio)
        estimated_tokens = text_tokens + image_tokens
        logger.info(f"[TokenCalc] 动态计算: text_chars={text_chars}, image_tokens={image_tokens}, ratio={ratio:.4f}, estimated_tokens={estimated_tokens}, msg_count={len(messages)}, images={image_count}")
        return estimated_tokens

    @staticmethod
    def merge_new_message_old_messages(new_message: MessageChunk, old_messages: List[MessageChunk]) -> List[MessageChunk]:
        """
        合并新消息和旧消息
        
        Args:
            new_message: 新消息
            old_messages: 旧消息列表
        
        Returns:
            合并后的消息列表
        """
        old_messages = deepcopy(old_messages)
        new_message_id = new_message.message_id
        # 有new_message_id，查找是否已存在相同message_id的消息，如果old最后一个相同则认为找到，否则认为没有找到
        existing_message = old_messages[-1] if old_messages and old_messages[-1].message_id == new_message_id else None
        def _tool_call_to_dict(tc):
            if isinstance(tc, dict):
                return deepcopy(tc)
            return {
                'id': getattr(tc, 'id', '') or '',
                'index': getattr(tc, 'index', None),
                'type': getattr(tc, 'type', 'function') or 'function',
                'function': {
                    'name': getattr(getattr(tc, 'function', None), 'name', '') or '',
                    'arguments': getattr(getattr(tc, 'function', None), 'arguments', '') or ''
                }
            }
        if existing_message:
            # 流式消息的特点是每次传递的都是新的增量内容
            if new_message.content is not None:
                # 处理多模态消息格式 - 只对纯文本消息进行合并
                if isinstance(existing_message.content, list) or isinstance(new_message.content, list):
                    # 多模态消息不合并，直接替换
                    existing_message.content = new_message.content
                else:
                    existing_message.content = (existing_message.content or '') + new_message.content
            
            # 合并 tool_calls（流式 tool_calls 增量合并）
            if new_message.tool_calls is not None:
                if existing_message.tool_calls is None:
                    existing_message.tool_calls = []
                else:
                    existing_message.tool_calls = [_tool_call_to_dict(tc) for tc in existing_message.tool_calls]
                
                # 遍历新的 tool_calls，优先按 index 合并，其次按 id 合并
                for new_tc in new_message.tool_calls:
                    new_tc = _tool_call_to_dict(new_tc)
                    tc_id = new_tc.get('id') or ''
                    tc_index = new_tc.get('index')
                    tc_function = new_tc.get('function', {}) if isinstance(new_tc.get('function', {}), dict) else {}
                    tc_name = tc_function.get('name')
                    tc_args = tc_function.get('arguments')
                    
                    # 查找是否已存在相同 id / index 的 tool_call
                    existing_tc = None
                    existing_tc_index = -1
                    if tc_id:
                        for idx, etc in enumerate(existing_message.tool_calls):
                            etc_id = etc.get('id') if isinstance(etc, dict) else getattr(etc, 'id', None)
                            if etc_id == tc_id:
                                existing_tc = etc
                                existing_tc_index = idx
                                break
                    if existing_tc is None and tc_index is not None:
                        for idx, etc in enumerate(existing_message.tool_calls):
                            etc_index = etc.get('index') if isinstance(etc, dict) else getattr(etc, 'index', None)
                            if etc_index == tc_index:
                                existing_tc = etc
                                existing_tc_index = idx
                                break
                    if existing_tc is None and tc_index is None and existing_message.tool_calls:
                        existing_tc = existing_message.tool_calls[-1]
                        existing_tc_index = len(existing_message.tool_calls) - 1
                    
                    if existing_tc:
                        if not isinstance(existing_tc, dict):
                            existing_tc = _tool_call_to_dict(existing_tc)
                            existing_message.tool_calls[existing_tc_index] = existing_tc
                        if tc_id:
                            existing_tc['id'] = tc_id
                        if tc_index is not None and existing_tc.get('index') is None:
                            existing_tc['index'] = tc_index
                        if tc_name:
                            existing_tc.setdefault('function', {})
                            existing_tc['function']['name'] = tc_name
                        if tc_args:
                            existing_tc.setdefault('function', {})
                            existing_args = existing_tc['function'].get('arguments') or ''
                            existing_tc['function']['arguments'] = existing_args + tc_args
                    else:
                        # 添加新的 tool_call
                        existing_message.tool_calls.append(new_tc)
        else:
            old_messages.append(new_message)
            # logger.debug(f"MessageManager: 创建新消息 {new_message.message_id[:8]}... ")
        return old_messages
    
    @staticmethod
    def convert_messages_to_str(messages: List[MessageChunk]) -> str:
        """
        将消息列表转换为字符串格式
        
        Args:
            messages: 消息列表
            
        Returns:
            str: 格式化后的消息字符串
        """
        logger.info(f"AgentBase: 将 {len(messages)} 条消息转换为字符串")

        messages = MessageManager.strip_turn_status_from_llm_context(list(messages))

        messages_str_list = []
        
        for msg in messages:
            if msg is None:
                continue
            # 提取文本内容（处理多模态格式）
            content_str = MessageManager._extract_text_from_content(msg.content)
            if msg.role == 'user':
                messages_str_list.append(f"User: {content_str}")
            elif msg.role == 'assistant':
                if content_str:
                    messages_str_list.append(f"AI: {content_str}")
                elif msg.tool_calls is not None:
                    messages_str_list.append(f"AI: Tool calls: {msg.tool_calls}")
            elif msg.role == 'tool':
                messages_str_list.append(f"Tool: {content_str}")
        
        result = "\n".join(messages_str_list) or "None"
        logger.info(f"AgentBase: 转换后字符串长度: {MessageManager._calculate_str_token_length_static(result)}")
        return result

    @staticmethod
    def _is_compress_history_tool_call(msg: MessageChunk) -> bool:
        """
        判断消息是否为调用 compress_conversation_history 工具的 Assistant 消息

        Args:
            msg: 消息对象

        Returns:
            bool: 是否为调用压缩历史工具的消息
        """
        # 只检查 Assistant 角色的消息
        if msg.role != MessageRole.ASSISTANT.value:
            return False

        # 检查 tool_calls 字段
        if msg.tool_calls is None:
            return False

        for tool_call in msg.tool_calls:
            # 获取工具名称
            if hasattr(tool_call, 'function'):
                tool_name = getattr(tool_call.function, 'name', None)
            elif isinstance(tool_call, dict):
                tool_name = tool_call.get('function', {}).get('name')
            else:
                tool_name = None

            if tool_name == 'compress_conversation_history':
                return True

        return False

    @staticmethod
    def _tool_call_entry_name_and_id(tc: Any) -> Tuple[Optional[str], Optional[str]]:
        """从流式或序列化后的 tool_call 条目中解析工具名与 id。"""
        tid: Optional[str] = None
        name: Optional[str] = None
        if isinstance(tc, dict):
            tid = tc.get("id")
            fn = tc.get("function")
            if isinstance(fn, dict):
                name = fn.get("name")
        else:
            tid = getattr(tc, "id", None)
            fn = getattr(tc, "function", None)
            if fn is not None:
                name = getattr(fn, "name", None)
        return name, tid

    @staticmethod
    def _message_has_non_empty_content(msg: MessageChunk) -> bool:
        """判断 assistant/user 等是否含有可视为「有效正文」的内容（含多模态文本段）。"""
        content = msg.content
        if content is None:
            return False
        if isinstance(content, str):
            return bool(content.strip())
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    t = part.get("text") or part.get("content")
                    if isinstance(t, str) and t.strip():
                        return True
            return False
        return bool(content)

    @staticmethod
    def strip_turn_status_from_llm_context(messages: List[MessageChunk]) -> List[MessageChunk]:
        """
        从即将发往 LLM 的消息列表中移除 turn_status 工具调用及其 tool 回复。

        不影响 message_manager.messages / messages.json 中的原始记录；
        仅在构造 API 请求或 extract_messages_for_inference 出口处使用。
        """
        if not messages:
            return []

        turn_ids: set[str] = set()
        for msg in messages:
            if msg.role != MessageRole.ASSISTANT.value or not msg.tool_calls:
                continue
            for tc in msg.tool_calls:
                name, tid = MessageManager._tool_call_entry_name_and_id(tc)
                if name == TURN_STATUS_TOOL_NAME and tid:
                    turn_ids.add(tid)

        out: List[MessageChunk] = []
        for msg in messages:
            if msg.role == MessageRole.TOOL.value and msg.tool_call_id and msg.tool_call_id in turn_ids:
                continue

            if msg.role == MessageRole.ASSISTANT.value and msg.tool_calls:
                kept: List[Any] = []
                for tc in msg.tool_calls:
                    name, _tid = MessageManager._tool_call_entry_name_and_id(tc)
                    if name != TURN_STATUS_TOOL_NAME:
                        kept.append(tc)

                if not kept:
                    if MessageManager._message_has_non_empty_content(msg):
                        out.append(replace(msg, tool_calls=None))
                    # 既无正文又仅含 turn_status：整段 assist 消息不进入 LLM
                    continue

                if len(kept) == len(msg.tool_calls):
                    out.append(msg)
                else:
                    out.append(replace(msg, tool_calls=kept))
                continue

            out.append(msg)

        return out

    @staticmethod
    def extract_messages_for_inference(messages: List[MessageChunk]) -> List[MessageChunk]:
        """
        从消息列表中提取用于推理的消息
        类似 extract_all_context_messages，但用于任意输入的消息列表（而非 self.messages）

        策略：
        1. 过滤掉 REASONING_CONTENT 类型的消息
        2. 检测 compress_conversation_history 工具调用
        3. 如果找到，保留该工具调用对应的 User 消息、最后一个压缩工具及之后的消息
        4. 如果没找到，返回过滤后的所有消息

        Args:
            messages: 原始消息列表

        Returns:
            List[MessageChunk]: 提取后的消息列表
        """
        if not messages:
            return []

        # 过滤掉 REASONING_CONTENT 类型的消息
        filtered_messages = [
            msg for msg in messages
            if not msg.matches_message_types([MessageType.REASONING_CONTENT.value])
        ]

        # 从后往前查找最新的压缩工具调用
        compression_tool_index = None
        compression_tool_user_index = None

        for i in range(len(filtered_messages) - 1, -1, -1):
            msg = filtered_messages[i]
            if MessageManager._is_compress_history_tool_call(msg):
                compression_tool_index = i
                # 找到该工具调用对应的 User 消息（往前找）
                for j in range(i - 1, -1, -1):
                    if filtered_messages[j].is_user_input_message():
                        compression_tool_user_index = j
                        break
                break

        # 如果找到了压缩工具调用，构建新的消息列表
        if compression_tool_index is not None and compression_tool_user_index is not None:
            logger.info(f"MessageManager: 检测到压缩工具调用，保留 User 索引 {compression_tool_user_index} 及最后一个压缩工具")
            # 收集所有 System 消息（必须在最前面）
            system_messages = [
                msg for msg in filtered_messages
                if msg.role == MessageRole.SYSTEM.value
            ]
            # 构建新列表：System 消息 + User + 最后一个压缩工具及之后
            # 注意：如果 User 消息在压缩工具之后（不应该发生），避免重复
            if compression_tool_user_index >= compression_tool_index:
                # User 消息在压缩工具之后，只返回从 User 开始的消息
                merged = system_messages + filtered_messages[compression_tool_user_index:]
            else:
                # 正常情况：User 消息在压缩工具之前
                merged = (
                    system_messages +  # System 消息（保留）
                    [filtered_messages[compression_tool_user_index]] +  # User 消息
                    filtered_messages[compression_tool_index:]  # 最后一个压缩工具及之后
                )
            return MessageManager.strip_turn_status_from_llm_context(merged)

        # 没找到压缩工具，返回过滤后的所有消息
        return MessageManager.strip_turn_status_from_llm_context(filtered_messages)

    def extract_all_context_messages(self, recent_turns: int = 0, last_turn_user_only: bool = True, allowed_message_types: Optional[List[str]] = None) -> List[MessageChunk]:
        """
        提取所有有意义的上下文消息，包括用户消息和助手消息，最后一个消息对话，可选是否只提取用户消息，如果只提取用户消息，即是本次请求的上下文，否则带上本次执行已有内容

        注意：本方法不再按 active_start_index 做硬截断。
        发往 LLM 的最终长度控制完全交给 SimpleAgent._prepare_messages_for_llm
        中的 compress_messages / compress_conversation_history 链路统一处理。
        本方法仍会按 recent_turns 限制对话轮数（辅助 Agent 依赖此行为）。

        说明：检测 compress_conversation_history 工具调用，只取最新的压缩工具对应的 User 消息及之后的消息

        Args:
            recent_turns: 最近的对话轮数，0表示不限制
            last_turn_user_only: 是否只提取最后一个对话轮的用户消息，默认是True
            allowed_message_types: 允许保留的消息类型列表，默认为 None (使用内置默认列表)

        Returns:
            提取后的消息列表
        """
        all_context_messages = []
        chat_list = []

        # 默认允许的消息类型
        if allowed_message_types is None:
            allowed_message_types = [
                MessageType.FINAL_ANSWER.value,
                MessageType.DO_SUBTASK_RESULT.value,
                MessageType.TOOL_CALL.value,
                MessageType.TASK_ANALYSIS.value,
                MessageType.TOOL_CALL_RESULT.value,
                MessageType.SKILL_OBSERVATION.value
            ]

        # 全量消息进入；后续靠 recent_turns + 上层压缩链路控制长度
        active_messages = self.messages

        # --- 新增：检测 compress_conversation_history 工具调用 ---
        # 从后往前查找最新的压缩工具调用
        # 策略：找到最后一个压缩工具调用，然后往前找到对应的 User 消息
        # 保留该 User 消息、最后一个压缩工具及之后的消息
        # 过滤掉该 User 和最后一个压缩工具之间的其他消息（包括前面的压缩工具）
        compression_tool_index = None
        compression_tool_user_index = None

        for i in range(len(active_messages) - 1, -1, -1):
            msg = active_messages[i]
            if self._is_compress_history_tool_call(msg):
                compression_tool_index = i
                # 找到该工具调用对应的 User 消息（往前找）
                for j in range(i - 1, -1, -1):
                    if active_messages[j].is_user_input_message():
                        compression_tool_user_index = j
                        break
                break

        # 如果找到了压缩工具调用，构建新的消息列表
        # 保留：User 消息 + 最后一个压缩工具及之后的消息
        # 过滤掉：User 和最后一个压缩工具之间的其他消息
        if compression_tool_index is not None and compression_tool_user_index is not None:
            logger.info(f"MessageManager: 检测到压缩工具调用，保留 User 索引 {compression_tool_user_index} 及最后一个压缩工具")
            # 构建新列表：User + 最后一个压缩工具及之后
            # 注意：如果 User 消息在压缩工具之后（不应该发生），避免重复
            if compression_tool_user_index >= compression_tool_index:
                # User 消息在压缩工具之后，只保留从 User 开始的消息
                active_messages = active_messages[compression_tool_user_index:]
            else:
                # 正常情况：User 消息在压缩工具之前
                active_messages = (
                    [active_messages[compression_tool_user_index]] +  # User 消息
                    active_messages[compression_tool_index:]  # 最后一个压缩工具及之后
                )
        # --- 检测结束 ---
            
        for msg in active_messages:
            if msg.is_user_input_message():
                chat_list.append([msg])
            elif msg.role != MessageRole.USER.value:
                if len(chat_list) > 0:
                    chat_list[-1].append(msg)
                else:
                    chat_list.append([msg])
        if recent_turns > 0:
            chat_list = chat_list[-recent_turns:]

        # 最后一个对话，只提取用户消息
        if last_turn_user_only and len(chat_list) > 0:
            last_chat = chat_list[-1]
            all_context_messages.append(last_chat[0])
            chat_list = chat_list[:-1]
        # 合并消息（长度限制由上层 _prepare_messages_for_llm 统一控制）
        for chat in chat_list[::-1]:
            merged_messages = []
            merged_messages.append(chat[0])

            for msg in chat[1:]:
                if msg.matches_message_types(allowed_message_types):
                    merged_messages.append(msg)

            all_context_messages.extend(merged_messages[::-1])

        result_messages = all_context_messages[::-1]
        # 打印提取结果的统计信息
        total_tokens = MessageManager.calculate_messages_token_length(result_messages)
        logger.info(f"MessageManager: 提取所有上下文消息完成，最近轮数：{recent_turns}，是否只提取最后一个对话轮的用户消息：{last_turn_user_only}，消息数量：{len(result_messages)}，总token长度：{total_tokens}")
        return result_messages

    @staticmethod
    def _apply_compression_level(msg: MessageChunk, level: int) -> MessageChunk:
        """
        应用特定等级的压缩 (Level 1 / Level 2)

        Args:
            msg: 原始消息
            level: 压缩等级 (1: 轻度, 2: 强力)

        Returns:
            MessageChunk: 压缩后的消息副本
        """
        new_msg = deepcopy(msg)
        content = new_msg.content

        # 处理多模态消息格式
        if isinstance(content, list):
            # 多模态消息：压缩文本部分，保留图片（图片数据不被截断）
            new_content = []
            for item in content:
                if isinstance(item, dict):
                    if item.get('type') == 'text':
                        # 压缩文本内容
                        text = item.get('text', '')
                        if level == 1 and len(text) > 200:
                            text = text[:100] + f"\n...[Text truncated, total {len(text)} chars]...\n" + text[-100:]
                        elif level == 2 and len(text) > 100:
                            text = text[:100] + f"...[Text omitted, length: {len(text)}]"
                        new_content.append({'type': 'text', 'text': text})
                    elif item.get('type') == 'image_url':
                        # 保留图片，但在 Level 2 时替换为占位符（移除图片，不截断）
                        if level == 2:
                            # Level 2: 将图片替换为占位符描述（完整移除，不截断 base64 数据）
                            new_content.append({'type': 'text', 'text': '...[Image content omitted]...'})
                        else:
                            # Level 1: 保留完整图片数据，不截断
                            new_content.append(item)
                    else:
                        new_content.append(item)
                else:
                    new_content.append(item)
            new_msg.content = new_content
            return new_msg

        content = content or ""

        if level == 1:
            # Level 1: Tool Output 截断 (100+100), Remove Thinking
            if new_msg.role == MessageRole.TOOL.value:
                if len(content) > 200:
                    new_msg.content = content[:100] + f"\n...[Tool output truncated, total {len(content)} chars]...\n" + content[-100:]
            elif new_msg.role == MessageRole.ASSISTANT.value:
                # 移除 <thinking>
                if "<thinking>" in content:
                    new_msg.content = re.sub(r'<thinking>.*?</thinking>', '', content, flags=re.DOTALL).strip()

        elif level == 2:
            # Level 2: 强力截断 (100 chars)
            if new_msg.role == MessageRole.TOOL.value:
                if len(content) > 100:
                    new_msg.content = content[:100] + f"...[Tool output omitted, length: {len(content)}]"
            elif new_msg.role == MessageRole.ASSISTANT.value:
                if len(content) > 100:
                    new_msg.content = content[:100] + "...[Content truncated]"

        return new_msg

    @staticmethod
    def _group_messages_indices(messages: List[MessageChunk]) -> List[List[int]]:
        """
        将消息索引分组
        规则：User 消息标志着新组的开始
        Group Structure:
        - Group 0 (Maybe System/Orphan): [0, ..., k]
        - Group 1 (User+): [u1, ..., u2-1]
        """
        groups = []
        if not messages:
            return []
            
        current_group = []
        for i, msg in enumerate(messages):
            if msg.role == MessageRole.USER.value:
                if current_group:
                    groups.append(current_group)
                current_group = [i]
            else:
                current_group.append(i)
        
        if current_group:
            groups.append(current_group)
            
        return groups

    @staticmethod
    def compress_messages(messages: List[MessageChunk], budget_limit: int, time_limit_hours: float = 24.0, recent_messages_count: int = 0) -> List[MessageChunk]:
        """
        根据预算限制压缩消息列表（分层压缩策略）。

        策略详情：
        Level 0 (保护区):
            - System Message: 永久保留，不做任何处理。
            - User Message Content: User 消息的内容在 Level 1/2 阶段不被修改（受保护内容）。
            - Recent Messages (最近消息): 强制保护消息列表末尾的 recent_messages_count 条消息，
              不论其 Token 大小，始终不压缩、不截断。默认保护最近 5 条消息。

        Level 0.5 (老化策略):
            - 规则: 超过 time_limit_hours (默认24小时) 的非保护区消息。
            - 动作: 直接应用 Level 2 (强力压缩)，优先释放陈旧消息的空间。

        Level 1 (轻度压缩):
            - Tool Output: 截断保留前 100 字符 + 后 100 字符，中间省略。
            - Assistant: 移除 <thinking>...</thinking> 思考过程，保留核心回复。

        Level 2 (强力压缩):
            - 触发: Level 1 处理后仍超出 Budget。
            - Tool Output: 仅保留前 100 字符 + 占位符 "...[Tool output omitted...]"。
            - Assistant: 仅保留前 100 字符 + 占位符 "...[Content truncated]"。

        Args:
            messages: 原始消息列表。
            budget_limit: 预算限制 (Token 数)。
            time_limit_hours: 老化时间阈值 (小时)，默认 24.0。
            recent_messages_count: 末尾强制保护的消息条数，默认 5。设为 0 则不强制保护。

        Returns:
            List[MessageChunk]: 压缩后的消息列表副本。
        """
        if not messages:
            return []

        # 复制消息列表 (浅拷贝列表，元素在修改时 deepcopy)
        working_messages = deepcopy(messages)

        # 辅助函数：计算当前 Token
        def current_usage():
            return MessageManager.calculate_messages_token_length(working_messages)

        current_tokens = current_usage()
        logger.info(f"MessageManager: compress_messages 初始token长度为{current_tokens}, budget_limit={budget_limit}")
        if current_tokens <= budget_limit:
            return working_messages

        # --- 1. 分组与保护区识别 ---
        # 将消息按 User 分组，每组包含一个 User 和其后的 Followers (Assistant/Tool)
        groups = MessageManager._group_messages_indices(working_messages)

        protected_indices = set()
        protected_group_indices = set()

        # 1.1 System Group 保护 (如果第一组以 System 开头)
        if groups and working_messages[groups[0][0]].role == MessageRole.SYSTEM.value:
            protected_group_indices.add(0)
            # System 消息内容受保护
            for idx in groups[0]:
                if working_messages[idx].role == MessageRole.SYSTEM.value:
                    protected_indices.add(idx)

        # 1.2 User 消息内容保护 (在压缩阶段不截断 User 内容)
        for i, msg in enumerate(working_messages):
            if msg.role == MessageRole.USER.value:
                protected_indices.add(i)

        # 1.3 近期消息保护 - 按条数强制保护末尾 N 条消息
        # 策略：从消息列表末尾取最后 recent_messages_count 条，无论 token 大小，全部加入保护区
        if recent_messages_count > 0:
            recent_start_idx = max(0, len(working_messages) - recent_messages_count)
            for i in range(recent_start_idx, len(working_messages)):
                protected_indices.add(i)

        # 同步更新 protected_group_indices（用于日志与分组级操作）
        for gi, group_indices in enumerate(groups):
            if any(idx in protected_indices for idx in group_indices):
                protected_group_indices.add(gi)

        # 调试日志：显示保护信息
        logger.info(f"MessageManager: 总组数={len(groups)}, 受保护组数={len(protected_group_indices)}, 受保护消息数={len(protected_indices)}")
        logger.info(f"MessageManager: 受保护组索引={sorted(protected_group_indices)}, 可压缩组索引={sorted(set(range(len(groups))) - protected_group_indices)}")

        # --- Level 0.5 & 1 & 2: 消息级压缩 ---
        now = time.time()
        aging_threshold = now - (time_limit_hours * 3600)
        aged_indices = set()

        def apply_levels(level_to_apply):
            # 遍历所有消息
            for i, msg in enumerate(working_messages):
                if i in protected_indices:
                    continue

                # Level 0.5: 老化策略 (直接应用 Level 2)
                if level_to_apply == 0.5:
                    if msg.timestamp and msg.timestamp < aging_threshold:
                        working_messages[i] = MessageManager._apply_compression_level(msg, 2)
                        aged_indices.add(i)
                # Level 1: 轻度压缩
                elif level_to_apply == 1:
                    if i in aged_indices:
                        continue
                    working_messages[i] = MessageManager._apply_compression_level(working_messages[i], 1)
                # Level 2: 强力压缩
                elif level_to_apply == 2:
                    if i in aged_indices:
                        continue
                    working_messages[i] = MessageManager._apply_compression_level(working_messages[i], 2)

        # 应用 Level 0.5 (老化)
        apply_levels(0.5)
        current_tokens = current_usage()
        logger.info(f"MessageManager: compress_messages 应用Level 0.5后的token长度为{current_tokens}")
        if current_tokens <= budget_limit:
            return working_messages

        # 应用 Level 1 (轻度)
        apply_levels(1)
        current_tokens = current_usage()
        logger.info(f"MessageManager: compress_messages 应用Level 1后的token长度为{current_tokens}")
        if current_tokens <= budget_limit:
            return working_messages

        # 应用 Level 2 (强力)
        apply_levels(2)
        current_tokens = current_usage()
        logger.info(f"MessageManager: compress_messages 应用Level 2后的token长度为{current_tokens}")

        # 返回压缩后的消息（不再进行 Level 3 丢弃）
        final_tokens = MessageManager.calculate_messages_token_length(working_messages)
        logger.info(f"MessageManager: compress_messages 完成，最终token长度={final_tokens}, 消息数={len(working_messages)}")

        return working_messages

    @staticmethod
    def should_compress_messages(messages: List[MessageChunk], max_model_len: int = 40000, max_new_tokens: int = 20000) -> tuple[bool, int, int]:
        """
        判断是否需要压缩消息（静态版本，不依赖实例）

        触发条件：
        1. 剩余空间 < 20% * max_model_len
        2. 或 剩余空间 < max_new_tokens

        Args:
            messages: 消息列表
            max_model_len: 最大模型长度，默认 40000
            max_new_tokens: 最大新token数，默认 20000

        Returns:
            tuple[bool, int, int]: (是否需要压缩, 当前token数, 最大模型长度)
        """
        # 计算当前消息长度
        current_tokens = MessageManager.calculate_messages_token_length(messages)

        # 阈值判断
        remaining_tokens = max_model_len - current_tokens
        threshold_ratio = int(max_model_len * 0.2)

        should_compress = remaining_tokens < threshold_ratio or remaining_tokens < max_new_tokens

        if should_compress:
            logger.info(f"MessageManager: 上下文空间不足 (剩余 {remaining_tokens}, 当前 {current_tokens}), 需要压缩")

        return should_compress, current_tokens, max_model_len

    @staticmethod
    def convert_messages_to_dict_for_request(messages: List[MessageChunk]) -> List[Dict[str, Any]]:
        """
        将消息列表转换为字典列表
        
        注意：
        1. 此方法会过滤掉content为None的消息
        2. 此方法会过滤掉tool_call_id为None的消息
        3. 此方法会过滤掉tool_calls为None的消息
        
        Args:
            messages: 消息列表
        
        Returns:
            字典列表
        """
        messages = MessageManager.strip_turn_status_from_llm_context(messages)
        new_messages = []
        for msg in messages:
            # 去掉empty消息
            if msg.matches_message_types([MessageType.EMPTY.value]):
                logger.debug(f"DirectExecutorAgent: 过滤空消息: {msg}")
                continue
            
            # 转换 tool_calls 为字典列表
            tool_calls_dict = None
            if msg.tool_calls is not None:
                tool_calls_dict = []
                for tc in msg.tool_calls:
                    if hasattr(tc, 'id'):
                        # ChoiceDeltaToolCall 对象形式
                        tc_dict = {
                            'id': tc.id,
                            'type': tc.type if hasattr(tc, 'type') else 'function',
                            'function': {
                                'name': tc.function.name if hasattr(tc, 'function') and hasattr(tc.function, 'name') else None,
                                'arguments': tc.function.arguments if hasattr(tc, 'function') and hasattr(tc.function, 'arguments') else None
                            }
                        }
                        tool_calls_dict.append(tc_dict)
                    else:
                        # 已经是字典形式
                        tool_calls_dict.append({
                            'id': tc.get('id'),
                            'type': tc.get('type', 'function'),
                            'function': {
                                'name': tc.get('function', {}).get('name') if isinstance(tc.get('function'), dict) else None,
                                'arguments': tc.get('function', {}).get('arguments') if isinstance(tc.get('function'), dict) else None
                            }
                        })
            
            clean_msg = {
                'role': msg.role,
                'content': msg.content,
                'tool_call_id': msg.tool_call_id,
                'tool_calls': tool_calls_dict
            }
            
            # 去掉None值的键
            clean_msg = {k: v for k, v in clean_msg.items() if v is not None}
            new_messages.append(clean_msg)
        
        logger.debug(f"DirectExecutorAgent: 清理后消息数量: {len(new_messages)}")
        return new_messages

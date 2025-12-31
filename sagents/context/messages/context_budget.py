"""
动态上下文预算管理模块

负责管理和分配 token 预算，包括：
- 计算 agent_config 的 token 数量
- 按比例分配 search、history 和 max_new_token 预算
- 切分消息为 search_messages 和 active_messages

"""
import json
from typing import Dict, Any, List
from copy import deepcopy

from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.utils.logger import logger



class ContextBudgetManager:
    """上下文预算管理器"""
    def __init__(
        self,
        max_model_len: int,
        history_ratio: float,
        active_ratio: float,
        max_new_message_ratio: float,
        recent_turns: int = 0
    ):
        """初始化上下文预算管理器
        
        Args:
            max_model_len: 模型最大token长度，默认 60000
            history_ratio: 历史消息的比例（0-1之间），默认 0.2 (20%)
            active_ratio: 活跃消息的比例（0-1之间），默认 0.3 (30%)
            max_new_message_ratio: 新消息的比例（0-1之间），默认 0.5 (50%)
            recent_turns: 限制最近的对话轮数，0表示不限制，默认 0
        """
        self.max_model_len = max_model_len
        self.history_ratio = history_ratio
        self.active_ratio = active_ratio
        self.max_new_message_ratio = max_new_message_ratio
        self.recent_turns = recent_turns
        
        # 验证比例之和
        total_ratio = history_ratio + active_ratio + max_new_message_ratio
        if abs(total_ratio - 1.0) > 0.01:
            logger.warning(
                f"ContextBudgetManager: 比例之和为 {total_ratio}，建议设置为 1.0 "
                f"(history={history_ratio}, active={active_ratio}, max_new={max_new_message_ratio})"
            )
        
        logger.info(
            f"ContextBudgetManager初始化: max_len={max_model_len}, "
            f"ratios(h/a/n)={history_ratio}/{active_ratio}/{max_new_message_ratio}, "
            f"recent_turns={recent_turns}"
        )

    @staticmethod
    def calculate_str_token_length(content: str) -> int:
        """
        计算字符串的token长度, 只计算content字段。
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
        if content is None:
            return 0
            
        token_length: float = 0.0
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
    def _calculate_message_tokens(msg: MessageChunk) -> int:
        """计算单条消息的token数（私有辅助方法）"""
        content = msg.get_content()

        return ContextBudgetManager.calculate_str_token_length(content)
    
    @staticmethod
    def _calculate_messages_tokens(messages: List[MessageChunk]) -> int:
        """计算多条消息的总token数（私有辅助方法）"""
        return sum(ContextBudgetManager._calculate_message_tokens(msg) for msg in messages)
    
    @staticmethod
    def _group_messages_by_chat(messages: List[MessageChunk]) -> List[List[MessageChunk]]:
        """按对话轮次分组（私有辅助方法）"""
        chat_list = []
        for msg in messages:
            if msg.role == MessageRole.USER.value and msg.type == MessageType.NORMAL.value:
                chat_list.append([msg])
            elif msg.role != MessageRole.USER.value:
                if chat_list:
                    chat_list[-1].append(msg)
                else:
                    chat_list.append([msg])
        
        return chat_list
    
    def calculate_budget(self, agent_config: Dict[str, Any]) -> Dict[str, int]:
        """计算上下文 token 预算分配"""

        config_str = json.dumps(agent_config, ensure_ascii=False) if agent_config else ""
        agent_config_tokens = ContextBudgetManager.calculate_str_token_length(config_str)
        
        # 计算可用 token
        available_tokens = max(0, self.max_model_len - agent_config_tokens)
        
        if available_tokens <= 0:
            logger.error(
                f"ContextBudgetManager: agent_config过长({agent_config_tokens}), "
                f"超过模型最大长度({self.max_model_len})"
            )
            return {
                'agent_config_tokens': agent_config_tokens,
                'available_tokens': 0,
                'history_budget': 0,
                'active_budget': 0,
                'max_new_tokens': 0
            }
        
        # 按比例分配
        budget_info = {
            'agent_config_tokens': agent_config_tokens,
            'available_tokens': available_tokens,
            'history_budget': int(available_tokens * self.history_ratio),
            'active_budget': int(available_tokens * self.active_ratio),
            'max_new_tokens': int(available_tokens * self.max_new_message_ratio)
        }
        
        logger.info(
            f"ContextBudgetManager: 预算分配 - 可用={available_tokens}, "
            f"history={budget_info['history_budget']}, "
            f"active={budget_info['active_budget']}, "
            f"max_new={budget_info['max_new_tokens']}"
        )
        
        return budget_info
    
    def split_messages(
        self, 
        messages: List[MessageChunk],
        active_budget: int
    ) -> Dict[str, Any]:
        """按 token 预算切分消息为 history 和 active 两部分"""
        # 按对话轮次分组
        chat_list = self._group_messages_by_chat(messages)

        # 限制最近轮次
        if self.recent_turns > 0:
            chat_list = chat_list[-self.recent_turns:]
        
        if not chat_list:
            return {
                'history_messages': [],
                'active_messages': [],
                'history_tokens': 0,
                'active_tokens': 0
            }
        
        # 从最新对话开始，填充 active_messages
        active_messages: List[MessageChunk] = []
        active_tokens = 0
        active_count = 0
        
        for chat in reversed(chat_list):
            chat_tokens = self._calculate_messages_tokens(chat)

            if active_tokens + chat_tokens <= active_budget or active_count == 0:
                active_messages = chat + active_messages
                active_tokens += chat_tokens
                active_count += 1
                if active_tokens > active_budget and active_count == 1:
                    logger.warning(
                        f"ContextBudgetManager: 最后一轮对话({chat_tokens}tokens)"
                        f"超出active预算({active_budget}), 强制保留"
                    )
                    break
            else:
                break
        
        # 剩余消息作为 history
        history_messages = []
        for i in range(len(chat_list) - active_count):
            history_messages.extend(chat_list[i])
        
        history_tokens = self._calculate_messages_tokens(history_messages)
        
        logger.info(
            f"ContextBudgetManager: 消息切分 - 总轮次={len(chat_list)}, "
            f"active={len(active_messages)}条/{active_tokens}tokens, "
            f"history={len(history_messages)}条/{history_tokens}tokens"
        )
        
        return {
            'history_messages': deepcopy(history_messages),
            'active_messages': deepcopy(active_messages),
            'history_tokens': history_tokens,
            'active_tokens': active_tokens
        }

# cd /data/wangxinhao/reagent && python -m sagents.context.messages.context_budget
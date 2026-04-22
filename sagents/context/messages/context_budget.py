"""
动态上下文预算管理模块

负责按比例分配 history / active / max_new token 预算，
供辅助 Agent 通过 budget_info 读取后做局部规则压缩。
"""
import json
from typing import Dict, Any

from sagents.utils.logger import logger



class ContextBudgetManager:
    """上下文预算管理器"""
    def __init__(
        self,
        max_model_len: int,
        history_ratio: float,
        active_ratio: float,
        max_new_message_ratio: float,
    ):
        """初始化上下文预算管理器

        Args:
            max_model_len: 模型最大token长度，默认 60000
            history_ratio: 历史消息的比例（0-1之间），默认 0.2 (20%)
            active_ratio: 活跃消息的比例（0-1之间），默认 0.3 (30%)
            max_new_message_ratio: 新消息的比例（0-1之间），默认 0.5 (50%)
        """
        self.max_model_len = max_model_len
        self.history_ratio = history_ratio
        self.active_ratio = active_ratio
        self.max_new_message_ratio = max_new_message_ratio

        total_ratio = history_ratio + active_ratio + max_new_message_ratio
        if abs(total_ratio - 1.0) > 0.01:
            logger.warning(
                f"ContextBudgetManager: 比例之和为 {total_ratio}，建议设置为 1.0 "
                f"(history={history_ratio}, active={active_ratio}, max_new={max_new_message_ratio})"
            )

        logger.debug(
            f"ContextBudgetManager初始化: max_len={max_model_len}, "
            f"ratios(h/a/n)={history_ratio}/{active_ratio}/{max_new_message_ratio}"
        )
        self.budget_info = None

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


    def calculate_budget(self, agent_config: Dict[str, Any] = None) -> Dict[str, int]:
        """计算上下文 token 预算分配"""
        if self.budget_info is not None and agent_config is None:
            return self.budget_info

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
                'max_new_tokens': 0,
                'max_model_len': self.max_model_len
            }
        
        # 按比例分配
        budget_info = {
            'agent_config_tokens': agent_config_tokens,
            'available_tokens': available_tokens,
            'history_budget': int(available_tokens * self.history_ratio),
            'active_budget': int(available_tokens * self.active_ratio),
            'max_new_tokens': int(available_tokens * self.max_new_message_ratio),
            'max_model_len': self.max_model_len
        }
        
        logger.debug(
            f"ContextBudgetManager: 预算分配 - 可用={available_tokens}, "
            f"history={budget_info['history_budget']}, "
            f"active={budget_info['active_budget']}, "
            f"max_new={budget_info['max_new_tokens']}"
        )
        
        self.budget_info = budget_info
        return budget_info

import uuid
import time
from typing import Dict, Any, Optional, List, Union
from dataclasses import dataclass, asdict
from enum import Enum
import json
import re
from sagents.utils.logger import logger

class MessageRole(Enum):
    """消息角色枚举"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


LEGACY_NORMAL_MESSAGE_TYPE = "normal"


def normalize_legacy_message_type(role: Optional[str], message_type: Optional[str]) -> Optional[str]:
    """兼容历史消息类型。

    仅用于读取旧数据：
    - user 的普通消息统一视为 `user_input`
    - assistant 的历史 `normal` 统一视为 `assistant_text`
    """
    if role == MessageRole.USER.value:
        return MessageType.USER_INPUT.value
    if role == MessageRole.ASSISTANT.value and message_type == LEGACY_NORMAL_MESSAGE_TYPE:
        return MessageType.ASSISTANT_TEXT.value
    return message_type


class MessageType(Enum):
    """消息类型枚举 - 与项目实际使用保持一致"""
    # 基础类型
    USER_INPUT = "user_input"
    ASSISTANT_TEXT = "assistant_text"
    REWRITE = "rewrite"
    TASK_ANALYSIS = "task_analysis"
    TASK_DECOMPOSITION = "task_decomposition"
    PLANNING = "planning"
    EXECUTION = "execution"  # 执行阶段时assistant 的任务描述使用
    OBSERVATION = "observation"
    TASK_COMPLETION_JUDGE = "task_completion_judge"
    FINAL_ANSWER = "final_answer"
    SYSTEM = "system"
    QUERY_SUGGEST = "query_suggest"
    MEMORY_EXTRACTION = "memory_extraction"
    DO_SUBTASK_RESULT = "do_subtask_result"

    # 推理内容
    REASONING_CONTENT = "reasoning_content"

    # 工具相关
    TOOL_CALL = "tool_call"
    TOOL_CALL_RESULT = "tool_call_result"  # 兼容现有代码

    # 技能相关
    SKILL_SELECT_RESULT = "skill_select_result"
    SKILL_EXEC_PLAN = "skill_exec_plan"
    SKILL_EXEC_TOOL_CALL = "skill_exec_tool_call"
    SKILL_EXEC_TOOL_CALL_RESULT = "skill_exec_tool_call_result"
    SKILL_EXEC_RESULT = "skill_exec_result"

    SKILL_OBSERVATION = "skill_observation"
    # 其他类型
    THINKING = "thinking"
    ERROR = "error"
    CHUNK = "chunk"
    GUIDE = "guide"
    # 特殊类型
    HANDOFF_AGENT = "handoff_agent"
    STAGE_SUMMARY = "stage_summary"
    TOKEN_USAGE = "token_usage"
    # 空数据
    EMPTY = "empty"
    # 循环熔断：连续相同错误导致自动暂停，前端可用特殊样式展示
    LOOP_BREAK = "loop_break"


@dataclass
class MessageChunk:
    """消息块结构类 - OpenAI兼容格式
    
    定义Agent流式返回的单个消息块的结构，确保所有必要字段都存在。
    支持OpenAI消息格式和工具调用。
    """
    
    # 必需字段 - OpenAI标准
    role: str  # 消息角色 (user, assistant, system, tool)
    
    # 内容字段（content和tool_calls至少有一个）
    # content 可以是字符串或列表（支持多模态，如图片+文本）
    # 列表格式: [{"type": "text", "text": "..."}, {"type": "image_url", "image_url": {"url": "..."}}]
    content: Optional[Union[str, List[Dict[str, Any]]]] = None  # 消息内容
    tool_calls: Optional[List[Dict[str, Any]]] = None  # 工具调用列表（OpenAI格式）
    
    # 消息标识
    message_id: Optional[str] = None  # 消息唯一标识符
    
    # 工具调用ID（tool角色消息必需）
    tool_call_id: Optional[str] = None  # 工具调用ID（tool角色消息必需）
    
    # 显示和类型字段
    type: Optional[str] = None  # 消息类型（兼容现有系统）
    message_type: Optional[str] = None  # 消息类型（备用字段）
    
    # 时间戳
    timestamp: Optional[float] = None  # 时间戳
    
    # 元数据字段
    agent_name: Optional[str] = None  # 生成消息的Agent名称
    agent_type: Optional[str] = None  # Agent类型
    chunk_id: Optional[str] = None  # 消息块ID（用于流式传输）
    is_final: bool = False  # 是否为最终消息块
    is_chunk: bool = False  # 是否为消息块
    
    # 扩展字段
    metadata: Optional[Dict[str, Any]] = None  # 额外的元数据
    error_info: Optional[Dict[str, Any]] = None # 错误信息
    session_id: Optional[str] = None  # 会话ID
    
    # 其他兼容字段
    updated_at: Optional[str] = None  # 更新时间
    
    def __post_init__(self):
        """初始化后处理"""
        if self.timestamp is None:
            self.timestamp = time.time()
        if self.chunk_id is None:
            self.chunk_id = str(uuid.uuid4())
        if self.message_id is None :
            self.message_id = str(uuid.uuid4())
        if len(self.message_id) == 0:
            self.message_id = str(uuid.uuid4())

        # 统一type字段
        if self.type is None and self.message_type is not None:
            self.type = self.message_type
        elif self.message_type is None and self.type is not None:
            self.message_type = self.type

        role = self.role.value if isinstance(self.role, MessageRole) else self.role
        # 统一为字符串，避免 role 仍为 MessageRole 枚举时与 ".value" 比较恒为 False（SSE redact、LLM strip 等全部失效）
        self.role = role

        # 统一基础文本消息语义，兼容历史 normal。
        if role == MessageRole.USER.value:
            self.type = MessageType.USER_INPUT.value
            self.message_type = self.type
        elif role == MessageRole.ASSISTANT.value and self.normalized_message_type() in {None, MessageType.ASSISTANT_TEXT.value}:
            self.type = MessageType.ASSISTANT_TEXT.value
            self.message_type = self.type
        
        # 验证必需字段
        if role == MessageRole.TOOL.value and self.tool_call_id is None:
            raise ValueError("tool角色的消息必须包含tool_call_id字段")
        
        if self.content is None and self.tool_calls is None:
            raise ValueError("消息必须包含content或tool_calls字段")
        
        if self.metadata is None:
            self.metadata = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式（保持向后兼容性）
        
        Returns:
            Dict[str, Any]: 字典格式的消息块
        """
        result = asdict(self)
        
        # 确保role字段是字符串 - 处理asdict后的枚举对象
        if 'role' in result and hasattr(result['role'], 'value'):
            result['role'] = result['role'].value
        elif isinstance(self.role, MessageRole):
            result['role'] = self.role.value
            
        # 确保type和message_type字段是字符串 - 处理MessageType枚举
        for field_name in ['type', 'message_type']:
            if field_name in result and result[field_name] is not None:
                if hasattr(result[field_name], 'value'):
                    result[field_name] = result[field_name].value
                elif isinstance(result[field_name], MessageType):
                    result[field_name] = result[field_name].value
        
        # 处理 tool_calls 字段 - 转换为标准字典格式
        if 'tool_calls' in result and result['tool_calls'] is not None:
            result['tool_calls'] = self._serialize_tool_calls(result['tool_calls'])
        
        # 移除None值以保持简洁
        return {k: v for k, v in result.items() if v is not None}
    
    def _serialize_tool_calls(self, tool_calls) -> List[Dict[str, Any]]:
        """序列化 tool_calls 为标准字典格式"""
        if tool_calls is None:
            return None
        
        result = []
        for tc in tool_calls:
            if hasattr(tc, 'id') and hasattr(tc, 'function'):
                # 对象形式 (如 ChoiceDeltaToolCall)
                tc_dict = {'id': tc.id, 'type': getattr(tc, 'type', 'function')}
                # OpenAI 流式增量 delta 中 index 至关重要：同一条 assistant 消息里
                # 多个 tool_call 在分片时仅靠 index 区分，丢失会导致前端把后续
                # 工具的参数累加到上一个工具上，进而出现"参数收集不到"或"工具消失"。
                tc_index = getattr(tc, 'index', None)
                if tc_index is not None:
                    tc_dict['index'] = tc_index
                function = tc.function if hasattr(tc, 'function') else None
                if function:
                    tc_dict['function'] = {
                        'name': getattr(function, 'name', ''),
                        'arguments': getattr(function, 'arguments', '')
                    }
                result.append(tc_dict)
            elif isinstance(tc, dict):
                # 字典形式 - 原样透传，保留 index 等额外字段
                result.append(tc)
            else:
                # 其他形式，转换为字符串
                result.append(str(tc))
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MessageChunk':
        """从字典创建MessageChunk实例
        
        Args:
            data: 字典格式的消息数据
            
        Returns:
            MessageChunk: 消息块实例
        """
        # 确保role字段存在
        if 'role' not in data:
            raise ValueError("Missing required field: role")
        
        # 自动生成message_id如果不存在
        if 'message_id' not in data or data['message_id'] is None:
            data['message_id'] = str(uuid.uuid4())
        
        # 只传递类中定义的字段
        valid_fields = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        
        return cls(**valid_fields)
    
    def validate(self) -> bool:
        """验证消息块的有效性
        
        Returns:
            bool: 是否有效
        """
        # 检查必需字段
        if not all([self.role, self.message_id is not None]):
            return False
        
        # 检查角色是否有效
        valid_roles = [role.value for role in MessageRole]
        if self.role not in valid_roles:
            return False
        
        return True

    def get_content(self) -> Optional[str]:
        """获取消息内容
        
        Returns:
            Optional[str]: 消息内容
        """
        return self.content

    def normalized_message_type(self) -> Optional[str]:
        """返回规范化后的消息类型。

        规则：
        - user 普通输入统一视为 `user_input`
        - assistant 的历史 `normal` 统一视为 `assistant_text`
        - 已有明确业务语义的 assistant type 保持原样
        """
        role = self.role.value if isinstance(self.role, MessageRole) else self.role
        message_type = self.message_type or self.type

        return normalize_legacy_message_type(role, message_type)

    def matches_message_types(self, allowed_types: List[str]) -> bool:
        """判断消息是否匹配给定类型集合。

        会优先用规范化后的 type 匹配，并兼容历史 `normal` 数据。
        """
        message_type = self.message_type or self.type
        normalized_type = self.normalized_message_type()
        return normalized_type in allowed_types or message_type in allowed_types

    def is_user_input_message(self) -> bool:
        """是否为用户输入消息。

        新数据统一使用 `user_input`。历史数据通过 role 兼容识别。
        """
        role = self.role.value if isinstance(self.role, MessageRole) else self.role
        return role == MessageRole.USER.value

    def is_assistant_text_message(self) -> bool:
        """是否为助手文本消息。

        新数据统一使用 `assistant_text`，同时兼容历史 `normal`。
        """
        role = self.role.value if isinstance(self.role, MessageRole) else self.role
        message_type = self.normalized_message_type()
        return role == MessageRole.ASSISTANT.value and message_type in {
            MessageType.ASSISTANT_TEXT.value,
            MessageType.FINAL_ANSWER.value,
        }

    @classmethod
    def extract_json_from_markdown(cls, content: str) -> str:
        """
        从markdown代码块中提取JSON内容
        Args:
            content: 可能包含markdown代码块的内容
        Returns:
            str: 提取的JSON内容，如果没有找到代码块则返回原始内容
        """
        logger.debug("AgentBase: 尝试从内容中提取JSON")
        
        # 首先尝试直接解析
        try:
            json.loads(content)
            return content
        except json.JSONDecodeError:
            pass
        # 尝试从markdown代码块中提取
        code_block_pattern = r'```(?:json)?\n([\s\S]*?)\n```'
        match = re.search(code_block_pattern, content)
        if match:
            try:
                json.loads(match.group(1))
                logger.debug("成功从markdown代码块中提取JSON")
                return match.group(1)
            except json.JSONDecodeError:
                logger.warning("解析markdown代码块中的JSON失败")
                pass
        logger.debug("未找到有效JSON，返回原始内容")
        return content

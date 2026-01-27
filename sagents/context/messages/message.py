import uuid
import time
from typing import Dict, Any, Optional, List
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


class MessageType(Enum):
    """消息类型枚举 - 与项目实际使用保持一致"""
    # 基础类型
    NORMAL = "normal"
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
    TASK_ROUTER = "task_router"
    DO_SUBTASK_RESULT = "do_subtask_result"

    # 工具相关
    TOOL_CALL = "tool_call"
    TOOL_CALL_RESULT = "tool_call_result"  # 兼容现有代码

    # 技能相关
    SKILL_SELECT_RESULT = "skill_select_result"
    SKILL_EXECUTION_PLAN = "skill_execution_plan"
    SKILL_EXECUTION_RESULT = "skill_execution_result"
    SKILL_OBSERVATION = "skill_observation"
    SKILL_MISS = "skill_miss"
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


@dataclass
class MessageChunk:
    """消息块结构类 - OpenAI兼容格式
    
    定义Agent流式返回的单个消息块的结构，确保所有必要字段都存在。
    支持OpenAI消息格式和工具调用。
    """
    
    # 必需字段 - OpenAI标准
    role: str  # 消息角色 (user, assistant, system, tool)
    
    # 内容字段（content和tool_calls至少有一个）
    content: Optional[str] = None  # 消息内容
    tool_calls: Optional[List[Dict[str, Any]]] = None  # 工具调用列表（OpenAI格式）
    
    # 消息标识
    message_id: Optional[str] = None  # 消息唯一标识符
    
    # 工具相关字段
    tool_call_id: Optional[str] = None  # 工具调用ID（tool角色消息必需）
    
    # 显示和类型字段
    show_content: Optional[str] = None  # 显示内容（用于前端展示）
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


        # 如果role 是user 类型，type 必须是normal
        if self.role == MessageRole.USER.value:
            self.type = MessageType.NORMAL.value

        # 统一type字段
        if self.type is None and self.message_type is not None:
            self.type = self.message_type
        elif self.message_type is None and self.type is not None:
            self.message_type = self.type
        
        # 验证必需字段
        if self.role == MessageRole.TOOL.value and self.tool_call_id is None:
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
        
        # 移除None值以保持简洁
        return {k: v for k, v in result.items() if v is not None}
    
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
        
        优先返回 show_content，如果不存在则返回 content
        
        Returns:
            Optional[str]: 消息内容
        """
        return self.show_content if self.show_content else self.content

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

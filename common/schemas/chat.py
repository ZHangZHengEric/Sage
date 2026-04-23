from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


class Message(BaseModel):
    message_id: Optional[str] = None
    role: str
    # content 可以是字符串或列表（支持多模态，如图片+文本）
    # 列表格式: [{"type": "text", "text": "..."}, {"type": "image_url", "image_url": {"url": "..."}}]
    content: Optional[Union[str, List[Dict[str, Any]]]] = None


class BaseChatRequest(BaseModel):
    """基础聊天请求，包含公共字段（server/desktop 共享）"""

    messages: List[Message]
    session_id: Optional[str] = None
    # server 有 user_id，desktop 目前没有；这里以 server 为准，并设为可选
    user_id: Optional[str] = None
    system_context: Optional[Dict[str, Any]] = None

    def __init__(self, **data: Any):  # type: ignore[override]
        super().__init__(**data)
        # 确保 messages 中的每个消息都有 role 和 content
        if self.messages:
            for i, msg in enumerate(self.messages):
                if isinstance(msg, dict):
                    # 如果是字典，转换为 Message 对象
                    self.messages[i] = Message(**msg)
                elif not hasattr(msg, "role") or not hasattr(msg, "content"):
                    raise ValueError(f"消息 {i} 缺少必要的 'role' 或 'content' 字段")


class CustomSubAgentConfig(BaseModel):
    # desktop 的版本有 agent_id，server 的版本没有；这里取并集
    agent_id: Optional[str] = None
    name: str
    system_prompt: Optional[str] = None
    description: Optional[str] = None
    available_tools: Optional[List[str]] = None
    available_skills: Optional[List[str]] = None
    available_workflows: Optional[Dict[str, List[str]]] = None
    system_context: Optional[Dict[str, Any]] = None


class StreamRequest(BaseChatRequest):
    """流式请求，包含所有流式控制参数（server/desktop 共享）"""

    agent_id: Optional[str] = None
    agent_name: Optional[str] = None
    deep_thinking: Optional[bool] = Field(
        default=None,
        deprecated=True,
        description="已过时。请改用消息中的 <enable_deep_thinking>true/false</enable_deep_thinking> 控制。",
    )
    max_loop_count: Optional[int] = None
    multi_agent: Optional[bool] = None
    agent_mode: Optional[str] = None
    more_suggest: Optional[bool] = None
    available_workflows: Optional[Dict[str, List[str]]] = None
    llm_model_config: Optional[Dict[str, Any]] = None
    system_prefix: Optional[str] = None
    available_tools: Optional[List[str]] = None
    available_skills: Optional[List[str]] = None
    # server 独有：知识库列表
    available_knowledge_bases: Optional[List[str]] = None
    available_sub_agent_ids: Optional[List[str]] = None
    force_summary: Optional[bool] = False
    # server/desktop 都有 memory_type，server 命名为 canonical
    memory_type: Optional[str] = "session"
    custom_sub_agents: Optional[List[CustomSubAgentConfig]] = None
    context_budget_config: Optional[Dict[str, Any]] = None
    # 额外的 mcp 配置
    extra_mcp_config: Optional[Dict[str, Dict[str, Any]]] = None
    # 内部使用：标记本次执行来源与开始时间，不参与外部序列化
    request_source: Optional[str] = Field(default=None, exclude=True)
    execution_started_at: Optional[datetime] = Field(default=None, exclude=True)


class ChatRequest(BaseChatRequest):
    """普通聊天请求，主要用于从 AgentID 初始化"""

    agent_id: str


class DisplayContextMessage(BaseModel):
    role: str
    content: str


class UserInputOptimizeRequest(BaseModel):
    current_input: str
    history_messages: List[DisplayContextMessage] = Field(default_factory=list)
    session_id: Optional[str] = None
    agent_id: Optional[str] = None
    user_id: Optional[str] = None

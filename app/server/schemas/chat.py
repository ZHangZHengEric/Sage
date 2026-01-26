from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel


class Message(BaseModel):
    role: str
    content: Union[str, List[Dict[str, Any]]]

class BaseChatRequest(BaseModel):
    """基础聊天请求，包含公共字段"""
    messages: List[Message]
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    system_context: Optional[Dict[str, Any]] = None
    
    def __init__(self, **data):
        super().__init__(**data)
        # 确保 messages 中的每个消息都有 role 和 content
        if self.messages:
            for i, msg in enumerate(self.messages):
                if isinstance(msg, dict):
                    # 如果是字典，转换为 Message 对象
                    self.messages[i] = Message(**msg)
                elif not hasattr(msg, "role") or not hasattr(msg, "content"):
                    raise ValueError(f"消息 {i} 缺少必要的 'role' 或 'content' 字段")

class StreamRequest(BaseChatRequest):
    """流式请求，包含所有流式控制参数"""
    agent_id: Optional[str] = None
    agent_name: Optional[str] = None
    deep_thinking: Optional[bool] = None
    max_loop_count: Optional[int] = 10
    multi_agent: Optional[bool] = None
    more_suggest: Optional[bool] = None
    available_workflows: Optional[Dict[str, List[str]]] = None
    llm_model_config: Optional[Dict[str, Any]] = None
    system_prefix: Optional[str] = None
    available_tools: Optional[List[str]] = None
    available_skills: Optional[List[str]] = None
    force_summary: Optional[bool] = False


class ChatRequest(BaseChatRequest):
    """普通聊天请求，主要用于从 AgentID 初始化"""
    agent_id: str

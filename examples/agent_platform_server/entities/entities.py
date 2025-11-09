"""
统一的响应模型和数据模型

提供标准化的API响应格式和数据模型定义
"""

from typing import List, Dict, Any, Optional, Union
from pydantic import BaseModel
from fastapi import HTTPException
import time


# ============= 自定义异常类 =============

class SageHTTPException(HTTPException):
    """自定义HTTP异常，支持更多错误信息"""
    def __init__(self, status_code: int, detail: str, error_detail: str = None):
        super().__init__(status_code=status_code, detail=detail)
        self.error_detail = error_detail


# ============= 统一响应模型 =============

class StandardResponse(BaseModel):
    """标准API响应格式"""
    code: int = 200
    message: str = "success"
    data: Optional[Any] = None
    timestamp: Optional[float] = None
    
    def __init__(self, **data):
        if 'timestamp' not in data:
            data['timestamp'] = time.time()
        super().__init__(**data)

class ErrorResponse(BaseModel):
    """错误响应格式"""
    code: int
    message: str
    error_detail: Optional[str] = None
    timestamp: Optional[float] = None
    
    def __init__(self, **data):
        if 'timestamp' not in data:
            data['timestamp'] = time.time()
        super().__init__(**data)


# ============= 工具相关模型 =============

class ToolInfo(BaseModel):
    name: str
    description: str
    parameters: Dict[str, Any]
    type: str  # 工具类型：basic, mcp, agent
    source: str  # 工具来源

class ExecToolRequest(BaseModel):
    tool_name: str
    tool_params: Dict[str, Any]


# ============= 会话相关模型 =============

class ConversationInfo(BaseModel):
    """会话信息模型"""
    session_id: str
    user_id: str
    agent_id: str
    agent_name: str
    title: str
    message_count: int
    user_count: int
    agent_count: int
    created_at: str
    updated_at: str

class PaginatedResponse(BaseModel):
    """分页响应模型"""
    list: List[Any]
    total: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_prev: bool

class ConversationListRequest(BaseModel):
    """会话列表查询请求"""
    page: int = 1
    page_size: int = 10
    user_id: Optional[str] = None


# ============= MCP相关模型 =============

class MCPServerRequest(BaseModel):
    name: str
    protocol: str  # 协议类型：streamable_http, sse
    streamable_http_url: Optional[str] = None
    sse_url: Optional[str] = None
    api_key: Optional[str] = None
    disabled: bool = False



# ============= Agent相关模型 =============

class AgentConfig(BaseModel):
    id:  Optional[str] = None
    name: str
    systemPrefix: Optional[str] = None
    systemContext: Optional[Dict[str, Any]] = None
    availableWorkflows: Optional[Dict[str, List[str]]] = None
    availableTools: Optional[List[str]] = None
    maxLoopCount: Optional[int] = 10
    deepThinking: Optional[bool] = False
    llmConfig: Optional[Dict[str, Any]] = None
    multiAgent: Optional[bool] = False
    description: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

class AutoGenAgentRequest(BaseModel):
    agent_description: str  # Agent描述
    available_tools: Optional[List[str]] = None  # 可选的工具名称列表，如果提供则只使用这些工具



# ============= 系统相关模型 =============

class SystemStatus(BaseModel):
    status: str
    service_name: str = "SageStreamService"
    tools_count: int
    active_sessions: int
    version: str = "1.0"

class InterruptRequest(BaseModel):
    message: str = "用户请求中断"

class SystemPromptOptimizeRequest(BaseModel):
    original_prompt: str  # 原始系统提示词
    optimization_goal: Optional[str] = None  # 优化目标（可选）

class ConfigRequest(BaseModel):
    api_key: str
    model_name: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com/v1"
    max_tokens: Optional[int] = 4096
    temperature: Optional[float] = 0.7


# ============= 响应数据模型 =============

class MCPServerData(BaseModel):
    server_name: str
    status: str


# ============= 辅助函数 =============

def create_success_response(data: Any = None, message: str = "操作成功") -> StandardResponse:
    """创建成功响应"""
    return StandardResponse(code=200, message=message, data=data)

def create_error_response(code: int = 500, message: str = "操作失败", error_detail: str = None) -> ErrorResponse:
    """创建错误响应"""
    return ErrorResponse(code=code, message=message, error_detail=error_detail)


class Response:
    @staticmethod
    async def succ(message="", data=None):
        return  StandardResponse(code=200, message=message, data=data)

    @staticmethod
    async def error(code: int = 500, message: str = "操作失败", error_detail: str = None):
        return ErrorResponse(code=code, message=message, error_detail=error_detail)

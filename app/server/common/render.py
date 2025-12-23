"""
统一的响应模型和数据模型

提供标准化的API响应格式和数据模型定义
"""

import time
from typing import Any, Optional

from pydantic import BaseModel

# ============= 统一响应模型 =============


class StandardResponse(BaseModel):
    """标准API响应格式"""

    code: int = 200
    message: str = "success"
    data: Optional[Any] = None
    timestamp: Optional[float] = None

    def __init__(self, **data):
        if "timestamp" not in data:
            data["timestamp"] = time.time()
        super().__init__(**data)


class ErrorResponse(BaseModel):
    """错误响应格式"""

    code: int
    message: str
    error_detail: Optional[str] = None
    timestamp: Optional[float] = None

    def __init__(self, **data):
        if "timestamp" not in data:
            data["timestamp"] = time.time()
        super().__init__(**data)


class Response:
    @staticmethod
    async def succ(message="", data=None):
        return StandardResponse(code=200, message=message, data=data)

    @staticmethod
    async def error(
        code: int = 500, message: str = "操作失败", error_detail: str = None
    ):
        return ErrorResponse(code=code, message=message, error_detail=error_detail)

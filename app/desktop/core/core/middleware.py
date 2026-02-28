"""
中间件模块
"""

import uuid

from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from .context import set_request_context




def register_middlewares(app):
    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex="https?://.*|tauri://.*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_logging_middleware(request: Request, call_next):
        """请求日志中间件，记录请求信息和用户名称"""
        # 生成请求ID
        request_id = f"{uuid.uuid4().hex[:12]}"

        # 使用bind创建带有上下文的logger实例，避免全局状态污染
        request_logger = logger.bind(request_id=request_id)

        # 设置请求上下文到ContextVar中，确保线程安全
        set_request_context(request_id, request_logger)

        # 将request_logger存储到request.state中，供后续使用（兼容性保留）
        request.state.logger = request_logger
        request.state.request_id = request_id

        # 处理请求
        response = await call_next(request)

        return response


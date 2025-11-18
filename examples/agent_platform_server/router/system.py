from fastapi import APIRouter
import time
from common.render import Response

# 创建路由器
system_router = APIRouter(prefix="/api", tags=["System"])


@system_router.get("/health")
async def health_check():
    return await Response.succ(
        message="服务运行正常",
        data={
            "status": "healthy",
            "timestamp": time.time(),
            "service": "SagePlatform",
        },
    )

"""
Trace 路由
"""


from fastapi import APIRouter
from loguru import logger

from ..core.render import Response
from ..models.trace import TraceDao

trace_router = APIRouter(prefix="/api/trace", tags=["trace"])

@trace_router.get("/{session_id}")
async def get_session_traces(session_id: str):
    """
    获取指定会话的 Trace 数据
    """
    dao = TraceDao()
    try:
        traces = await dao.get_traces_by_session_id(session_id)
        return await Response.succ(data=[t.to_dict() for t in traces])
    except Exception as e:
        logger.error(f"Failed to get traces for session {session_id}: {e}")
        return await Response.error(message=f"获取 Trace 数据失败: {str(e)}")

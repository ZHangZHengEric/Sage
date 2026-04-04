from typing import Any, Awaitable, Callable, Dict, Optional

from common.schemas.agent import AgentAbilitiesData
from common.services import agent_service
from common.services.agent_view_service import get_default_system_prompt_content
from common.services.async_task_service import get_async_task_service


async def build_default_system_prompt_response(
    *,
    language: str = "zh",
    blank_draft: bool = False,
) -> Dict[str, Any]:
    content = get_default_system_prompt_content(
        language=language,
        blank_draft=blank_draft,
    )
    return {
        "message": "成功获取默认System Prompt模板",
        "data": {"content": content},
    }


async def build_auto_generate_response(
    *,
    agent_description: str,
    available_tools: Optional[list[str]],
    user_id: str,
    wrap_key: Optional[str] = None,
) -> Dict[str, Any]:
    agent_config = await agent_service.auto_generate_agent(
        agent_description=agent_description,
        available_tools=available_tools,
        user_id=user_id,
    )
    data: Any = agent_config if not wrap_key else {wrap_key: agent_config}
    return {
        "message": "Agent自动生成成功",
        "data": data,
    }


async def submit_auto_generate_task(
    *,
    agent_description: str,
    available_tools: Optional[list[str]],
    user_id: str,
) -> Dict[str, Any]:
    task = await get_async_task_service().submit(
        task_type="agent_auto_generate",
        owner_id=user_id,
        metadata={"agent_description": (agent_description or "")[:120]},
        runner=lambda: agent_service.auto_generate_agent(
            agent_description=agent_description,
            available_tools=available_tools,
            user_id=user_id,
        ),
    )
    return {
        "message": "Agent自动生成任务已提交",
        "data": task,
    }


async def build_system_prompt_optimize_response(
    *,
    original_prompt: str,
    optimization_goal: Optional[str],
    user_id: str,
) -> Dict[str, Any]:
    result = await agent_service.optimize_system_prompt(
        original_prompt=original_prompt,
        optimization_goal=optimization_goal,
        user_id=user_id,
    )
    return {
        "message": "系统提示词优化成功",
        "data": result,
    }


async def submit_system_prompt_optimize_task(
    *,
    original_prompt: str,
    optimization_goal: Optional[str],
    user_id: str,
) -> Dict[str, Any]:
    task = await get_async_task_service().submit(
        task_type="system_prompt_optimize",
        owner_id=user_id,
        metadata={"original_length": len(original_prompt or "")},
        runner=lambda: agent_service.optimize_system_prompt(
            original_prompt=original_prompt,
            optimization_goal=optimization_goal,
            user_id=user_id,
        ),
    )
    return {
        "message": "系统提示词优化任务已提交",
        "data": task,
    }


async def build_agent_abilities_response(
    *,
    agent_id: str,
    session_id: Optional[str],
    context: Optional[Dict[str, Any]],
    language: str,
    user_id: str,
    wrap_data_model: bool = False,
) -> Dict[str, Any]:
    items = await agent_service.generate_agent_abilities(
        agent_id=agent_id,
        session_id=session_id,
        context=context,
        language=language or "zh",
        user_id=user_id,
    )
    if wrap_data_model:
        data = AgentAbilitiesData(items=items).model_dump()
    else:
        data = {"items": [item.model_dump() for item in items]}
    return {
        "message": "获取 Agent 能力列表成功",
        "data": data,
    }


async def build_workspace_listing_response(
    *,
    agent_id: str,
    user_id: Optional[str] = None,
    fetcher: Callable[[], Awaitable[Dict[str, Any]]],
) -> Dict[str, Any]:
    result = await fetcher()
    data = dict(result or {})
    if user_id is not None:
        data["user_id"] = user_id
    return {
        "message": data.get("message", "获取文件列表成功"),
        "data": data,
    }


async def build_workspace_delete_response(
    *,
    file_path: str,
    deleter: Callable[[], Awaitable[bool]],
) -> Dict[str, Any]:
    await deleter()
    return {
        "message": f"文件 {file_path} 已删除",
        "data": {},
    }

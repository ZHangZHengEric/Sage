import os
import time
from typing import List, Optional
from fastapi import APIRouter, Query, Path, Body, Request
from loguru import logger
from common.schemas.base import (
    OneTimeTaskCreate,
    OneTimeTaskListResponse,
    OneTimeTaskUpdate,
    RecurringTaskCreate,
    RecurringTaskResponse,
    RecurringTaskUpdate,
    TaskHistoryListResponse,
    TaskListResponse,
    TaskResponse,
)
from ..services.task import task_service
from ..user_context import DEFAULT_DESKTOP_USER_ID, get_desktop_user_id

SCHEDULER_USER_ID = os.getenv("SAGE_TASK_SCHEDULER_USER_ID", "task_scheduler")


def _get_scheduler_scope_user_id(request: Request) -> str:
    user_id = get_desktop_user_id(request)
    if user_id == SCHEDULER_USER_ID:
        return ""
    return user_id or DEFAULT_DESKTOP_USER_ID


def _serialize_task_items(items):
    return [TaskResponse.model_validate(item).model_dump(mode="json") for item in items]

task_router = APIRouter(prefix="/tasks", tags=["Tasks"])

@task_router.get("/one-time", response_model=OneTimeTaskListResponse)
async def list_one_time_tasks(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    agent_id: Optional[str] = None
):
    start_time = time.perf_counter()
    user_id = get_desktop_user_id(request)
    logger.info(f"[TaskRouter] list_one_time_tasks START | page={page} | page_size={page_size} | agent_id={agent_id} | user_id={user_id}")
    items, total = await task_service.get_one_time_tasks(page, page_size, agent_id, user_id=user_id)
    elapsed = time.perf_counter() - start_time
    logger.info(f"[TaskRouter] list_one_time_tasks SUCCESS | count={len(items)} | total={total} | time={elapsed:.3f}s")
    return OneTimeTaskListResponse(items=items, total=total, page=page, page_size=page_size)

@task_router.get("/one-time/{task_id}", response_model=TaskResponse)
async def get_one_time_task(request: Request, task_id: int = Path(..., ge=1)):
    start_time = time.perf_counter()
    user_id = get_desktop_user_id(request)
    logger.info(f"[TaskRouter] get_one_time_task START | task_id={task_id} | user_id={user_id}")
    result = await task_service.get_one_time_task(task_id, user_id=user_id)
    elapsed = time.perf_counter() - start_time
    logger.info(f"[TaskRouter] get_one_time_task SUCCESS | task_id={task_id} | time={elapsed:.3f}s")
    return result

@task_router.post("/one-time", response_model=TaskResponse)
async def create_one_time_task(data: OneTimeTaskCreate, request: Request):
    start_time = time.perf_counter()
    user_id = get_desktop_user_id(request)
    logger.info(f"[TaskRouter] create_one_time_task START | name='{data.name}' | agent_id={data.agent_id} | user_id={user_id}")
    result = await task_service.create_one_time_task(data, user_id=user_id)
    elapsed = time.perf_counter() - start_time
    logger.info(f"[TaskRouter] create_one_time_task SUCCESS | task_id={result.id} | time={elapsed:.3f}s")
    return result

@task_router.put("/one-time/{task_id}", response_model=TaskResponse)
async def update_one_time_task(
    request: Request,
    task_id: int = Path(..., ge=1),
    data: OneTimeTaskUpdate = Body(...)
):
    start_time = time.perf_counter()
    user_id = get_desktop_user_id(request)
    logger.info(f"[TaskRouter] update_one_time_task START | task_id={task_id} | user_id={user_id}")
    result = await task_service.update_one_time_task(task_id, data, user_id=user_id)
    elapsed = time.perf_counter() - start_time
    logger.info(f"[TaskRouter] update_one_time_task SUCCESS | task_id={task_id} | time={elapsed:.3f}s")
    return result

@task_router.delete("/one-time/{task_id}")
async def delete_one_time_task(request: Request, task_id: int = Path(..., ge=1)):
    start_time = time.perf_counter()
    user_id = get_desktop_user_id(request)
    logger.info(f"[TaskRouter] delete_one_time_task START | task_id={task_id} | user_id={user_id}")
    await task_service.delete_one_time_task(task_id, user_id=user_id)
    elapsed = time.perf_counter() - start_time
    logger.info(f"[TaskRouter] delete_one_time_task SUCCESS | task_id={task_id} | time={elapsed:.3f}s")
    return {"success": True}

@task_router.get("/recurring", response_model=TaskListResponse)
async def list_recurring_tasks(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    agent_id: Optional[str] = None
):
    start_time = time.perf_counter()
    user_id = get_desktop_user_id(request)
    logger.info(f"[TaskRouter] list_recurring_tasks START | page={page} | page_size={page_size} | agent_id={agent_id} | user_id={user_id}")
    items, total = await task_service.get_recurring_tasks(page, page_size, agent_id, user_id=user_id)
    elapsed = time.perf_counter() - start_time
    logger.info(f"[TaskRouter] list_recurring_tasks SUCCESS | count={len(items)} | total={total} | time={elapsed:.3f}s")
    return TaskListResponse(items=items, total=total, page=page, page_size=page_size)

@task_router.get("/recurring/{task_id}", response_model=RecurringTaskResponse)
async def get_recurring_task(request: Request, task_id: int = Path(..., ge=1)):
    start_time = time.perf_counter()
    user_id = get_desktop_user_id(request)
    logger.info(f"[TaskRouter] get_recurring_task START | task_id={task_id} | user_id={user_id}")
    result = await task_service.get_recurring_task(task_id, user_id=user_id)
    elapsed = time.perf_counter() - start_time
    logger.info(f"[TaskRouter] get_recurring_task SUCCESS | task_id={task_id} | time={elapsed:.3f}s")
    return result

@task_router.post("/recurring", response_model=RecurringTaskResponse)
async def create_recurring_task(data: RecurringTaskCreate, request: Request):
    start_time = time.perf_counter()
    user_id = get_desktop_user_id(request)
    logger.info(f"[TaskRouter] create_recurring_task START | name='{data.name}' | agent_id={data.agent_id} | user_id={user_id}")
    result = await task_service.create_recurring_task(data, user_id=user_id)
    elapsed = time.perf_counter() - start_time
    logger.info(f"[TaskRouter] create_recurring_task SUCCESS | task_id={result.id} | time={elapsed:.3f}s")
    return result

@task_router.put("/recurring/{task_id}", response_model=RecurringTaskResponse)
async def update_recurring_task(
    request: Request,
    task_id: int = Path(..., ge=1),
    data: RecurringTaskUpdate = Body(...)
):
    start_time = time.perf_counter()
    user_id = get_desktop_user_id(request)
    logger.info(f"[TaskRouter] update_recurring_task START | task_id={task_id} | user_id={user_id}")
    result = await task_service.update_recurring_task(task_id, data, user_id=user_id)
    elapsed = time.perf_counter() - start_time
    logger.info(f"[TaskRouter] update_recurring_task SUCCESS | task_id={task_id} | time={elapsed:.3f}s")
    return result

@task_router.delete("/recurring/{task_id}")
async def delete_recurring_task(request: Request, task_id: int = Path(..., ge=1)):
    start_time = time.perf_counter()
    user_id = get_desktop_user_id(request)
    logger.info(f"[TaskRouter] delete_recurring_task START | task_id={task_id} | user_id={user_id}")
    await task_service.delete_recurring_task(task_id, user_id=user_id)
    elapsed = time.perf_counter() - start_time
    logger.info(f"[TaskRouter] delete_recurring_task SUCCESS | task_id={task_id} | time={elapsed:.3f}s")
    return {"success": True}

@task_router.post("/recurring/{task_id}/toggle", response_model=RecurringTaskResponse)
async def toggle_task_status(
    request: Request,
    task_id: int = Path(..., ge=1),
    enabled: bool = Body(..., embed=True)
):
    start_time = time.perf_counter()
    user_id = get_desktop_user_id(request)
    logger.info(f"[TaskRouter] toggle_task_status START | task_id={task_id} | enabled={enabled} | user_id={user_id}")
    result = await task_service.toggle_task_status(task_id, enabled, user_id=user_id)
    elapsed = time.perf_counter() - start_time
    logger.info(f"[TaskRouter] toggle_task_status SUCCESS | task_id={task_id} | enabled={enabled} | time={elapsed:.3f}s")
    return result

@task_router.get("/recurring/{task_id}/history", response_model=TaskHistoryListResponse)
async def get_task_history(
    request: Request,
    task_id: int = Path(..., ge=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100)
):
    start_time = time.perf_counter()
    user_id = get_desktop_user_id(request)
    logger.info(f"[TaskRouter] get_task_history START | task_id={task_id} | page={page} | user_id={user_id}")
    items, total = await task_service.get_task_history(task_id, page, page_size, user_id=user_id)
    elapsed = time.perf_counter() - start_time
    logger.info(f"[TaskRouter] get_task_history SUCCESS | task_id={task_id} | count={len(items)} | time={elapsed:.3f}s")
    return TaskHistoryListResponse(items=items, total=total, page=page, page_size=page_size)

@task_router.get("/one-time/{task_id}/history")
async def get_one_time_task_history(
    request: Request,
    task_id: int = Path(..., ge=1),
    limit: int = Query(20, ge=1, le=100)
):
    start_time = time.perf_counter()
    user_id = get_desktop_user_id(request)
    logger.info(f"[TaskRouter] get_one_time_task_history START | task_id={task_id} | limit={limit} | user_id={user_id}")
    result = await task_service.get_one_time_task_history(task_id, user_id=user_id, limit=limit)
    elapsed = time.perf_counter() - start_time
    logger.info(f"[TaskRouter] get_one_time_task_history SUCCESS | task_id={task_id} | count={len(result)} | time={elapsed:.3f}s")
    return result

@task_router.post("/internal/spawn-due")
async def spawn_due_recurring_tasks(request: Request):
    start_time = time.perf_counter()
    user_id = _get_scheduler_scope_user_id(request)
    logger.info(f"[TaskRouter] spawn_due_recurring_tasks START | user_id={user_id}")
    items = await task_service.spawn_due_recurring_tasks(user_id=user_id)
    elapsed = time.perf_counter() - start_time
    logger.info(f"[TaskRouter] spawn_due_recurring_tasks SUCCESS | spawned_count={len(items)} | time={elapsed:.3f}s")
    return {"items": _serialize_task_items(items)}

@task_router.get("/internal/due")
async def get_due_pending_tasks(
    request: Request,
    limit: int = Query(100, ge=1, le=500)
):
    start_time = time.perf_counter()
    user_id = _get_scheduler_scope_user_id(request)
    logger.info(f"[TaskRouter] get_due_pending_tasks START | limit={limit} | user_id={user_id}")
    items = await task_service.get_due_pending_tasks(user_id=user_id, limit=limit)
    elapsed = time.perf_counter() - start_time
    logger.info(f"[TaskRouter] get_due_pending_tasks SUCCESS | count={len(items)} | time={elapsed:.3f}s")
    return {"items": _serialize_task_items(items)}

@task_router.post("/internal/one-time/{task_id}/claim")
async def claim_one_time_task(request: Request, task_id: int = Path(..., ge=1)):
    start_time = time.perf_counter()
    user_id = get_desktop_user_id(request)
    logger.info(f"[TaskRouter] claim_one_time_task START | task_id={task_id} | user_id={user_id}")
    result = await task_service.claim_one_time_task(task_id, user_id=user_id)
    elapsed = time.perf_counter() - start_time
    logger.info(f"[TaskRouter] claim_one_time_task SUCCESS | task_id={task_id} | claimed={result} | time={elapsed:.3f}s")
    return {"claimed": result}

@task_router.post("/internal/one-time/{task_id}/complete")
async def complete_one_time_task(
    request: Request,
    task_id: int = Path(..., ge=1),
    response: Optional[str] = Body(None, embed=True)
):
    start_time = time.perf_counter()
    user_id = get_desktop_user_id(request)
    logger.info(f"[TaskRouter] complete_one_time_task START | task_id={task_id} | user_id={user_id}")
    result = await task_service.complete_one_time_task(task_id, user_id=user_id, response=response)
    elapsed = time.perf_counter() - start_time
    logger.info(f"[TaskRouter] complete_one_time_task SUCCESS | task_id={task_id} | time={elapsed:.3f}s")
    return result

@task_router.post("/internal/one-time/{task_id}/fail")
async def fail_one_time_task(
    request: Request,
    task_id: int = Path(..., ge=1),
    error_message: Optional[str] = Body(None, embed=True)
):
    start_time = time.perf_counter()
    user_id = get_desktop_user_id(request)
    logger.info(f"[TaskRouter] fail_one_time_task START | task_id={task_id} | user_id={user_id}")
    result = await task_service.fail_one_time_task(task_id, user_id=user_id, error_message=error_message)
    elapsed = time.perf_counter() - start_time
    logger.info(f"[TaskRouter] fail_one_time_task SUCCESS | task_id={task_id} | time={elapsed:.3f}s")
    return result

@task_router.post("/internal/recurring/{task_id}/complete")
async def complete_recurring_task(request: Request, task_id: int = Path(..., ge=1)):
    start_time = time.perf_counter()
    user_id = get_desktop_user_id(request)
    logger.info(f"[TaskRouter] complete_recurring_task START | task_id={task_id} | user_id={user_id}")
    result = await task_service.complete_recurring_task(task_id, user_id=user_id)
    elapsed = time.perf_counter() - start_time
    logger.info(f"[TaskRouter] complete_recurring_task SUCCESS | task_id={task_id} | time={elapsed:.3f}s")
    return result

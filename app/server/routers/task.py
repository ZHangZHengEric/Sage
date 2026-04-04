from typing import Optional

from fastapi import APIRouter, Body, Path, Query, Request

from common.core.request_identity import get_request_user_id
from common.core.render import Response
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
from common.services.task_service import task_service

task_router = APIRouter(prefix="/tasks", tags=["Tasks"])


@task_router.get("/one-time", response_model=OneTimeTaskListResponse)
async def list_one_time_tasks(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    agent_id: Optional[str] = None,
):
    items, total = await task_service.get_one_time_tasks(
        page,
        page_size,
        agent_id,
        user_id=get_request_user_id(request),
    )
    return OneTimeTaskListResponse(items=items, total=total, page=page, page_size=page_size)


@task_router.get("/one-time/{task_id}", response_model=TaskResponse)
async def get_one_time_task(request: Request, task_id: int = Path(..., ge=1)):
    return await task_service.get_one_time_task(task_id, user_id=get_request_user_id(request))


@task_router.post("/one-time", response_model=TaskResponse)
async def create_one_time_task(data: OneTimeTaskCreate, request: Request):
    return await task_service.create_one_time_task(data, user_id=get_request_user_id(request))


@task_router.put("/one-time/{task_id}", response_model=TaskResponse)
async def update_one_time_task(
    request: Request,
    task_id: int = Path(..., ge=1),
    data: OneTimeTaskUpdate = Body(...),
):
    return await task_service.update_one_time_task(task_id, data, user_id=get_request_user_id(request))


@task_router.delete("/one-time/{task_id}")
async def delete_one_time_task(request: Request, task_id: int = Path(..., ge=1)):
    await task_service.delete_one_time_task(task_id, user_id=get_request_user_id(request))
    return {"success": True}


@task_router.get("/recurring", response_model=TaskListResponse)
async def list_recurring_tasks(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    agent_id: Optional[str] = None,
):
    items, total = await task_service.get_recurring_tasks(
        page,
        page_size,
        agent_id,
        user_id=get_request_user_id(request),
    )
    return TaskListResponse(items=items, total=total, page=page, page_size=page_size)


@task_router.get("/recurring/{task_id}", response_model=RecurringTaskResponse)
async def get_recurring_task(request: Request, task_id: int = Path(..., ge=1)):
    return await task_service.get_recurring_task(task_id, user_id=get_request_user_id(request))


@task_router.post("/recurring", response_model=RecurringTaskResponse)
async def create_recurring_task(data: RecurringTaskCreate, request: Request):
    return await task_service.create_recurring_task(data, user_id=get_request_user_id(request))


@task_router.put("/recurring/{task_id}", response_model=RecurringTaskResponse)
async def update_recurring_task(
    request: Request,
    task_id: int = Path(..., ge=1),
    data: RecurringTaskUpdate = Body(...),
):
    return await task_service.update_recurring_task(task_id, data, user_id=get_request_user_id(request))


@task_router.delete("/recurring/{task_id}")
async def delete_recurring_task(request: Request, task_id: int = Path(..., ge=1)):
    await task_service.delete_recurring_task(task_id, user_id=get_request_user_id(request))
    return {"success": True}


@task_router.post("/recurring/{task_id}/toggle", response_model=RecurringTaskResponse)
async def toggle_task_status(
    request: Request,
    task_id: int = Path(..., ge=1),
    enabled: bool = Body(..., embed=True),
):
    return await task_service.toggle_task_status(task_id, enabled, user_id=get_request_user_id(request))


@task_router.get("/recurring/{task_id}/history", response_model=TaskHistoryListResponse)
async def get_task_history(
    request: Request,
    task_id: int = Path(..., ge=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    items, total = await task_service.get_task_history(
        task_id,
        page,
        page_size,
        user_id=get_request_user_id(request),
    )
    return TaskHistoryListResponse(items=items, total=total, page=page, page_size=page_size)


@task_router.get("/one-time/{task_id}/history")
async def get_one_time_task_history(
    request: Request,
    task_id: int = Path(..., ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    items = await task_service.get_one_time_task_history(
        task_id,
        user_id=get_request_user_id(request),
        limit=limit,
    )
    return items


@task_router.post("/internal/spawn-due")
async def spawn_due_recurring_tasks(request: Request):
    items = await task_service.spawn_due_recurring_tasks(user_id=get_request_user_id(request))
    return {"items": items}


@task_router.get("/internal/due")
async def get_due_pending_tasks(
    request: Request,
    limit: int = Query(100, ge=1, le=500),
):
    items = await task_service.get_due_pending_tasks(user_id=get_request_user_id(request), limit=limit)
    return {"items": items}


@task_router.post("/internal/one-time/{task_id}/claim")
async def claim_one_time_task(request: Request, task_id: int = Path(..., ge=1)):
    return {"claimed": await task_service.claim_one_time_task(task_id, user_id=get_request_user_id(request))}


@task_router.post("/internal/one-time/{task_id}/complete")
async def complete_one_time_task(
    request: Request,
    task_id: int = Path(..., ge=1),
    response: Optional[str] = Body(None, embed=True),
):
    task = await task_service.complete_one_time_task(
        task_id,
        user_id=get_request_user_id(request),
        response=response,
    )
    return task


@task_router.post("/internal/one-time/{task_id}/fail")
async def fail_one_time_task(
    request: Request,
    task_id: int = Path(..., ge=1),
    error_message: Optional[str] = Body(None, embed=True),
):
    task = await task_service.fail_one_time_task(
        task_id,
        user_id=get_request_user_id(request),
        error_message=error_message,
    )
    return task


@task_router.post("/internal/recurring/{task_id}/complete")
async def complete_recurring_task(request: Request, task_id: int = Path(..., ge=1)):
    return await task_service.complete_recurring_task(task_id, user_id=get_request_user_id(request))

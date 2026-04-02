from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Path, Body
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

task_router = APIRouter(prefix="/tasks", tags=["Tasks"])

@task_router.get("/one-time", response_model=OneTimeTaskListResponse)
async def list_one_time_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    agent_id: Optional[str] = None
):
    items, total = await task_service.get_one_time_tasks(page, page_size, agent_id)
    return OneTimeTaskListResponse(items=items, total=total, page=page, page_size=page_size)

@task_router.post("/one-time", response_model=TaskResponse)
async def create_one_time_task(data: OneTimeTaskCreate):
    return await task_service.create_one_time_task(data)

@task_router.put("/one-time/{task_id}", response_model=TaskResponse)
async def update_one_time_task(
    task_id: int = Path(..., ge=1),
    data: OneTimeTaskUpdate = Body(...)
):
    return await task_service.update_one_time_task(task_id, data)

@task_router.delete("/one-time/{task_id}")
async def delete_one_time_task(task_id: int = Path(..., ge=1)):
    await task_service.delete_one_time_task(task_id)
    return {"success": True}

@task_router.get("/recurring", response_model=TaskListResponse)
async def list_recurring_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    agent_id: Optional[str] = None
):
    items, total = await task_service.get_recurring_tasks(page, page_size, agent_id)
    return TaskListResponse(items=items, total=total, page=page, page_size=page_size)

@task_router.post("/recurring", response_model=RecurringTaskResponse)
async def create_recurring_task(data: RecurringTaskCreate):
    return await task_service.create_recurring_task(data)

@task_router.put("/recurring/{task_id}", response_model=RecurringTaskResponse)
async def update_recurring_task(
    task_id: int = Path(..., ge=1),
    data: RecurringTaskUpdate = Body(...)
):
    return await task_service.update_recurring_task(task_id, data)

@task_router.delete("/recurring/{task_id}")
async def delete_recurring_task(task_id: int = Path(..., ge=1)):
    await task_service.delete_recurring_task(task_id)
    return {"success": True}

@task_router.post("/recurring/{task_id}/toggle", response_model=RecurringTaskResponse)
async def toggle_task_status(
    task_id: int = Path(..., ge=1),
    enabled: bool = Body(..., embed=True)
):
    return await task_service.toggle_task_status(task_id, enabled)

@task_router.get("/recurring/{task_id}/history", response_model=TaskHistoryListResponse)
async def get_task_history(
    task_id: int = Path(..., ge=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100)
):
    items, total = await task_service.get_task_history(task_id, page, page_size)
    return TaskHistoryListResponse(items=items, total=total, page=page, page_size=page_size)

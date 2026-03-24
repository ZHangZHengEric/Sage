from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel

class RecurringTaskBase(BaseModel):
    name: str
    description: Optional[str] = None
    agent_id: str
    cron_expression: str
    enabled: bool = True

class RecurringTaskCreate(RecurringTaskBase):
    pass

class OneTimeTaskCreate(BaseModel):
    name: str
    description: Optional[str] = None
    agent_id: str
    execute_at: datetime

class OneTimeTaskUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    agent_id: Optional[str] = None
    execute_at: Optional[datetime] = None

class RecurringTaskUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    agent_id: Optional[str] = None
    cron_expression: Optional[str] = None
    enabled: Optional[bool] = None

class RecurringTaskResponse(RecurringTaskBase):
    id: int
    created_at: datetime
    updated_at: datetime
    last_executed_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class TaskResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    agent_id: str
    session_id: Optional[str] = None
    execute_at: datetime
    status: str
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    retry_count: int
    max_retries: int
    recurring_task_id: Optional[int] = None

    class Config:
        from_attributes = True

class TaskListResponse(BaseModel):
    items: List[RecurringTaskResponse]
    total: int
    page: int
    page_size: int

class OneTimeTaskListResponse(BaseModel):
    items: List[TaskResponse]
    total: int
    page: int
    page_size: int

class TaskHistoryListResponse(BaseModel):
    items: List[TaskResponse]
    total: int
    page: int
    page_size: int

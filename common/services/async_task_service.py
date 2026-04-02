import asyncio
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, Optional

from loguru import logger

from common.core.exceptions import SageHTTPException


class AsyncTaskService:
    def __init__(self) -> None:
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def submit(
        self,
        *,
        task_type: str,
        owner_id: str,
        runner: Callable[[], Awaitable[Any]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        now = time.time()
        task_data = {
            "task_id": task_id,
            "task_type": task_type,
            "owner_id": owner_id or "",
            "status": "pending",
            "result": None,
            "error": None,
            "metadata": metadata or {},
            "created_at": now,
            "updated_at": now,
        }

        async with self._lock:
            self._cleanup_locked()
            self._tasks[task_id] = task_data

        async def _run() -> None:
            await self._update(task_id, status="running")
            try:
                result = await runner()
                await self._update(task_id, status="completed", result=result)
            except asyncio.CancelledError:
                logger.bind(task_id=task_id).info("异步任务已取消")
                await self._update(
                    task_id,
                    status="cancelled",
                    error={"message": "任务已取消", "code": "TASK_CANCELLED"},
                )
                raise
            except Exception as exc:
                logger.bind(task_id=task_id).exception(f"异步任务执行失败: {exc}")
                await self._update(
                    task_id,
                    status="failed",
                    error={
                        "message": str(exc) or "任务执行失败",
                        "code": getattr(exc, "code", "TASK_FAILED"),
                    },
                )

        task = asyncio.create_task(_run())
        await self._update(task_id, asyncio_task=task)
        return self._public_task(task_data)

    async def get(self, task_id: str, owner_id: str) -> Dict[str, Any]:
        async with self._lock:
            self._cleanup_locked()
            task = self._tasks.get(task_id)
            if not task:
                raise SageHTTPException(detail="任务不存在", error_detail=f"task '{task_id}' not found")
            if task["owner_id"] and owner_id and task["owner_id"] != owner_id:
                raise SageHTTPException(detail="无权访问该任务", error_detail="forbidden")
            return self._public_task(task)

    async def cancel(self, task_id: str, owner_id: str) -> Dict[str, Any]:
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                raise SageHTTPException(detail="任务不存在", error_detail=f"task '{task_id}' not found")
            if task["owner_id"] and owner_id and task["owner_id"] != owner_id:
                raise SageHTTPException(detail="无权访问该任务", error_detail="forbidden")
            asyncio_task = task.get("asyncio_task")
            if asyncio_task and not asyncio_task.done():
                asyncio_task.cancel()
            task["updated_at"] = time.time()
            return self._public_task(task)

    async def _update(self, task_id: str, **updates: Any) -> None:
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task.update(updates)
            task["updated_at"] = time.time()

    def _public_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "task_id": task["task_id"],
            "task_type": task["task_type"],
            "status": task["status"],
            "result": task.get("result"),
            "error": task.get("error"),
            "metadata": task.get("metadata") or {},
            "created_at": task["created_at"],
            "updated_at": task["updated_at"],
        }

    def _cleanup_locked(self) -> None:
        now = time.time()
        expired_task_ids = [
            task_id
            for task_id, task in self._tasks.items()
            if task.get("status") in {"completed", "failed", "cancelled"}
            and now - task.get("updated_at", now) > 60 * 30
        ]
        for task_id in expired_task_ids:
            self._tasks.pop(task_id, None)


_async_task_service: Optional[AsyncTaskService] = None


def get_async_task_service() -> AsyncTaskService:
    global _async_task_service
    if _async_task_service is None:
        _async_task_service = AsyncTaskService()
    return _async_task_service

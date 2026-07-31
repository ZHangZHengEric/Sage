import asyncio
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, Optional

from loguru import logger

from common.core.exceptions import SageHTTPException


class AsyncTaskService:
    TERMINAL_STATUSES = {"completed", "failed", "cancelled"}

    def __init__(
        self,
        *,
        retention_seconds: float = 60 * 30,
        cleanup_interval_seconds: float = 60,
    ) -> None:
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._retention_seconds = retention_seconds
        self._cleanup_interval_seconds = cleanup_interval_seconds
        self._cleanup_task: Optional[asyncio.Task] = None
        self._shutdown = False

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

        async def _run() -> None:
            try:
                await self._update(task_id, status="running")
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
            finally:
                await self._drop_runner_reference(task_id, asyncio.current_task())

        async with self._lock:
            if self._shutdown:
                raise RuntimeError("AsyncTaskService is shut down")
            self._ensure_cleanup_task()
            self._cleanup_locked()
            self._tasks[task_id] = task_data
            try:
                task = asyncio.create_task(_run())
            except BaseException:
                self._tasks.pop(task_id, None)
                raise
            task_data["asyncio_task"] = task
        return self._public_task(task_data)

    async def get(self, task_id: str, owner_id: str) -> Dict[str, Any]:
        async with self._lock:
            self._cleanup_locked()
            task = self._tasks.get(task_id)
            if not task:
                raise SageHTTPException(
                    message_key="task.not_found",
                    error_detail=f"task '{task_id}' not found",
                )
            if task["owner_id"] and owner_id and task["owner_id"] != owner_id:
                raise SageHTTPException(
                    message_key="task.access_forbidden", error_detail="forbidden"
                )
            return self._public_task(task)

    async def cancel(self, task_id: str, owner_id: str) -> Dict[str, Any]:
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                raise SageHTTPException(
                    message_key="task.not_found",
                    error_detail=f"task '{task_id}' not found",
                )
            if task["owner_id"] and owner_id and task["owner_id"] != owner_id:
                raise SageHTTPException(
                    message_key="task.access_forbidden", error_detail="forbidden"
                )
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

    async def _drop_runner_reference(
        self, task_id: str, runner_task: Optional[asyncio.Task]
    ) -> None:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task and task.get("asyncio_task") is runner_task:
                task.pop("asyncio_task", None)

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
            if task.get("status") in self.TERMINAL_STATUSES
            and now - task.get("updated_at", now) > self._retention_seconds
        ]
        for task_id in expired_task_ids:
            self._tasks.pop(task_id, None)

    def _ensure_cleanup_task(self) -> None:
        if self._cleanup_task is not None and not self._cleanup_task.done():
            return
        self._cleanup_task = asyncio.create_task(
            self._cleanup_loop(),
            name="async-task-service-cleanup",
        )

    async def _cleanup_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._cleanup_interval_seconds)
                async with self._lock:
                    self._cleanup_locked()
        except asyncio.CancelledError:
            raise

    async def shutdown(self) -> None:
        """Cancel owned tasks and release all retained task results."""
        async with self._lock:
            self._shutdown = True
            cleanup_task = self._cleanup_task
            self._cleanup_task = None
            runners = [
                task.get("asyncio_task")
                for task in self._tasks.values()
                if task.get("asyncio_task") is not None
                and not task["asyncio_task"].done()
            ]
        if cleanup_task:
            if not cleanup_task.done():
                cleanup_task.cancel()
            await asyncio.gather(cleanup_task, return_exceptions=True)

        for runner in runners:
            runner.cancel()
        if runners:
            await asyncio.gather(*runners, return_exceptions=True)
        async with self._lock:
            self._tasks.clear()


_async_task_service: Optional[AsyncTaskService] = None


def get_async_task_service() -> AsyncTaskService:
    global _async_task_service
    if _async_task_service is None:
        _async_task_service = AsyncTaskService()
    return _async_task_service


async def shutdown_async_task_service() -> None:
    global _async_task_service
    service = _async_task_service
    if service is None:
        return
    await service.shutdown()
    _async_task_service = None

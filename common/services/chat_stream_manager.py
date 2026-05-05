import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from loguru import logger
from sagents.context.session_context import delete_session_run_lock
from sagents.session_runtime import get_global_session_manager
from sagents.utils.lock_manager import safe_release


@dataclass
class SessionState:
    session_id: str
    query: str = ""
    history: List[str] = field(default_factory=list)
    subscribers: Set[asyncio.Queue] = field(default_factory=set)
    task: Optional[asyncio.Task] = None
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    status: str = "running"
    is_completed: bool = False
    lock: Optional[asyncio.Lock] = None


class StreamManager:
    _instance = None
    _sessions: Dict[str, SessionState] = {}
    _session_list_subscribers: Set[asyncio.Queue] = set()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(StreamManager, cls).__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get_history_length(self, session_id: str) -> int:
        session = self._sessions.get(session_id)
        if not session:
            return 0
        return len(session.history)

    async def _notify_session_list_changed(self):
        if not self._session_list_subscribers:
            return

        sessions = self.get_active_sessions()
        for queue in list(self._session_list_subscribers):
            await queue.put(sessions)

    async def notify_session_list_changed(self):
        await self._notify_session_list_changed()

    async def subscribe_active_sessions(self):
        queue = asyncio.Queue()
        self._session_list_subscribers.add(queue)
        try:
            yield self.get_active_sessions()
            while True:
                sessions = await queue.get()
                if sessions is None:
                    break
                yield sessions
        except asyncio.CancelledError:
            pass
        finally:
            self._session_list_subscribers.discard(queue)

    async def create_publisher(self, session_id: str, query: str = ""):
        if session_id in self._sessions:
            await self.cleanup_session(session_id)

        session = SessionState(session_id=session_id)
        session.query = query
        session.status = "running"
        self._sessions[session_id] = session
        await self._notify_session_list_changed()
        return session

    async def publish(self, session_id: str, chunk: str):
        session = self._sessions.get(session_id)
        if not session:
            return

        session.history.append(chunk)
        chunk_index = len(session.history) - 1
        session.last_activity = time.time()
        for queue in list(session.subscribers):
            await queue.put((chunk_index, chunk))

    async def finish_publisher(self, session_id: str):
        session = self._sessions.get(session_id)
        if not session:
            return

        session.is_completed = True
        for queue in list(session.subscribers):
            await queue.put(None)

        if self._sessions.get(session_id) is session:
            del self._sessions[session_id]

        await self._notify_session_list_changed()

    async def start_session(self, session_id: str, query: str, generator, lock: asyncio.Lock):
        if session_id in self._sessions:
            session = self._sessions[session_id]
            if not session.is_completed and session.task and not session.task.done():
                logger.info(f"Session {session_id} already running, joining existing session.")
                if lock and lock != session.lock:
                    await safe_release(lock, session_id, "复用会话释放新锁")
                return
            await self.cleanup_session(session_id)

        session = SessionState(session_id=session_id, lock=lock)
        session.query = query
        self._sessions[session_id] = session
        await self._notify_session_list_changed()

        session.task = asyncio.create_task(self._background_worker(session, generator))
        logger.debug(f"Started background task for session {session_id}")

    async def _background_worker(self, session: SessionState, generator):
        try:
            async for chunk in generator:
                session.history.append(chunk)
                chunk_index = len(session.history) - 1
                session.last_activity = time.time()
                for queue in list(session.subscribers):
                    await queue.put((chunk_index, chunk))
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            session.status = "interrupted"
            logger.info(f"Background worker cancelled for {session.session_id}")
            raise
        except Exception as e:
            logger.error(f"Background worker error for {session.session_id}: {e}")
            error_json = '{"type":"error","content":"Internal Server Error during stream processing"}\n'
            session.history.append(error_json)
            error_index = len(session.history) - 1
            for queue in list(session.subscribers):
                await queue.put((error_index, error_json))
        finally:
            try:
                if hasattr(generator, "aclose"):
                    await generator.aclose()
            except Exception as e:
                logger.warning(f"Error closing generator for {session.session_id}: {e}")
            session.is_completed = True
            logger.debug(f"Session {session.session_id} completed. Total chunks: {len(session.history)}")
            for queue in list(session.subscribers):
                await queue.put(None)

            if session.lock:
                try:
                    released = await safe_release(session.lock, session.session_id, "后台流结束清理")
                    delete_session_run_lock(session.session_id)
                    if released:
                        logger.debug(f"Released lock for session {session.session_id}")
                except Exception as e:
                    logger.error(f"Error releasing lock for {session.session_id}: {e}")

            if self._sessions.get(session.session_id) is session:
                del self._sessions[session.session_id]
                await self._notify_session_list_changed()

    async def cleanup_session(self, session_id: str):
        if session_id in self._sessions:
            del self._sessions[session_id]
            await self._notify_session_list_changed()

    def has_running_session(self, session_id: Optional[str]) -> bool:
        if not session_id:
            return False
        session = self._sessions.get(session_id)
        if not session:
            return False
        return bool(session.task and not session.task.done() and not session.is_completed)

    async def get_session_query(self, session_id: str) -> Optional[str]:
        if session_id in self._sessions:
            return self._sessions[session_id].query
        return None

    async def stop_session(self, session_id: Optional[str]) -> None:
        if not session_id:
            return
        session = self._sessions.get(session_id)
        if not session:
            return
        task = session.task
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        session.status = "interrupted"
        await self.cleanup_session(session_id)

    async def subscribe(self, session_id: str, last_index: int = 0):
        session = self._sessions.get(session_id)
        if not session:
            return

        queue = asyncio.Queue()
        session.subscribers.add(queue)
        logger.info(f"Client subscribed to session {session_id}, offset={last_index}")

        try:
            history_len = len(session.history)
            start_index = max(0, last_index)
            next_index = start_index

            if start_index < history_len:
                for i in range(start_index, history_len):
                    yield session.history[i]
                    next_index = i + 1

            if session.is_completed:
                return

            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=20.0)
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                    continue

                if payload is None:
                    break

                idx, chunk = payload
                if idx < next_index:
                    continue

                next_index = idx + 1
                yield chunk
        except asyncio.CancelledError:
            raise
        finally:
            session.subscribers.discard(queue)

    def get_active_sessions(self):
        if not self._sessions:
            return []
        session_manager = get_global_session_manager()
        return [
            {
                "session_id": session.session_id,
                "created_at": session.created_at,
                "is_completed": session.is_completed,
                "status": session.status,
                "last_activity": session.last_activity,
                "query": session.query,
                "goal": (
                    goal.model_dump(mode="json")
                    if (goal := session_manager.get_goal(session.session_id))
                    else None
                ),
                "goal_transition": (
                    session_manager.get_goal_transition(session.session_id)
                    if session_manager
                    else None
                ),
            }
            for session in self._sessions.values()
            if not session.is_completed
        ]

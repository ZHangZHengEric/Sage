import asyncio
import time
from typing import Dict, List, Set, Optional
from dataclasses import dataclass, field
from loguru import logger
from sagents.context.session_context import delete_session_run_lock
from sagents.utils.lock_manager import safe_release


@dataclass
class SessionState:
    session_id: str
    history: List[str] = field(default_factory=list)  # 存储已生成的 JSON 字符串
    subscribers: Set[asyncio.Queue] = field(default_factory=set)
    task: Optional[asyncio.Task] = None
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    is_completed: bool = False
    lock: Optional[asyncio.Lock] = None  # 持有 session lock


class StreamManager:
    _instance = None
    _sessions: Dict[str, SessionState] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(StreamManager, cls).__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def start_session(self, session_id: str, generator, lock: asyncio.Lock):
        """
        启动一个新的会话任务，如果会话已存在且正在运行，则复用
        """
        if session_id in self._sessions:
            session = self._sessions[session_id]
            # 如果已存在且未完成，可能是重复请求，或者之前的任务还在跑
            if not session.is_completed and session.task and not session.task.done():
                logger.info(f"Session {session_id} already running, joining existing session.")
                # 即使复用，我们也不需要释放传入的新锁，因为调用方应该在发现 session 存在时处理
                # 但这里简单起见，如果复用，我们需要释放传入的 lock，因为我们使用旧的 lock
                if lock and lock != session.lock:
                    await safe_release(lock, session_id, "复用会话释放新锁")
                return

            # 如果已完成，或是旧的残留，清理掉旧的
            await self.cleanup_session(session_id)

        session = SessionState(session_id=session_id, lock=lock)
        self._sessions[session_id] = session

        # 启动后台任务
        session.task = asyncio.create_task(self._background_worker(session, generator))
        logger.info(f"Started background task for session {session_id}")

    async def _background_worker(self, session: SessionState, generator):
        try:
            async for chunk in generator:
                session.history.append(chunk)
                session.last_activity = time.time()
                # 广播给所有订阅者
                for q in list(session.subscribers):
                    await q.put(chunk)
                await asyncio.sleep(0)
        except Exception as e:
            logger.error(f"Background worker error for {session.session_id}: {e}")
            # 可以在这里构造一个 Error Chunk 发送给订阅者
            error_json = '{"type":"error","content":"Internal Server Error during stream processing"}\n'
            session.history.append(error_json)
            for q in list(session.subscribers):
                await q.put(error_json)
        finally:
            session.is_completed = True
            logger.info(f"Session {session.session_id} completed. Total chunks: {len(session.history)}")
            # 发送结束信号给订阅者 (None)
            for q in list(session.subscribers):
                await q.put(None)

            # 任务结束，释放业务锁
            if session.lock:
                try:
                    released = await safe_release(session.lock, session.session_id, "后台流结束清理")
                    delete_session_run_lock(session.session_id)
                    if released:
                        logger.info(f"Released lock for session {session.session_id}")
                except Exception as e:
                    logger.error(f"Error releasing lock for {session.session_id}: {e}")

            if self._sessions.get(session.session_id) is session:
                del self._sessions[session.session_id]

    async def cleanup_session(self, session_id: str):
        if session_id in self._sessions:
            del self._sessions[session_id]

    def has_running_session(self, session_id: Optional[str]) -> bool:
        if not session_id:
            return False
        session = self._sessions.get(session_id)
        if not session:
            return False
        return bool(session.task and not session.task.done() and not session.is_completed)

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
        await self.cleanup_session(session_id)

    async def subscribe(self, session_id: str, last_index: int = 0):
        """
        订阅会话消息流
        :param session_id: 会话ID
        :param last_index: 客户端已收到的消息索引，从该索引之后开始发送
        """
        session = self._sessions.get(session_id)
        if not session:
            # Session 不存在
            return

        queue = asyncio.Queue()
        session.subscribers.add(queue)
        logger.info(f"Client subscribed to session {session_id}, offset={last_index}")

        try:
            # 1. 先发送历史消息 (Catch up)
            history_len = len(session.history)
            if last_index < history_len:
                for i in range(last_index, history_len):
                    yield session.history[i]

            # 2. 如果任务已完成，直接结束
            if session.is_completed:
                return

            # 3. 监听实时消息
            while True:
                chunk = await queue.get()
                if chunk is None:  # 结束信号
                    break
                yield chunk
        except asyncio.CancelledError:
            logger.info(f"Client disconnected from session {session_id}")
            raise
        finally:
            session.subscribers.discard(queue)

    def get_active_sessions(self):
        if not self._sessions:
            return []
        """获取所有活跃会话列表（可选，用于侧边栏展示）"""
        return [{"session_id": s.session_id, "created_at": s.created_at, "is_completed": s.is_completed, "last_activity": s.last_activity} for s in self._sessions.values() if not s.is_completed]

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
    query: str = ""
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
        """通知所有订阅者会话列表发生变化"""
        if not self._session_list_subscribers:
            return
        
        # 获取当前会话列表
        sessions = self.get_active_sessions()
        
        # 推送给所有订阅者
        for q in list(self._session_list_subscribers):
            await q.put(sessions)

    async def subscribe_active_sessions(self):
        """订阅活跃会话列表变化"""
        queue = asyncio.Queue()
        self._session_list_subscribers.add(queue)
        try:
            # 立即发送当前状态
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
        """
        创建一个由外部驱动的会话发布者
        """
        if session_id in self._sessions:
            await self.cleanup_session(session_id)

        session = SessionState(session_id=session_id)
        session.query = query
        self._sessions[session_id] = session
        await self._notify_session_list_changed()
        return session

    async def publish(self, session_id: str, chunk: str):
        """
        向指定会话发布消息块
        """
        session = self._sessions.get(session_id)
        if not session:
            return

        session.history.append(chunk)
        chunk_index = len(session.history) - 1
        session.last_activity = time.time()
        for q in list(session.subscribers):
            await q.put((chunk_index, chunk))

    async def finish_publisher(self, session_id: str):
        """
        结束外部驱动的会话
        """
        session = self._sessions.get(session_id)
        if not session:
            return

        session.is_completed = True
        # 发送结束信号给订阅者
        for q in list(session.subscribers):
            await q.put(None)

        # 清理会话
        if self._sessions.get(session_id) is session:
            del self._sessions[session_id]
        
        await self._notify_session_list_changed()

    async def start_session(self, session_id: str, query: str, generator, lock: asyncio.Lock):
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
        session.query = query
        self._sessions[session_id] = session
        await self._notify_session_list_changed()

        # 启动后台任务
        session.task = asyncio.create_task(self._background_worker(session, generator))
        logger.debug(f"Started background task for session {session_id}")

    async def _background_worker(self, session: SessionState, generator):
        try:
            async for chunk in generator:
                session.history.append(chunk)
                chunk_index = len(session.history) - 1
                session.last_activity = time.time()
                # 广播给所有订阅者
                for q in list(session.subscribers):
                    await q.put((chunk_index, chunk))
                
                # 在这里保留一个微小的调度点是好的，确保高频消息分发时不会完全占满事件循环
                # 特别是当有多个订阅者时，这给了其他协程（如新连接请求）插入的机会
                await asyncio.sleep(0)
        except Exception as e:
            logger.error(f"Background worker error for {session.session_id}: {e}")
            # 可以在这里构造一个 Error Chunk 发送给订阅者
            error_json = '{"type":"error","content":"Internal Server Error during stream processing"}\n'
            session.history.append(error_json)
            error_index = len(session.history) - 1
            for q in list(session.subscribers):
                await q.put((error_index, error_json))
        finally:
            session.is_completed = True
            logger.debug(f"Session {session.session_id} completed. Total chunks: {len(session.history)}")
            # 发送结束信号给订阅者 (None)
            for q in list(session.subscribers):
                await q.put(None)

            # 任务结束，释放业务锁
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
            # 注意：last_index 是客户端已经收到的最后一条消息的索引 + 1（即期望的下一条）
            # 或者如果是 0，表示从头开始
            
            history_len = len(session.history)
            
            # 客户端传来的 last_index 通常是它期望的下一个 index
            # 如果客户端传来 0，表示它没有数据，我们从 0 开始发
            # 如果客户端传来 5，表示它已经有 0-4，我们从 5 开始发
            start_index = max(0, last_index)
            
            # 使用 next_index 跟踪当前已发送的索引，避免重复发送
            next_index = start_index
            
            if start_index < history_len:
                for i in range(start_index, history_len):
                    yield session.history[i]
                    next_index = i + 1
            
            # 2. 如果任务已完成，且历史消息已全部发送，直接结束
            if session.is_completed:
                return

            # 3. 监听实时消息
            while True:
                try:
                    # 增加超时处理，实现心跳机制 (每20秒发送一次心跳)
                    payload = await asyncio.wait_for(queue.get(), timeout=20.0)
                except asyncio.TimeoutError:
                    # 发送SSE注释作为心跳，保持连接活跃
                    yield ": heartbeat\n\n"
                    continue

                if payload is None:  # 结束信号
                    break
                    
                idx, chunk = payload
                
                # 防止重复发送历史消息
                # 如果 queue 中的消息索引小于我们已经发送的 next_index，说明我们在 catch up 阶段已经发过了
                if idx < next_index:
                    continue
                
                # 更新 next_index
                next_index = idx + 1
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
        return [
            {
                "session_id": s.session_id, 
                "created_at": s.created_at, 
                "is_completed": s.is_completed, 
                "last_activity": s.last_activity,
                "query": s.query
            } 
            for s in self._sessions.values() 
            if not s.is_completed
        ]

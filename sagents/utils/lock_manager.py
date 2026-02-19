import asyncio
import os
import time
from typing import Dict, Any
from sagents.utils.logger import logger

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


class UnifiedLock:
    """
    统一锁接口，屏蔽 asyncio.Lock (同步release) 和 Redis Lock (异步release) 的差异
    """

    def __init__(self, lock, is_redis: bool = False):
        self._lock = lock
        self._is_redis = is_redis

    async def acquire(self, blocking: bool = True):
        if self._is_redis:
            return await self._lock.acquire(blocking=blocking)
        else:
            # asyncio.Lock.acquire doesn't verify blocking param in standard way like threading
            # but usually we just await it
            return await self._lock.acquire()

    async def release(self):
        if self._is_redis:
            await self._lock.release()
        else:
            self._lock.release()

    def locked(self) -> bool:
        if self._is_redis:
            return self._lock.locked()
        else:
            return self._lock.locked()

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.release()


class LockManager:
    _instance = None
    _memory_locks: Dict[str, Dict[str, Any]] = {}
    _redis_client = None
    use_redis = False
    _lock_expire_seconds = 1800  # 默认1小时过期
    _last_cleanup_time = 0

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(LockManager, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        self.use_redis = os.getenv("ENABLE_REDIS_LOCK", "false").lower() == "true"
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        
        # 从环境变量获取过期时间配置
        try:
            self._lock_expire_seconds = int(os.getenv("MEMORY_LOCK_EXPIRE_SECONDS", "1800"))
        except ValueError:
            self._lock_expire_seconds = 1800

        if self.use_redis:
            if not REDIS_AVAILABLE:
                logger.warning(
                    "ENABLE_REDIS_LOCK is true but redis-py is not installed. Falling back to memory locks."
                )
                self.use_redis = False
            else:
                try:
                    # socket_keepalive=True to avoid connection drop
                    self._redis_client = redis.from_url(
                        self.redis_url,
                        encoding="utf-8",
                        decode_responses=True,
                        socket_keepalive=True,
                    )
                    logger.info(f"LockManager initialized with Redis: {self.redis_url}")
                except Exception as e:
                    logger.error(
                        f"Failed to connect to Redis: {e}. Falling back to memory locks."
                    )
                    self.use_redis = False

    def _cleanup_expired_locks(self):
        """清理过期的内存锁"""
        now = time.time()
        # 每分钟最多清理一次
        if now - self._last_cleanup_time < 60:
            return
            
        self._last_cleanup_time = now
        expired_keys = []
        
        # 找出过期且未被锁定的锁
        for key, entry in self._memory_locks.items():
            if (now - entry['last_accessed'] > self._lock_expire_seconds and 
                not entry['lock'].locked()):
                expired_keys.append(key)
        
        # 删除过期锁
        if expired_keys:
            logger.debug(f"Cleaning up {len(expired_keys)} expired memory locks")
            for key in expired_keys:
                # 再次检查以确保安全
                if (key in self._memory_locks and 
                    not self._memory_locks[key]['lock'].locked()):
                    del self._memory_locks[key]

    def get_lock(self, key: str) -> UnifiedLock:
        """获取锁实例"""
        if self.use_redis and self._redis_client:
            lock_key = f"sage:lock:{key}"
            redis_lock = self._redis_client.lock(lock_key, timeout=30)
            return UnifiedLock(redis_lock, is_redis=True)
        else:
            # 尝试清理过期锁
            self._cleanup_expired_locks()
            
            now = time.time()
            if key not in self._memory_locks:
                self._memory_locks[key] = {
                    'lock': asyncio.Lock(),
                    'last_accessed': now
                }
            
            # 更新访问时间
            self._memory_locks[key]['last_accessed'] = now
            return UnifiedLock(self._memory_locks[key]['lock'], is_redis=False)

    async def close(self):
        if self._redis_client:
            await self._redis_client.close()

    def delete_lock_ref(self, key: str):
        """仅用于清理内存锁引用，Redis锁不需要手动删除key"""
        if not self.use_redis and key in self._memory_locks:
            if not self._memory_locks[key].locked():
                del self._memory_locks[key]


lock_manager = LockManager()

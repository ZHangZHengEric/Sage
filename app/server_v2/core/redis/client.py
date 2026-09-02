from __future__ import annotations

import asyncio
import builtins
import json
import secrets
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from loguru import logger
from redis.asyncio import BlockingConnectionPool
from redis.asyncio import Redis as AsyncRedis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.server_v2.core.failures import DependencyUnavailableError

_EXTEND_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
  return redis.call("PEXPIRE", KEYS[1], ARGV[2])
end
return 0
"""
_RELEASE_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
  return redis.call("DEL", KEYS[1])
end
return 0
"""


@dataclass(frozen=True, slots=True)
class RedisSettings:
    url: str = field(repr=False)
    key_prefix: str = "aiot"
    connect_timeout_seconds: float = 3
    socket_timeout_seconds: float = 2
    max_connections: int = 100
    pool_timeout_seconds: float = 5


class RedisLockUnavailable(RuntimeError):
    pass


class RedisLease:
    def __init__(
        self,
        redis: Redis,
        *,
        key: str,
        owner_token: str,
        lease_milliseconds: int,
    ) -> None:
        self._redis = redis
        self.key = key
        self._owner_token = owner_token
        self._lease_milliseconds = lease_milliseconds
        self._renew_task: asyncio.Task[None] | None = None

    async def extend(self) -> bool:
        result = await self._redis.eval(
            _EXTEND_SCRIPT,
            1,
            self.key,
            self._owner_token,
            str(self._lease_milliseconds),
        )
        return int(result or 0) == 1

    async def release(self) -> bool:
        result = await self._redis.eval(
            _RELEASE_SCRIPT,
            1,
            self.key,
            self._owner_token,
        )
        return int(result or 0) == 1

    def start_renewal(self) -> None:
        if self._renew_task is None:
            self._renew_task = asyncio.create_task(
                self._renew(),
                name=f"redis-lease:{self.key}",
            )

    async def stop_renewal(self) -> None:
        task, self._renew_task = self._renew_task, None
        if task is None:
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def _renew(self) -> None:
        interval = max(0.01, self._lease_milliseconds / 3000)
        while True:
            await asyncio.sleep(interval)
            if not await self.extend():
                return


class Redis:
    name = "redis"

    def __init__(
        self,
        settings: RedisSettings,
        *,
        pool_factory: Callable[..., Any] = BlockingConnectionPool.from_url,
        client_factory: Callable[[Any], Any] = AsyncRedis.from_pool,
    ) -> None:
        if not str(settings.url or "").strip():
            raise ValueError("Redis URL is required")
        if settings.connect_timeout_seconds <= 0:
            raise ValueError("Redis connect timeout must be positive")
        if settings.socket_timeout_seconds <= 0:
            raise ValueError("Redis socket timeout must be positive")
        if settings.max_connections <= 0:
            raise ValueError("Redis max connections must be positive")
        if settings.pool_timeout_seconds <= 0:
            raise ValueError("Redis pool timeout must be positive")
        self.settings = settings
        self._pool_factory = pool_factory
        self._client_factory = client_factory
        self._client: Any | None = None

    async def start(self) -> None:
        pool = self._pool_factory(
            self.settings.url,
            max_connections=self.settings.max_connections,
            timeout=self.settings.pool_timeout_seconds,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=self.settings.connect_timeout_seconds,
            socket_timeout=self.settings.socket_timeout_seconds,
            socket_keepalive=True,
            health_check_interval=30,
        )
        client = self._client_factory(pool)
        try:
            await client.ping()
        except BaseException:
            await client.aclose()
            raise
        self._client = client

    async def ready(self) -> bool:
        if self._client is None:
            return False
        try:
            return bool(await self._client.ping())
        except Exception:
            return False

    async def stop(self) -> None:
        client = self._client
        if client is None:
            return
        await client.aclose()
        if self._client is client:
            self._client = None

    def key(self, *parts: str) -> str:
        values = [str(part).strip(": ") for part in parts if str(part or "").strip(": ")]
        prefix = self.settings.key_prefix.strip(": ")
        if prefix:
            values.insert(0, prefix)
        return ":".join(values)

    def _required_client(self) -> Any:
        if self._client is None:
            raise RuntimeError("Redis is not initialized")
        return self._client

    async def _read_with_retry(
        self,
        operation: str,
        command: Callable[[], Awaitable[Any]],
    ) -> Any:
        try:
            return await command()
        except (RedisConnectionError, RedisTimeoutError) as error:
            logger.warning(
                "Redis read failed; retrying once: operation={} error_type={}",
                operation,
                type(error).__name__,
            )
        try:
            return await command()
        except (RedisConnectionError, RedisTimeoutError) as error:
            logger.warning(
                "Redis read unavailable after retry: operation={} error_type={}",
                operation,
                type(error).__name__,
            )
            raise DependencyUnavailableError(self.name) from error

    async def get(self, key: str, *, default: Any = None) -> Any:
        client = self._required_client()
        value = await self._read_with_retry("get", lambda: client.get(key))
        return default if value is None else value

    async def set(
        self,
        key: str,
        value: Any,
        *,
        expires_seconds: int | None = None,
        expires_milliseconds: int | None = None,
        only_if_absent: bool = False,
    ) -> bool:
        return bool(
            await self._required_client().set(
                key,
                value,
                ex=expires_seconds,
                px=expires_milliseconds,
                nx=only_if_absent,
            )
        )

    async def delete(self, *keys: str) -> int:
        return int(await self._required_client().delete(*keys)) if keys else 0

    async def ttl(self, key: str) -> int:
        client = self._required_client()
        return int(await self._read_with_retry("ttl", lambda: client.ttl(key)))

    async def expire(self, key: str, seconds: int) -> bool:
        normalized_seconds = int(seconds)
        if normalized_seconds <= 0:
            raise ValueError("Redis expiry must be positive")
        return bool(await self._required_client().expire(key, normalized_seconds))

    async def set_add(self, key: str, *values: str) -> int:
        if not values:
            return 0
        return int(await self._required_client().sadd(key, *values))

    async def set_remove(self, key: str, *values: str) -> int:
        if not values:
            return 0
        return int(await self._required_client().srem(key, *values))

    async def set_members(self, key: str) -> builtins.set[str]:
        client = self._required_client()
        return builtins.set(await self._read_with_retry("smembers", lambda: client.smembers(key)))

    async def get_json(self, key: str, *, default: Any = None) -> Any:
        value = await self.get(key)
        return default if value is None else json.loads(value)

    async def set_json(
        self,
        key: str,
        value: Any,
        *,
        expires_seconds: int | None = None,
        only_if_absent: bool = False,
    ) -> bool:
        return await self.set(
            key,
            json.dumps(value, ensure_ascii=False),
            expires_seconds=expires_seconds,
            only_if_absent=only_if_absent,
        )

    async def eval(self, script: str, numkeys: int, *args: Any) -> Any:
        return await self._required_client().eval(script, numkeys, *args)

    async def eval_readonly(self, script: str, numkeys: int, *args: Any) -> Any:
        """Evaluate a Lua script that the caller guarantees has no side effects."""

        client = self._required_client()
        return await self._read_with_retry(
            "eval_readonly",
            lambda: client.eval(script, numkeys, *args),
        )

    async def stream_add(
        self,
        key: str,
        fields: Mapping[str, str],
        *,
        max_length: int | None = None,
    ) -> str:
        return str(
            await self._required_client().xadd(
                key,
                dict(fields),
                maxlen=max_length,
                approximate=True,
            )
        )

    async def stream_range(
        self,
        key: str,
        *,
        start: str = "-",
        end: str = "+",
        count: int | None = None,
    ) -> list[tuple[str, dict[str, str]]]:
        client = self._required_client()
        return list(
            await self._read_with_retry(
                "xrange",
                lambda: client.xrange(
                    key,
                    min=start,
                    max=end,
                    count=count,
                ),
            )
        )

    async def stream_read(
        self,
        streams: Mapping[str, str],
        *,
        count: int | None = None,
        block_milliseconds: int | None = None,
    ) -> Any:
        client = self._required_client()
        return await self._read_with_retry(
            "xread",
            lambda: client.xread(
                dict(streams),
                count=count,
                block=block_milliseconds,
            ),
        )

    async def stream_ack(self, key: str, group: str, *entry_ids: str) -> int:
        return int(await self._required_client().xack(key, group, *entry_ids))

    async def stream_delete(self, key: str, *entry_ids: str) -> int:
        return int(await self._required_client().xdel(key, *entry_ids))

    @asynccontextmanager
    async def lock(
        self,
        *key_parts: str,
        lease_seconds: float,
        wait_timeout_seconds: float = 0,
        retry_interval_seconds: float = 0.1,
    ) -> AsyncIterator[RedisLease]:
        lease_milliseconds = int(lease_seconds * 1000)
        if lease_milliseconds <= 0:
            raise ValueError("Redis lock lease must be at least one millisecond")
        if wait_timeout_seconds < 0:
            raise ValueError("Redis lock wait timeout cannot be negative")
        if retry_interval_seconds <= 0:
            raise ValueError("Redis lock retry interval must be positive")
        key = self.key(*key_parts)
        owner_token = secrets.token_urlsafe(24)
        deadline = time.monotonic() + wait_timeout_seconds
        while True:
            acquired = await self.set(
                key,
                owner_token,
                expires_milliseconds=lease_milliseconds,
                only_if_absent=True,
            )
            if acquired:
                break
            if time.monotonic() >= deadline:
                raise RedisLockUnavailable(f"Redis lock is unavailable: {key}")
            await asyncio.sleep(retry_interval_seconds)

        lease = RedisLease(
            self,
            key=key,
            owner_token=owner_token,
            lease_milliseconds=lease_milliseconds,
        )
        lease.start_renewal()
        try:
            yield lease
        finally:
            await lease.stop_renewal()
            await lease.release()

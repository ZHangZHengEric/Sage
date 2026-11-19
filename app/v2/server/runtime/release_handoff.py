"""Manage the shared scheduler's active release from the deployment host."""

import argparse

from redis import Redis
from redis.exceptions import WatchError

from app.v2.server.config.redis_namespace import distributed_runtime_prefix
from app.v2.server.config.settings import ServerSettings
from sagents.v2.runtime.execution.scheduler.plugins.redis_distributed import RedisDistributedScheduler


def change_active_release(redis, key, expected, target):
    """Apply an idempotent change without overwriting another release."""
    for _ in range(16):
        with redis.pipeline() as pipe:
            try:
                pipe.watch(key)
                current = pipe.get(key)
                if current == target:
                    return
                if current != expected:
                    raise RuntimeError(f"Active scheduler release is {current!r}, expected {expected!r}")
                pipe.multi()
                if target is None:
                    pipe.delete(key)
                else:
                    pipe.set(key, target)
                pipe.execute()
                return
            except WatchError:
                continue
    raise RuntimeError("Active scheduler release changed repeatedly")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "change"))
    parser.add_argument("previous_release")
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    settings = ServerSettings.from_env()
    if not settings.release_id or not settings.redis_url:
        raise RuntimeError("The Server container must be configured for release handoff")
    previous = args.previous_release or None
    key = RedisDistributedScheduler.active_release_key(distributed_runtime_prefix(settings, "scheduler"))
    with Redis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=5, socket_timeout=5) as redis:
        if args.action == "check":
            current = redis.get(key)
            if current != previous:
                raise RuntimeError(f"Active scheduler release is {current!r}, expected {previous!r}")
        else:
            expected, target = settings.release_id, previous
            if not args.rollback:
                expected, target = target, expected
            change_active_release(redis, key, expected, target)


if __name__ == "__main__":
    main()

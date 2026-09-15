"""Serialize catalog read/modify/write across Agent, model, MCP and Skill APIs."""

from functools import wraps
from inspect import signature
import hashlib


def catalog_transaction(function):
    sig = signature(function, eval_str=True)

    @wraps(function)
    async def wrapped(*args, **kwargs):
        values = sig.bind(*args, **kwargs).arguments
        service, user = values["service"], values["user"]
        index = int.from_bytes(
            hashlib.sha256(user.user_id.encode()).digest()[:2], "big"
        ) % len(service.catalog_locks)
        async with service.catalog_locks[index]:
            return await function(*args, **kwargs)

    wrapped.__signature__ = sig
    return wrapped

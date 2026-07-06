import asyncio
from typing import (
    Awaitable,
    Callable,
    List,
    Literal,
    Optional,
    Sequence,
    TypeVar,
    Union,
    cast,
    overload,
)

T = TypeVar("T")


@overload
async def run_with_concurrency_limit_ordered(
    limit: int,
    coros: Sequence[Union[Callable[[], Awaitable[T]], Awaitable[T]]],
    progress_callback: Optional[Callable[[int, int], Awaitable[None]]] = None,
    *,
    return_exceptions: Literal[False] = False,
) -> List[T]: ...


@overload
async def run_with_concurrency_limit_ordered(
    limit: int,
    coros: Sequence[Union[Callable[[], Awaitable[T]], Awaitable[T]]],
    progress_callback: Optional[Callable[[int, int], Awaitable[None]]] = None,
    *,
    return_exceptions: Literal[True],
) -> List[Union[T, BaseException]]: ...


async def run_with_concurrency_limit_ordered(
    limit: int,
    coros: Sequence[Union[Callable[[], Awaitable[T]], Awaitable[T]]],
    progress_callback: Optional[Callable[[int, int], Awaitable[None]]] = None,
    *,
    return_exceptions: bool = False,
) -> List[Union[T, BaseException]]:
    semaphore = asyncio.Semaphore(limit)
    results: List[Optional[Union[T, BaseException]]] = [None] * len(coros)
    total = len(coros)
    completed = 0

    async def run_one(
        idx: int,
        coro_or_factory: Union[Callable[[], Awaitable[T]], Awaitable[T]],
    ) -> None:
        nonlocal completed
        async with semaphore:
            awaitable = (
                coro_or_factory() if callable(coro_or_factory) else coro_or_factory
            )
            try:
                results[idx] = await awaitable
            except BaseException as exc:
                if not return_exceptions:
                    raise
                results[idx] = exc
            completed += 1
            if progress_callback:
                await progress_callback(completed, total)

    await asyncio.gather(*[run_one(i, coro) for i, coro in enumerate(coros)])
    return [cast(Union[T, BaseException], item) for item in results]

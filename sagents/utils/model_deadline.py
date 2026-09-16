"""Bound provider startup even when SSE keepalives prevent HTTP read timeouts."""
import asyncio
import os


def first_chunk_timeout_seconds():
    try:
        value = float(os.environ.get("SAGE_MODEL_FIRST_CHUNK_TIMEOUT_SECONDS", "30"))
        if 0 < value <= 600:
            return value
    except (TypeError, ValueError):
        pass
    return 30.0


def preflight_timeout_seconds():
    """One wall-clock budget for optional query generation, including retries."""
    try:
        value = float(os.environ.get("SAGE_PREFLIGHT_TIMEOUT_SECONDS", "10"))
        if 0 < value <= 600:
            return value
    except (TypeError, ValueError):
        pass
    return 10.0


class FirstChunkDeadlineStream:
    def __init__(self, stream, deadline):
        self.stream = stream
        self.iterator = stream.__aiter__()
        self.deadline = deadline
        self.received = False
        self.closed = False

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            if self.received:
                return await self.iterator.__anext__()
            async with asyncio.timeout_at(self.deadline):
                result = await self.iterator.__anext__()
            self.received = True
            return result
        except TimeoutError as exc:
            await self.aclose()
            if self.received:
                raise
            raise TimeoutError("Model first-chunk timeout: provider did not start producing data") from exc
        except BaseException:
            await self.aclose()
            raise

    async def aclose(self):
        if self.closed:
            return
        self.closed = True
        close = getattr(self.iterator, "aclose", None)
        if close is not None:
            await close()
        if self.stream is not self.iterator:
            close = getattr(self.stream, "aclose", None) or getattr(self.stream, "close", None)
            if close is not None:
                await close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.aclose()

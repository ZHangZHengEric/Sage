"""Bounded content-addressed token counts, with no retained prompt bodies."""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
import hashlib
import json
import threading
from sagents.v2._concurrency import bounded_to_thread


class CachedMessageEstimator:
    additive = True

    def _init_cache(self):
        self._cache = OrderedDict()
        self._cache_lock = threading.Lock()

    def estimate(self, messages):
        total = 0
        for message in messages:
            payload = message.model_dump(mode="json")
            media_tokens = 0
            for block in payload.get("content", ()):
                if not isinstance(block, dict) or block.get("kind") != "image":
                    continue
                media_tokens += 256 if block.get("detail") == "low" else 4096
                uri = str(block.get("uri") or "")
                if uri.startswith("data:"):
                    block["uri"] = uri.partition(",")[0] + ",<opaque-image-data>"
            value = json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
            key = (
                self._cache_identity(),
                hashlib.sha256(value.encode("utf-8")).digest(),
            )
            with self._cache_lock:
                count = self._cache.get(key)
                if count is not None:
                    self._cache.move_to_end(key)
            if count is None:
                count = self._text_tokens(value)
                with self._cache_lock:
                    self._cache[key] = count
                    self._cache.move_to_end(key)
                    while len(self._cache) > 2048:
                        self._cache.popitem(last=False)
            total += count + media_tokens
        return total

    async def _estimate_worker(self, messages, *, individual):
        def prepare():
            snapshot = deepcopy(messages)

            def calculate():
                if individual:
                    return tuple(self.estimate((message,)) for message in snapshot)
                return self.estimate(snapshot)

            return calculate

        return await bounded_to_thread("context-cpu", None, prepare=prepare)

    async def estimate_async(self, messages):
        if not messages:
            return 0
        return await self._estimate_worker(messages, individual=False)

    async def estimate_messages_async(self, messages):
        return await self._estimate_worker(messages, individual=True)


class WireSizeTokenEstimator(CachedMessageEstimator):
    """Internal fallback adapter for hosts that do not inject a tokenizer."""

    estimator_id = "wire-size"

    def __init__(self):
        self._init_cache()

    def _cache_identity(self):
        return ()

    def _text_tokens(self, value):
        import math

        return 6 + math.ceil(len(value.encode("utf-8")) / 4.0)

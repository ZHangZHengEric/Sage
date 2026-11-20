"""Incremental inventory of immutable diagnostic parts on the shared volume."""

import asyncio
import time

from sqlalchemy import select, tuple_

from .orm import models


class EvidenceInventory:
    def __init__(self, storage):
        self.storage = storage
        self.sizes = {}
        self.keys = {}
        self.cursor = ""

    def inspect(self):
        # Other server processes publish immutable parts with rename(). Directory
        # mtime changes on both publication and unlink, including during rollback.
        sizes = {}
        for directory in self.storage.root.glob("*/*"):
            try:
                stamp = directory.stat().st_mtime_ns
                previous = self.sizes.get(directory)
                if previous is None or previous[0] != stamp:
                    size = count = 0
                    for part in directory.iterdir():
                        try:
                            size += part.stat().st_size
                            count += 1
                        except FileNotFoundError:
                            pass
                    previous = stamp, size, count
                sizes[directory] = previous
            except FileNotFoundError:
                continue
        self.sizes = sizes
        self.keys = {path: key for path, key in self.keys.items() if path in sizes}
        # Orphan and staging bytes are included. Crossing this upper bound
        # triggers exact referenced-byte accounting before any eviction.
        return sum(size for _, size, _ in sizes.values())

    def candidates(self, limit=100):
        active = sorted(p for p, (_, _, count) in self.sizes.items() if count)
        after = [p for p in active if str(p) > self.cursor]
        page = (after or active)[:limit]
        if page:
            self.cursor = str(page[-1])
        cutoff = time.time() - 3600
        candidates = {}
        for directory in page:
            for part in directory.glob("*"):
                try:
                    if part.is_file() and part.stat().st_mtime < cutoff:
                        candidates.setdefault(directory, []).append(part)
                except FileNotFoundError:
                    pass
        return candidates

    def _remember_keys(self, rows):
        for row in rows:
            key = tuple(row)
            path = self.storage.directory(key)
            if path in self.sizes:
                self.keys[path] = key

    async def referenced_payloads(self, db, candidates, key_names):
        columns = tuple(models.c[n] for n in key_names)
        missing = set(candidates).difference(self.keys)
        if missing:
            # Legacy directories contain a one-way hash. Resolve their owners
            # with keys only, and remember them while the directories exist.
            result = await db.stream(select(*columns).execution_options(yield_per=512))
            try:
                async for page in result.partitions(512):
                    await asyncio.to_thread(self._remember_keys, page)
            finally:
                await result.close()
        keys = [self.keys[p] for p in candidates if p in self.keys]
        payloads = await db.scalars(select(models.c.payload).where(tuple_(*columns).in_(keys)))
        return list(payloads)

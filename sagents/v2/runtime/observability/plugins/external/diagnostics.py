"""External evidence adapter with performance capture and bounded report queries."""

from __future__ import annotations
import asyncio
import httpx
from .evidence import ExternalEvidenceSink
from .._shared.query import QueryCache
from ...performance.aggregation import timing_report
from ...performance.capture import PerformanceCapture
from ...performance.trace_projection import timing_rows


class ExternalDiagnostics(ExternalEvidenceSink):
    def __init__(
        self,
        *,
        performance_max_entries=1024,
        performance_max_rows=4096,
        performance_idle_seconds=300,
        **options,
    ):
        super().__init__(**options)
        self._timings = PerformanceCapture(
            service=self.service,
            environment=self.environment,
            on_failure=self._capture_failed,
            max_entries=performance_max_entries,
            max_rows=performance_max_rows,
            idle_seconds=performance_idle_seconds,
        )
        self._query_cache = QueryCache()

    def _capture_failed(self):
        self.capture_failures += 1

    def bind_trace_sink(self, sink):
        if self.trace_sink is None:
            self.trace_sink = sink
        setter = getattr(sink, "set_span_observer", None)
        if callable(setter):
            setter(self._timings)

    async def close(self):
        self.closed = True
        await self._query_cache.close()
        self._timings.close()
        await super().close()

    def _model(self, session_id, request, **fields):
        self._timings.emit(
            "model",
            dict(
                session_id=session_id,
                run_id=request.run_id,
                request_id=request.request_id,
                **fields,
            ),
        )

    async def report(
        self,
        *,
        start,
        end,
        agent_id="",
        bucket="hour",
        timezone_name="Asia/Shanghai",
        client=None,
    ):
        async def build():
            if client is None:
                async with httpx.AsyncClient() as owned:
                    return await self._report(
                        owned,
                        start=start,
                        end=end,
                        agent_id=agent_id,
                        bucket=bucket,
                        timezone_name=timezone_name,
                    )
            return await self._report(
                client,
                start=start,
                end=end,
                agent_id=agent_id,
                bucket=bucket,
                timezone_name=timezone_name,
            )

        return await self._query_cache.get(
            (start, end, agent_id, bucket, timezone_name), build
        )

    async def _report(self, client, *, start, end, agent_id, bucket, timezone_name):
        spans, truncated = await self._query(
            client, start=start, end=end, agent_id=agent_id
        )

        def aggregate():
            events, models = timing_rows(spans)
            return timing_report(
                events,
                models,
                start=start,
                end=end,
                agent_id=agent_id,
                bucket=bucket,
                timezone_name=timezone_name,
                truncated=truncated,
            )

        result = await asyncio.to_thread(aggregate)
        result.update(source=self.backend, capture_failures=self.capture_failures)
        return result

    def write(self, record):
        self._timings.begin_log(record)
        self._timings.write(record)

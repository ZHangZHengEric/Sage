"""Hosts query observation data without knowing its storage implementation."""

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from datetime import datetime
    from sagents.v2.runtime.observability.contracts import LogLevel

import pytest

from sagents.v2.runtime.observability import LogRecord
from sagents.v2.runtime.observability.provider import (
    ObservabilityProvider,
    create_observability_provider,
)


@pytest.mark.asyncio
async def test_provider_exposes_a_storage_independent_performance_query():
    class Query:
        available = True

        async def report(self, **options):
            return {"summary": {"requests": 2}, "start": options["start"]}

    provider = ObservabilityProvider(plugin_id="test.custom", performance_query=Query())
    try:
        assert provider.performance_available
        result = await provider.report_performance(start=10, end=20)
        assert result["summary"]["requests"] == 2
        assert result["start"] == 10
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_sqlite_performance_is_queried_through_the_provider(tmp_path):
    provider = create_observability_provider(
        "sage.observability.local",
        {
            "diagnostics_root": str(tmp_path),
            "diagnostics_storage": "sqlite",
            "log_stdout": False,
        },
    )
    try:
        provider.logs.write(
            LogRecord(
                level=cast('LogLevel', "info"),
                event="agent.run.started",
                message="started",
                component="test",
                session_id="s",
                run_id="r",
                timestamp=cast('datetime', "2026-10-21T00:00:00Z"),
            )
        )
        provider.logs.write(
            LogRecord(
                level=cast('LogLevel', "info"),
                event="agent.run.completed",
                message="completed",
                component="test",
                session_id="s",
                run_id="r",
                timestamp=cast('datetime', "2026-10-21T00:00:01Z"),
            )
        )
        assert provider.performance_available
        result = await provider.report_performance(start=1792540800, end=1792540810)
        assert result["summary"]["requests"] == 1
        assert result["source"] == "local"
        assert result["capture_failures"] == 0
    finally:
        await provider.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("storage", ["files", "none"])
async def test_capture_without_performance_queries_is_explicit(tmp_path, storage):
    provider = create_observability_provider(
        "sage.observability.local",
        {
            "diagnostics_root": str(tmp_path),
            "diagnostics_storage": storage,
            "log_stdout": False,
        },
    )
    try:
        assert not provider.performance_available
        assert provider.trace_query is None
        with pytest.raises(NotImplementedError):
            await provider.report_performance(start=10, end=20)
    finally:
        await provider.close()

import asyncio
import json
from datetime import date, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import select

from common.core.client.db import close_db_client, get_global_db, init_db_client
from common.core.config import StartupConfig
from common.models.base import Base
from common.models.token_usage import TokenUsage
from common.schemas.base import TokenUsageStatsRequest
from common.services import token_usage_service


def _assert_validation_error(**kwargs):
    try:
        TokenUsageStatsRequest(**kwargs)
    except ValidationError:
        return
    raise AssertionError("expected TokenUsageStatsRequest validation error")


class _FakeSessionContext:
    def __init__(
        self,
        *,
        usage,
        session_id="session-1",
        user_id="user-1",
        agent_id="agent-1",
        start_time=None,
        end_time=None,
    ):
        self._usage = usage
        self.session_id = session_id
        self.user_id = user_id
        self.agent_id = agent_id
        self.start_time = start_time
        self.end_time = end_time

    def get_tokens_usage_info(self):
        return self._usage


async def _reset_test_db():
    await close_db_client()
    db = await init_db_client(StartupConfig(db_type="memory"))
    async with db._engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return db


async def _list_records():
    db = await get_global_db()
    async with db.get_session() as session:  # type: ignore[attr-defined]
        result = await session.execute(select(TokenUsage).order_by(TokenUsage.finished_at))
        return list(result.scalars().all())


def test_record_session_execution_persists_valid_usage():
    async def _run():
        await _reset_test_db()
        started_at = datetime(2026, 4, 23, 10, 0, 0)
        finished_at = datetime(2026, 4, 23, 10, 1, 0)
        ctx = _FakeSessionContext(
            usage={
                "total_info": {
                    "prompt_tokens": 120,
                    "completion_tokens": 30,
                    "total_tokens": 150,
                    "cached_tokens": 15,
                    "reasoning_tokens": 8,
                },
                "per_step_info": [
                    {"step_name": "direct_execution", "usage": {"total_tokens": 100}},
                    {"step_name": "task_complete_judge", "usage": {"total_tokens": 50}},
                ],
            },
            start_time=started_at.timestamp(),
            end_time=finished_at.timestamp(),
        )

        saved = await token_usage_service.record_session_execution(
            session_context=ctx,
            request_source="api/chat",
            started_at=started_at,
            finished_at=finished_at,
        )
        records = await _list_records()

        assert saved is True
        assert len(records) == 1
        assert records[0].request_source == "api/chat"
        assert records[0].input_tokens == 120
        assert records[0].output_tokens == 30
        assert records[0].total_tokens == 150
        assert records[0].cached_tokens == 15
        assert records[0].reasoning_tokens == 8
        assert records[0].step_count == 2
        assert "usage_payload" in TokenUsage.__table__.columns
        assert isinstance(records[0].usage_payload, str)
        assert "total_info" in json.loads(records[0].usage_payload)

        await close_db_client()

    asyncio.run(_run())


def test_session_stats_aggregate_multiple_executions_without_time_range():
    async def _run():
        await _reset_test_db()
        base_time = datetime(2026, 4, 23, 9, 0, 0)
        usage_payload = {
            "total_info": {
                "prompt_tokens": 100,
                "completion_tokens": 40,
                "total_tokens": 140,
                "cached_tokens": 10,
                "reasoning_tokens": 6,
            },
            "per_step_info": [{"step_name": "direct_execution", "usage": {"total_tokens": 140}}],
        }

        for offset in (0, 5):
            ctx = _FakeSessionContext(
                usage=usage_payload,
                session_id="session-agg",
                user_id="user-agg",
                agent_id="agent-agg",
                start_time=(base_time + timedelta(minutes=offset)).timestamp(),
                end_time=(base_time + timedelta(minutes=offset + 1)).timestamp(),
            )
            await token_usage_service.record_session_execution(
                session_context=ctx,
                request_source="api/web-stream",
            )

        stats = await token_usage_service.get_token_usage_stats(
            dimension="session",
            session_id="session-agg",
        )

        assert stats["summary"]["total_tokens"] == 280
        assert stats["summary"]["input_tokens"] == 200
        assert stats["summary"]["output_tokens"] == 80
        assert stats["summary"]["session_count"] == 1
        assert stats["summary"]["average_tokens_per_session"] == 280
        assert stats["summary"]["model_call_count"] == 2
        assert len(stats["items"]) == 1
        item = stats["items"][0]
        assert set(item.keys()) == {
            "agent_id",
            "user_id",
            "session_id",
            "session_count",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "model_call_count",
            "started_at",
            "finished_at",
        }
        assert item["agent_id"] == "agent-agg"
        assert item["user_id"] == "user-agg"
        assert item["session_id"] == "session-agg"
        assert item["session_count"] == 1
        assert item["model_call_count"] == 2
        assert item["total_tokens"] == 280

        await close_db_client()

    asyncio.run(_run())


def test_grouped_stats_support_time_filters():
    async def _run():
        await _reset_test_db()
        old_time = datetime(2026, 4, 20, 10, 0, 0)
        new_time = datetime(2026, 4, 23, 10, 0, 0)

        old_ctx = _FakeSessionContext(
            usage={
                "total_info": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
                "per_step_info": [{"step_name": "direct_execution", "usage": {"total_tokens": 30}}],
            },
            session_id="s-old",
            user_id="user-a",
            agent_id="agent-a",
            start_time=old_time,
            end_time=old_time,
        )
        new_ctx = _FakeSessionContext(
            usage={
                "total_info": {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
                "per_step_info": [{"step_name": "direct_execution", "usage": {"total_tokens": 70}}],
            },
            session_id="s-new",
            user_id="user-b",
            agent_id="agent-b",
            start_time=new_time,
            end_time=new_time,
        )

        await token_usage_service.record_session_execution(session_context=old_ctx, request_source="api/chat")
        await token_usage_service.record_session_execution(session_context=new_ctx, request_source="api/chat")

        stats = await token_usage_service.get_token_usage_stats(
            dimension="user",
            start_date=date(2026, 4, 22),
            end_date=date(2026, 4, 24),
        )

        assert stats["summary"]["model_call_count"] == 1
        assert stats["summary"]["total_tokens"] == 70
        assert len(stats["items"]) == 1
        item = stats["items"][0]
        assert item["agent_id"] == ""
        assert item["user_id"] == "user-b"
        assert item["session_id"] == ""
        assert item["session_count"] == 1
        assert item["total_tokens"] == 70

        await close_db_client()

    asyncio.run(_run())


def test_record_session_execution_skips_invalid_usage():
    async def _run():
        await _reset_test_db()
        ctx = _FakeSessionContext(
            usage={
                "total_info": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                },
                "per_step_info": [{"step_name": "direct_execution", "usage": {"prompt_tokens": 10}}],
            }
        )

        saved = await token_usage_service.record_session_execution(
            session_context=ctx,
            request_source="api/chat",
        )
        stats = await token_usage_service.get_token_usage_stats(
            dimension="session",
            session_id="session-1",
        )

        assert saved is False
        assert stats["summary"]["model_call_count"] == 0
        assert stats["summary"]["total_tokens"] == 0
        assert stats["items"] == []

        await close_db_client()

    asyncio.run(_run())


def test_agent_stats_use_uniform_item_fields_and_filters():
    async def _run():
        await _reset_test_db()
        usage_a = {
            "total_info": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            "per_step_info": [
                {"step_name": "direct_execution", "usage": {"total_tokens": 100}},
                {"step_name": "task_complete_judge", "usage": {"total_tokens": 50}},
            ],
        }
        usage_b = {
            "total_info": {"prompt_tokens": 30, "completion_tokens": 20, "total_tokens": 50},
            "per_step_info": [{"step_name": "direct_execution", "usage": {"total_tokens": 50}}],
        }
        for session_id, usage, source in (
            ("s-a", usage_a, "api/chat"),
            ("s-b", usage_b, "api/chat"),
            ("s-c", usage_b, "api/web-stream"),
        ):
            ctx = _FakeSessionContext(
                usage=usage,
                session_id=session_id,
                user_id="user-1",
                agent_id="agent-1",
                start_time=datetime(2026, 4, 23, 10, 0, 0),
                end_time=datetime(2026, 4, 23, 10, 1, 0),
            )
            await token_usage_service.record_session_execution(
                session_context=ctx,
                request_source=source,
            )

        stats = await token_usage_service.get_token_usage_stats(
            dimension="agent",
            agent_id="agent-1",
            request_source="api/chat",
            start_date=date(2026, 4, 23),
            end_date=date(2026, 4, 23),
        )

        assert stats["summary"] == {
            "input_tokens": 130,
            "output_tokens": 70,
            "total_tokens": 200,
            "session_count": 2,
            "average_tokens_per_session": 100,
            "model_call_count": 3,
        }
        assert len(stats["items"]) == 1
        item = stats["items"][0]
        assert set(item.keys()) == {
            "agent_id",
            "user_id",
            "session_id",
            "session_count",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "model_call_count",
            "started_at",
            "finished_at",
        }
        assert item["agent_id"] == "agent-1"
        assert item["user_id"] == ""
        assert item["session_id"] == ""
        assert item["session_count"] == 2
        assert item["model_call_count"] == 3
        assert item["total_tokens"] == 200

        await close_db_client()

    asyncio.run(_run())


def test_token_usage_stats_request_time_validation():
    TokenUsageStatsRequest(dimension="session", session_id="s-1")
    TokenUsageStatsRequest(
        dimension="session",
        start_date=date(2026, 4, 23),
        end_date=date(2026, 4, 23),
    )
    TokenUsageStatsRequest(
        dimension="agent",
        start_date=date(2026, 4, 23),
        end_date=date(2026, 4, 23),
    )

    _assert_validation_error(dimension="agent")
    _assert_validation_error(dimension="user", start_date=date(2026, 4, 23))
    _assert_validation_error(
        dimension="session",
        start_date=date(2026, 4, 24),
        end_date=date(2026, 4, 23),
    )
    _assert_validation_error(
        dimension="agent",
        start_date=date(2026, 4, 23),
        end_date=date(2026, 4, 23),
        limit=100,
    )
    _assert_validation_error(
        dimension="agent",
        start_date=date(2026, 4, 23),
        end_date=date(2026, 4, 23),
        offset=0,
    )

import asyncio
import random

import httpx
import pytest

from sagents.agent.agent_base import AgentBase


class _DummyAgent(AgentBase):
    async def run_stream(self, session_context):  # pragma: no cover
        if False:
            yield session_context


def _run_async_generator(generator):
    async def _consume():
        async for _ in generator:
            pass

    return asyncio.run(_consume())


def test_lightweight_direct_execution_uses_reduced_retry_budget(monkeypatch):
    async def _raise_connect_error(*args, **kwargs):
        raise httpx.ConnectError("Connection error")

    sleep_calls = []

    async def _fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(
        "sagents.agent.agent_base.create_chat_completion_with_fallback",
        _raise_connect_error,
    )
    monkeypatch.setattr("sagents.agent.agent_base.asyncio.sleep", _fake_sleep)
    monkeypatch.setattr(random, "uniform", lambda a, b: 0)

    agent = _DummyAgent(model=object(), model_config={"model": "dummy-model"})

    with pytest.raises(httpx.ConnectError):
        _run_async_generator(
            agent._call_llm_streaming(
                messages=[{"role": "user", "content": "hello"}],
                session_id=None,
                step_name="direct_execution",
            )
        )

    assert sleep_calls == [2, 2]


def test_actionable_direct_execution_keeps_default_retry_budget(monkeypatch):
    async def _raise_connect_error(*args, **kwargs):
        raise httpx.ConnectError("Connection error")

    sleep_calls = []

    async def _fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(
        "sagents.agent.agent_base.create_chat_completion_with_fallback",
        _raise_connect_error,
    )
    monkeypatch.setattr("sagents.agent.agent_base.asyncio.sleep", _fake_sleep)
    monkeypatch.setattr(random, "uniform", lambda a, b: 0)

    agent = _DummyAgent(model=object(), model_config={"model": "dummy-model"})

    with pytest.raises(httpx.ConnectError):
        _run_async_generator(
            agent._call_llm_streaming(
                messages=[{"role": "user", "content": "inspect this repo"}],
                session_id=None,
                step_name="direct_execution",
            )
        )

    assert sleep_calls == [2, 4, 8, 16, 30, 30, 30]

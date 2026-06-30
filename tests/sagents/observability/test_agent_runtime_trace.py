import asyncio

import sagents.observability.agent_runtime as agent_runtime
from sagents.observability.agent_runtime import ObservableCompletions, ObservableToolManager


class _FakeCompletions:
    class _Client:
        base_url = "http://example.test"

    _client = _Client()

    async def create(self, **kwargs):
        return {"ok": True}


class _FakeObservabilityManager:
    def __init__(self):
        self.llm_start_messages = None
        self.tool_starts = []
        self.tool_ends = []
        self.tool_errors = []

    def on_llm_start(self, session_id, model_name, messages, **kwargs):
        self.llm_start_messages = messages

    def on_llm_end(self, response, **kwargs):
        pass

    def on_llm_error(self, error, **kwargs):
        pass

    def on_tool_start(self, session_id, tool_name, tool_input, **kwargs):
        self.tool_starts.append((session_id, tool_name, tool_input, kwargs))

    def on_tool_end(self, tool_output, **kwargs):
        self.tool_ends.append((tool_output, kwargs))

    def on_tool_error(self, error, **kwargs):
        self.tool_errors.append((error, kwargs))


class _FakeToolManager:
    def __init__(self):
        self.calls = []

    def get_tool(self, tool_name):
        return None

    async def run_tool_async(self, tool_name, session_id, user_id=None, **kwargs):
        self.calls.append((tool_name, session_id, user_id, kwargs))
        return {"ok": True}


def test_observable_completions_preserves_full_llm_messages(monkeypatch):
    async def _run():
        monkeypatch.setattr(
            agent_runtime,
            "_get_current_observability_session_id",
            lambda: "sess_test",
        )
        manager = _FakeObservabilityManager()
        completions = ObservableCompletions(_FakeCompletions(), manager)
        messages = [
            {
                "role": "user",
                "content": "prefix data:image/png;base64,AAAA full payload suffix",
            }
        ]

        await completions.create(model="m1", messages=messages)

        assert manager.llm_start_messages is messages
        assert "data:image/png;base64,AAAA" in manager.llm_start_messages[0]["content"]

    asyncio.run(_run())


def test_observable_tool_manager_wrap_reuses_existing_wrapper():
    async def _run():
        manager = _FakeObservabilityManager()
        base = _FakeToolManager()

        first = ObservableToolManager.wrap(base, manager, "session-1")
        second = ObservableToolManager.wrap(first, manager, "session-1")

        assert second is first

        result = await second.run_tool_async(
            "web_search",
            session_id="session-1",
            query="x",
        )

        assert result == {"ok": True}
        assert len(base.calls) == 1
        assert len(manager.tool_starts) == 1
        assert len(manager.tool_ends) == 1

    asyncio.run(_run())


def test_observable_tool_manager_wrap_rewraps_base_manager_for_new_session():
    manager = _FakeObservabilityManager()
    base = _FakeToolManager()

    first = ObservableToolManager.wrap(base, manager, "session-1")
    second = ObservableToolManager.wrap(first, manager, "session-2")

    assert second is not first
    assert second._tool_manager is base

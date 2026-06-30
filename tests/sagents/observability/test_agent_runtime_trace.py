import asyncio

import sagents.observability.agent_runtime as agent_runtime
from sagents.observability.agent_runtime import ObservableCompletions


class _FakeCompletions:
    class _Client:
        base_url = "http://example.test"

    _client = _Client()

    async def create(self, **kwargs):
        return {"ok": True}


class _FakeObservabilityManager:
    def __init__(self):
        self.llm_start_messages = None

    def on_llm_start(self, session_id, model_name, messages, **kwargs):
        self.llm_start_messages = messages

    def on_llm_end(self, response, **kwargs):
        pass

    def on_llm_error(self, error, **kwargs):
        pass


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

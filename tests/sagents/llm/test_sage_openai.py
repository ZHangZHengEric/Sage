import unittest
from unittest.mock import patch

from sagents.llm.chat import OpenAIChat
from sagents.llm.sage_openai import SageAsyncOpenAI


class _FakeCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)

        async def _stream():
            if False:
                yield None

        return _stream()


class _FakeClient:
    def __init__(self):
        self.chat = type("Chat", (), {})()
        self.chat.completions = _FakeCompletions()

    async def close(self):
        return None


class TestSageAsyncOpenAI(unittest.TestCase):
    def test_fast_model_type_uses_fast_model_name(self):
        standard_client = _FakeClient()
        fast_client = _FakeClient()
        client = SageAsyncOpenAI(
            standard_client=standard_client,
            fast_client=fast_client,
            model_name="standard-model",
            fast_model_name="fast-model",
        )

        stream = client.chat.completions.create(
            model_type="fast",
            model="standard-model",
            messages=[],
            stream=True,
        )

        self.assertEqual(fast_client.chat.completions.calls[0]["model"], "fast-model")
        self.assertEqual(standard_client.chat.completions.calls, [])
        self.assertTrue(hasattr(stream, "__aiter__"))

    def test_fast_model_type_falls_back_without_fast_client(self):
        standard_client = _FakeClient()
        client = SageAsyncOpenAI(
            standard_client=standard_client,
            fast_client=None,
            model_name="standard-model",
            fast_model_name="fast-model",
        )

        client.chat.completions.create(
            model_type="fast",
            model="standard-model",
            messages=[],
            stream=True,
        )

        self.assertEqual(
            standard_client.chat.completions.calls[0]["model"], "standard-model"
        )

    def test_openai_chat_disables_compression_for_streaming_transport(self):
        constructed_clients = []

        class _FakeAsyncOpenAI:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                constructed_clients.append(self)

            async def close(self):
                http_client = self.kwargs.get("http_client")
                if http_client is not None:
                    await http_client.aclose()

        with patch("sagents.llm.chat.AsyncOpenAI", _FakeAsyncOpenAI):
            client = OpenAIChat(
                api_key="test-key",
                base_url="https://provider.example/v1",
                model_name="standard-model",
                fast_model_name="fast-model",
            )

        try:
            self.assertEqual(len(constructed_clients), 2)
            standard_http_client = constructed_clients[0].kwargs["http_client"]
            fast_http_client = constructed_clients[1].kwargs["http_client"]

            self.assertEqual(
                standard_http_client.headers["Accept-Encoding"], "identity"
            )
            self.assertEqual(fast_http_client.headers["Accept-Encoding"], "identity")
            self.assertIsNot(standard_http_client, fast_http_client)
        finally:
            import asyncio

            asyncio.run(client.close())


if __name__ == "__main__":
    unittest.main()

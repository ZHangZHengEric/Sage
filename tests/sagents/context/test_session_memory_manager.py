import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


if "rank_bm25" not in sys.modules:
    fake_rank_bm25 = types.ModuleType("rank_bm25")

    class _FakeBM25Okapi:
        def __init__(self, corpus):
            self.corpus = corpus

        def get_scores(self, query_tokens):
            return [1.0 for _ in self.corpus]

    fake_rank_bm25.BM25Okapi = _FakeBM25Okapi
    sys.modules["rank_bm25"] = fake_rank_bm25


from sagents.context.session_memory.bm25_backend import Bm25SessionMemoryBackend
from sagents.context.session_memory.factory import (
    create_session_memory_manager,
    resolve_session_memory_backend_name,
)
from sagents.context.session_memory.noop_backend import NoopSessionMemoryBackend
from sagents.context.session_memory.session_memory_manager import (
    SessionMemoryManager,
    resolve_session_memory_strategy,
)


class _FakeBackend:
    def __init__(self):
        self.calls = []
        self.cleared = False

    def retrieve_history_messages(self, messages, query, history_budget):
        self.calls.append(("messages", messages, query, history_budget))
        return ["message-result"]

    def retrieve_group_messages_by_chat(self, messages, query, history_budget):
        self.calls.append(("chat", messages, query, history_budget))
        return ["chat-result"]

    def clear_cache(self):
        self.cleared = True


class _FakeMessage:
    def __init__(self, message_id: str, role: str, content: str):
        self.message_id = message_id
        self.role = role
        self._content = content

    def get_content(self):
        return self._content

    def normalized_message_type(self):
        return "text"


class TestSessionMemoryManager(unittest.TestCase):
    def test_default_backend_is_bm25(self):
        manager = SessionMemoryManager()
        self.assertIsInstance(manager.backend, Bm25SessionMemoryBackend)

    def test_manager_delegates_to_backend(self):
        backend = _FakeBackend()
        manager = SessionMemoryManager(backend=backend)

        history = manager.retrieve_history_messages(["m1"], "query", 200)
        chats = manager.retrieve_group_messages_by_chat(["m1"], "query", 300)

        self.assertEqual(history, ["message-result"])
        self.assertEqual(chats, ["chat-result"])
        self.assertEqual(
            backend.calls,
            [
                ("messages", ["m1"], "query", 200),
                ("chat", ["m1"], "query", 300),
            ],
        )

    def test_manager_clear_cache_forwards_to_backend(self):
        backend = _FakeBackend()
        manager = SessionMemoryManager(backend=backend)

        manager.clear_cache()

        self.assertTrue(backend.cleared)

    def test_manager_retrieve_supports_grouped_chat_strategy(self):
        backend = _FakeBackend()
        manager = SessionMemoryManager(backend=backend)

        result = manager.retrieve(["m1"], "query", 200, strategy="grouped_chat")

        self.assertEqual(result, ["chat-result"])
        self.assertEqual(backend.calls, [("chat", ["m1"], "query", 200)])

    def test_factory_defaults_to_bm25_backend(self):
        manager = create_session_memory_manager()
        self.assertIsInstance(manager.backend, Bm25SessionMemoryBackend)

    def test_factory_reads_backend_name_from_env(self):
        with patch.dict("os.environ", {"SAGE_SESSION_MEMORY_BACKEND": "bm25"}):
            manager = create_session_memory_manager()
        self.assertIsInstance(manager.backend, Bm25SessionMemoryBackend)

    def test_factory_supports_noop_backend(self):
        manager = create_session_memory_manager("noop")
        self.assertIsInstance(manager.backend, NoopSessionMemoryBackend)

    def test_factory_prefers_agent_config_over_env(self):
        agent_config = {"memory_backends": {"session_history": "noop"}}
        with patch.dict("os.environ", {"SAGE_SESSION_MEMORY_BACKEND": "bm25"}):
            manager = create_session_memory_manager(agent_config=agent_config)
        self.assertIsInstance(manager.backend, NoopSessionMemoryBackend)

    def test_factory_supports_legacy_agent_config_key(self):
        manager = create_session_memory_manager(agent_config={"session_memory_backend": "noop"})
        self.assertIsInstance(manager.backend, NoopSessionMemoryBackend)

    def test_resolve_backend_name_prefers_explicit_argument(self):
        resolved = resolve_session_memory_backend_name(
            backend_name="bm25",
            agent_config={"memory_backends": {"session_history": "noop"}},
        )
        self.assertEqual(resolved, "bm25")

    def test_resolve_strategy_prefers_agent_config_then_env(self):
        with patch.dict("os.environ", {"SAGE_SESSION_MEMORY_STRATEGY": "messages"}):
            resolved = resolve_session_memory_strategy(
                agent_config={"memory_backends": {"session_history_strategy": "grouped_chat"}}
            )
        self.assertEqual(resolved, "grouped_chat")

    def test_resolve_strategy_supports_legacy_agent_config_key(self):
        resolved = resolve_session_memory_strategy(
            agent_config={"session_memory_strategy": "grouped_chat"}
        )
        self.assertEqual(resolved, "grouped_chat")

    def test_resolve_strategy_rejects_unknown_strategy(self):
        with self.assertRaisesRegex(ValueError, "Unsupported session memory strategy"):
            resolve_session_memory_strategy(agent_config={"session_memory_strategy": "unknown"})

    def test_factory_rejects_unknown_backend(self):
        with self.assertRaisesRegex(ValueError, "Unsupported session memory backend"):
            create_session_memory_manager("unknown")

    def test_bm25_backend_clear_cache_resets_internal_state(self):
        backend = Bm25SessionMemoryBackend()
        messages = [_FakeMessage("m1", "user", "hello world")]

        backend.retrieve_history_messages(messages, "hello", 200)
        self.assertIsNotNone(backend._message_bm25_cache_key)
        self.assertIsNotNone(backend._message_bm25_cache)

        backend.retrieve_group_messages_by_chat(messages, "hello", 200)
        self.assertIsNotNone(backend._chat_bm25_cache_key)
        self.assertIsNotNone(backend._chat_bm25_cache)

        backend.clear_cache()

        self.assertIsNone(backend._message_bm25_cache_key)
        self.assertIsNone(backend._message_bm25_cache)
        self.assertIsNone(backend._chat_bm25_cache_key)
        self.assertIsNone(backend._chat_bm25_cache)


if __name__ == "__main__":
    unittest.main()

import asyncio
import sys
import types
import unittest
from unittest.mock import patch


if "rank_bm25" not in sys.modules:
    fake_rank_bm25 = types.ModuleType("rank_bm25")

    class _FakeBM25Okapi:
        def __init__(self, corpus):
            self.corpus = corpus

        def get_scores(self, query_tokens):
            return [1.0 for _ in self.corpus]

    fake_rank_bm25.BM25Okapi = _FakeBM25Okapi
    sys.modules["rank_bm25"] = fake_rank_bm25


from sagents.tool.impl.file_memory.factory import (
    create_file_memory_backend,
    resolve_file_memory_backend_name,
)
from sagents.tool.impl.file_memory.index_backend import ScopedIndexFileMemoryBackend
from sagents.tool.impl.file_memory.noop_backend import NoopFileMemoryBackend
from sagents.tool.impl.memory_tool import FileMemoryRetriever


class _FakeIndex:
    instances = []
    update_calls = 0

    def __init__(self, sandbox, workspace_path, index_path):
        self.sandbox = sandbox
        self.workspace_path = workspace_path
        self.index_path = index_path
        self._has_search_index = False
        _FakeIndex.instances.append(self)

    def has_search_index(self):
        return self._has_search_index

    async def update_index(self):
        _FakeIndex.update_calls += 1
        self._has_search_index = True
        return {"updated": True}

    def search(self, query, top_k):
        return [
            types.SimpleNamespace(
                path="/workspace/app/cli/example.py",
                content="[Line 3] matched snippet",
            )
        ]


class _FakeMemoryTool:
    def _get_index_path(self, user_id: str, agent_id: str, workspace_path: str) -> str:
        return "/tmp/memory_index.pkl"


class TestFileMemoryBackend(unittest.TestCase):
    def setUp(self):
        ScopedIndexFileMemoryBackend.clear_shared_cache()
        _FakeIndex.instances.clear()
        _FakeIndex.update_calls = 0

    def test_factory_defaults_to_scoped_index_backend(self):
        backend = create_file_memory_backend(_FakeMemoryTool())
        self.assertIsInstance(backend, ScopedIndexFileMemoryBackend)

    def test_factory_supports_noop_backend(self):
        backend = create_file_memory_backend(_FakeMemoryTool(), "noop")
        self.assertIsInstance(backend, NoopFileMemoryBackend)

    def test_factory_prefers_agent_config_over_env(self):
        agent_config = {"memory_backends": {"file_memory": "noop"}}
        with patch.dict("os.environ", {"SAGE_FILE_MEMORY_BACKEND": "scoped_index"}):
            backend = create_file_memory_backend(_FakeMemoryTool(), agent_config=agent_config)
        self.assertIsInstance(backend, NoopFileMemoryBackend)

    def test_factory_supports_legacy_agent_config_key(self):
        backend = create_file_memory_backend(
            _FakeMemoryTool(),
            agent_config={"file_memory_backend": "noop"},
        )
        self.assertIsInstance(backend, NoopFileMemoryBackend)

    def test_resolve_backend_name_prefers_explicit_argument(self):
        resolved = resolve_file_memory_backend_name(
            backend_name="scoped_index",
            agent_config={"memory_backends": {"file_memory": "noop"}},
        )
        self.assertEqual(resolved, "scoped_index")

    def test_factory_rejects_unknown_backend(self):
        with self.assertRaisesRegex(ValueError, "Unsupported file memory backend"):
            create_file_memory_backend(_FakeMemoryTool(), "unknown")

    def test_noop_backend_returns_no_results(self):
        backend = NoopFileMemoryBackend(_FakeMemoryTool())
        result = asyncio.run(backend.search("provider", 3, types.SimpleNamespace()))
        self.assertEqual(result, [])

    def test_scoped_index_backend_reuses_index_cache(self):
        backend = ScopedIndexFileMemoryBackend(_FakeMemoryTool())
        session_context = types.SimpleNamespace(
            sandbox=object(),
            sandbox_agent_workspace="/workspace",
            agent_id="agent-a",
            user_id="alice",
        )

        with patch("sagents.tool.impl.memory_index.MemoryIndex", _FakeIndex):
            first = asyncio.run(backend.search("provider", 3, session_context))
            second = asyncio.run(backend.search("provider", 3, session_context))

        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(len(_FakeIndex.instances), 1)
        self.assertEqual(_FakeIndex.update_calls, 1)

    def test_retriever_uses_agent_config_backend_selection(self):
        retriever = FileMemoryRetriever(_FakeMemoryTool())
        session_context = types.SimpleNamespace(
            sandbox=object(),
            sandbox_agent_workspace="/workspace",
            agent_id="agent-a",
            user_id="alice",
            agent_config={"memory_backends": {"file_memory": "noop"}},
        )

        with patch.dict("os.environ", {"SAGE_FILE_MEMORY_BACKEND": "scoped_index"}):
            result = asyncio.run(retriever.search("provider", 3, session_context))

        self.assertEqual(result, [])
        self.assertIsInstance(retriever.backend, NoopFileMemoryBackend)


if __name__ == "__main__":
    unittest.main()

import asyncio
import sys
import threading
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

    fake_rank_bm25.BM25Okapi = _FakeBM25Okapi  # pyright: ignore[reportAttributeAccessIssue]
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

    def clear_index(self):
        raise AssertionError("in-memory release must not delete the persisted index")


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
            backend = create_file_memory_backend(
                _FakeMemoryTool(), agent_config=agent_config
            )
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

    def test_scoped_index_backend_releases_index_after_each_sequential_search(self):
        backend = ScopedIndexFileMemoryBackend(_FakeMemoryTool())
        session_context = types.SimpleNamespace(
            sandbox=object(),
            sandbox_agent_workspace="/workspace",
            agent_id="agent-a",
            user_id="alice",
        )

        with patch("sagents.tool.impl.memory_index.MemoryIndex", _FakeIndex):
            first = asyncio.run(backend.search("provider", 3, session_context))
            self.assertEqual(ScopedIndexFileMemoryBackend._index_cache, {})
            second = asyncio.run(backend.search("provider", 3, session_context))

        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(len(_FakeIndex.instances), 2)
        self.assertEqual(_FakeIndex.update_calls, 2)
        self.assertEqual(ScopedIndexFileMemoryBackend._index_cache, {})

    def test_scoped_index_backend_shares_only_between_concurrent_searches(self):
        backend = ScopedIndexFileMemoryBackend(_FakeMemoryTool())
        session_context = types.SimpleNamespace(
            sandbox=object(),
            sandbox_agent_workspace="/workspace",
            agent_id="agent-a",
            user_id="alice",
        )

        async def scenario():
            update_started = asyncio.Event()
            allow_update = asyncio.Event()

            class _BlockingIndex(_FakeIndex):
                async def update_index(self):
                    _FakeIndex.update_calls += 1
                    self._has_search_index = True
                    update_started.set()
                    await allow_update.wait()
                    return {"updated": True}

            with patch("sagents.tool.impl.memory_index.MemoryIndex", _BlockingIndex):
                first_task = asyncio.create_task(
                    backend.search("first", 3, session_context)
                )
                await update_started.wait()
                second_task = asyncio.create_task(
                    backend.search("second", 3, session_context)
                )
                await asyncio.sleep(0)

                scope_key = backend._build_scope_key("alice", "agent-a", "/workspace")
                cache_entry = backend._index_cache[scope_key]
                self.assertEqual(cache_entry.active_searches, 2)
                self.assertEqual(len(_FakeIndex.instances), 1)

                allow_update.set()
                results = await asyncio.gather(first_task, second_task)

            self.assertEqual([len(result) for result in results], [1, 1])
            self.assertEqual(len(_FakeIndex.instances), 1)
            self.assertEqual(_FakeIndex.update_calls, 1)
            self.assertEqual(backend._index_cache, {})

        asyncio.run(scenario())

    def test_scoped_index_backend_keeps_different_scopes_isolated(self):
        backend = ScopedIndexFileMemoryBackend(_FakeMemoryTool())
        alice_context = types.SimpleNamespace(
            sandbox=object(),
            sandbox_agent_workspace="/workspace",
            agent_id="agent-a",
            user_id="alice",
        )
        bob_context = types.SimpleNamespace(
            sandbox=object(),
            sandbox_agent_workspace="/workspace",
            agent_id="agent-a",
            user_id="bob",
        )

        async def scenario():
            started_count = 0
            both_started = asyncio.Event()
            allow_updates = asyncio.Event()

            class _TwoScopeIndex(_FakeIndex):
                async def update_index(self):
                    nonlocal started_count
                    started_count += 1
                    self._has_search_index = True
                    if started_count == 2:
                        both_started.set()
                    await allow_updates.wait()
                    return {"updated": True}

            with patch("sagents.tool.impl.memory_index.MemoryIndex", _TwoScopeIndex):
                alice_task = asyncio.create_task(
                    backend.search("alice", 3, alice_context)
                )
                bob_task = asyncio.create_task(backend.search("bob", 3, bob_context))
                await both_started.wait()

                self.assertEqual(len(backend._index_cache), 2)
                self.assertEqual(len(_FakeIndex.instances), 2)

                allow_updates.set()
                await asyncio.gather(alice_task, bob_task)

            self.assertEqual(backend._index_cache, {})

        asyncio.run(scenario())

    def test_scoped_index_backend_releases_index_after_failures(self):
        backend = ScopedIndexFileMemoryBackend(_FakeMemoryTool())
        session_context = types.SimpleNamespace(
            sandbox=object(),
            sandbox_agent_workspace="/workspace",
            agent_id="agent-a",
            user_id="alice",
        )

        class _InitializationFailure:
            def __init__(self, sandbox, workspace_path, index_path):
                raise RuntimeError("initialization failed")

        class _UpdateFailure(_FakeIndex):
            async def update_index(self):
                raise RuntimeError("update failed")

        class _SearchFailure(_FakeIndex):
            def search(self, query, top_k):
                raise RuntimeError("search failed")

        for failing_index in (
            _InitializationFailure,
            _UpdateFailure,
            _SearchFailure,
        ):
            with self.subTest(failing_index=failing_index.__name__):
                with patch(
                    "sagents.tool.impl.memory_index.MemoryIndex", failing_index
                ):
                    result = asyncio.run(
                        backend.search("provider", 3, session_context)
                    )
                self.assertEqual(result, [])
                self.assertEqual(backend._index_cache, {})

    def test_scoped_index_backend_releases_index_after_cancellation(self):
        backend = ScopedIndexFileMemoryBackend(_FakeMemoryTool())
        session_context = types.SimpleNamespace(
            sandbox=object(),
            sandbox_agent_workspace="/workspace",
            agent_id="agent-a",
            user_id="alice",
        )

        async def scenario():
            search_started = threading.Event()
            allow_search = threading.Event()

            class _CancellableIndex(_FakeIndex):
                def search(self, query, top_k):
                    search_started.set()
                    allow_search.wait(timeout=5)
                    return super().search(query, top_k)

            with patch("sagents.tool.impl.memory_index.MemoryIndex", _CancellableIndex):
                search_task = asyncio.create_task(
                    backend.search("provider", 3, session_context)
                )
                started = await asyncio.to_thread(search_started.wait, 2)
                self.assertTrue(started)
                search_task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await search_task

                scope_key = backend._build_scope_key("alice", "agent-a", "/workspace")
                self.assertEqual(backend._index_cache[scope_key].active_searches, 1)

                second_task = asyncio.create_task(
                    backend.search("second", 3, session_context)
                )
                await asyncio.sleep(0)
                self.assertEqual(backend._index_cache[scope_key].active_searches, 2)
                self.assertEqual(len(_FakeIndex.instances), 1)

                allow_search.set()
                second_result = await second_task
                await asyncio.sleep(0)

            self.assertEqual(len(second_result), 1)
            self.assertEqual(len(_FakeIndex.instances), 1)
            self.assertEqual(backend._index_cache, {})

        asyncio.run(scenario())

    def test_retriever_uses_agent_config_backend_selection(self):
        retriever = FileMemoryRetriever(_FakeMemoryTool())  # pyright: ignore[reportArgumentType]
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

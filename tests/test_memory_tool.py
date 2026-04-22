import asyncio
import importlib
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
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


def _load_memory_tool_module():
    return importlib.import_module("sagents.tool.impl.memory_tool")


def _load_tool_manager_class():
    module = importlib.import_module("sagents.tool.tool_manager")
    return module.ToolManager


class _FakeMessage:
    def __init__(self, message_id: str, role: str, content: str):
        self.message_id = message_id
        self.role = role
        self.content = content
        self.timestamp = 123

    def get_content(self):
        return self.content

    def normalized_message_type(self):
        return "text"


class _FakeMessageManager:
    def __init__(self, messages, history_messages):
        self.messages = messages
        self._history_messages = history_messages
        self.prepare_calls = 0

    def prepare_history_split(self, agent_config):
        self.prepare_calls += 1
        return {
            "split_result": {
                "history_messages": self._history_messages,
            }
        }


class _FakeSessionMemoryManager:
    def __init__(self, retrieved_messages):
        self.retrieved_messages = retrieved_messages
        self.calls = 0

    def retrieve_history_messages(self, messages, query, history_budget):
        self.calls += 1
        return self.retrieved_messages


class _FakeIndex:
    instances = []
    update_calls = 0
    search_calls = []

    def __init__(self, sandbox, workspace_path, index_path):
        self.sandbox = sandbox
        self.workspace_path = workspace_path
        self.index_path = index_path
        self._has_search_index = False
        self.update_count = 0
        _FakeIndex.instances.append(self)

    def has_search_index(self):
        return self._has_search_index

    async def update_index(self):
        self.update_count += 1
        _FakeIndex.update_calls += 1
        self._has_search_index = True
        return {"updated": True}

    def search(self, query, top_k):
        _FakeIndex.search_calls.append((query, top_k, self.workspace_path))
        return [
            types.SimpleNamespace(
                path="/workspace/app/cli/example.py",
                content="[Line 3] matched snippet",
                line_number=3,
            )
        ]


class TestMemoryTool(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_memory_tool_module()
        cls.MemoryTool = cls.module.MemoryTool
        cls.FileMemoryRetriever = cls.module.FileMemoryRetriever
        cls.SessionHistoryRetriever = cls.module.SessionHistoryRetriever
        cls.ToolManager = _load_tool_manager_class()

    def setUp(self):
        self.FileMemoryRetriever.clear_cache()
        self.SessionHistoryRetriever.clear_cache()
        _FakeIndex.instances.clear()
        _FakeIndex.update_calls = 0
        _FakeIndex.search_calls.clear()

    def test_search_memory_error_contract_is_stable(self):
        tool = self.MemoryTool()

        missing_session = asyncio.run(tool.search_memory(query="hello", top_k=3, session_id=None))
        self.assertEqual(missing_session["status"], "error")
        self.assertEqual(missing_session["long_term_memory"], [])
        self.assertEqual(missing_session["session_history"], [])

        missing_query = asyncio.run(tool.search_memory(query=" ", top_k=3, session_id="s1"))
        self.assertEqual(missing_query["status"], "error")
        self.assertEqual(missing_query["long_term_memory"], [])
        self.assertEqual(missing_query["session_history"], [])

    def test_session_history_retriever_reuses_prepare_history_split_cache(self):
        tool = self.MemoryTool()
        messages = [_FakeMessage("m1", "user", "hello session")]
        history_messages = [_FakeMessage("h1", "assistant", "history snippet")]
        message_manager = _FakeMessageManager(messages=messages, history_messages=history_messages)
        session_memory_manager = _FakeSessionMemoryManager(retrieved_messages=history_messages)
        session_context = types.SimpleNamespace(
            message_manager=message_manager,
            agent_config={"name": "demo"},
            session_memory_manager=session_memory_manager,
        )

        results1 = tool.session_history_retriever.search("history", 3, "session-1", session_context)
        results2 = tool.session_history_retriever.search("history", 3, "session-1", session_context)

        self.assertEqual(message_manager.prepare_calls, 1)
        self.assertEqual(session_memory_manager.calls, 2)
        self.assertEqual(len(results1), 1)
        self.assertEqual(len(results2), 1)

        messages.append(_FakeMessage("m2", "user", "new history"))
        tool.session_history_retriever.search("history", 3, "session-1", session_context)
        self.assertEqual(message_manager.prepare_calls, 2)

    def test_session_history_retriever_invalidates_cache_on_agent_config_change(self):
        tool = self.MemoryTool()
        history_messages = [_FakeMessage("h1", "assistant", "history snippet")]
        session_context = types.SimpleNamespace(
            message_manager=_FakeMessageManager(
                messages=[_FakeMessage("m1", "user", "hello session")],
                history_messages=history_messages,
            ),
            agent_config={"name": "demo-v1"},
            session_memory_manager=_FakeSessionMemoryManager(retrieved_messages=history_messages),
        )

        tool.session_history_retriever.search("history", 3, "session-1", session_context)
        tool.session_history_retriever.search("history", 3, "session-1", session_context)
        self.assertEqual(session_context.message_manager.prepare_calls, 1)

        session_context.agent_config = {"name": "demo-v2"}
        tool.session_history_retriever.search("history", 3, "session-1", session_context)
        self.assertEqual(session_context.message_manager.prepare_calls, 2)

    def test_file_memory_retriever_reuses_scoped_index_and_refreshes_once(self):
        tool = self.MemoryTool()
        session_context = types.SimpleNamespace(
            sandbox=object(),
            sandbox_agent_workspace="/workspace",
            agent_id="agent-a",
            user_id="alice",
        )

        with patch("sagents.tool.impl.memory_index.MemoryIndex", _FakeIndex):
            results1 = asyncio.run(tool.file_memory_retriever.search("provider cli", 3, session_context))
            results2 = asyncio.run(tool.file_memory_retriever.search("provider cli", 3, session_context))

        self.assertEqual(len(_FakeIndex.instances), 1)
        self.assertEqual(_FakeIndex.update_calls, 1)
        self.assertEqual(len(results1), 1)
        self.assertEqual(len(results2), 1)
        self.assertEqual(results1[0]["path"], "/workspace/app/cli/example.py")
        self.assertEqual(results1[0]["snippets"][0]["line_number"], 3)

    def test_file_memory_retriever_refreshes_again_when_cached_index_is_stale(self):
        tool = self.MemoryTool()
        session_context = types.SimpleNamespace(
            sandbox=object(),
            sandbox_agent_workspace="/workspace",
            agent_id="agent-a",
            user_id="alice",
        )

        with patch("sagents.tool.impl.memory_index.MemoryIndex", _FakeIndex):
            asyncio.run(tool.file_memory_retriever.search("provider cli", 3, session_context))

            scope_key = tool.file_memory_retriever._build_scope_key(
                user_id="alice",
                agent_id="agent-a",
                workspace_path="/workspace",
            )
            cache_entry = tool.file_memory_retriever._index_cache[scope_key]
            cache_entry.last_refresh_at = 0.0

            asyncio.run(tool.file_memory_retriever.search("provider cli", 3, session_context))

        self.assertEqual(len(_FakeIndex.instances), 1)
        self.assertEqual(_FakeIndex.update_calls, 2)

    def test_search_memory_success_returns_split_results(self):
        tool = self.MemoryTool()

        async def fake_file_search(query, top_k, session_id):
            return [{"path": "/workspace/app/cli/example.py", "snippets": [{"line_number": 2, "text": "provider"}]}]

        async def fake_history_search(query, top_k, session_id):
            return [{"role": "assistant", "content_preview": "history", "timestamp": 123}]

        with patch.object(tool, "_search_file_memory", fake_file_search), patch.object(tool, "_search_session_history", fake_history_search):
            result = asyncio.run(tool.search_memory(query="provider", top_k=3, session_id="session-1"))

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["query"], "provider")
        self.assertEqual(len(result["long_term_memory"]), 1)
        self.assertEqual(len(result["session_history"]), 1)

    def test_tool_manager_run_tool_async_injects_session_id_for_search_memory(self):
        tool = self.MemoryTool()
        manager = self.ToolManager(is_auto_discover=False, isolated=True)
        manager.register_tools_from_object(tool)

        async def fake_file_search(query, top_k, session_id):
            self.assertEqual(session_id, "session-tool")
            return [{"path": "/workspace/app/cli/example.py", "snippets": []}]

        async def fake_history_search(query, top_k, session_id):
            self.assertEqual(session_id, "session-tool")
            return [{"role": "assistant", "content_preview": "history", "timestamp": 123}]

        with patch.object(tool, "_search_file_memory", fake_file_search), patch.object(tool, "_search_session_history", fake_history_search):
            raw = asyncio.run(
                manager.run_tool_async(
                    tool_name="search_memory",
                    session_id="session-tool",
                    query="provider",
                    top_k=2,
                )
            )

        payload = json.loads(raw)
        self.assertIn("content", payload)
        self.assertEqual(payload["content"]["status"], "success")
        self.assertEqual(payload["content"]["query"], "provider")
        self.assertEqual(len(payload["content"]["long_term_memory"]), 1)
        self.assertEqual(len(payload["content"]["session_history"]), 1)


if __name__ == "__main__":
    unittest.main()

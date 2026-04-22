import importlib.util
import pickle
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_memory_index_module():
    module_path = (
        REPO_ROOT
        / "sagents"
        / "tool"
        / "impl"
        / "memory_index.py"
    )
    spec = importlib.util.spec_from_file_location("memory_index_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestMemoryIndexFTS(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_memory_index_module()
        cls.MemoryIndex = cls.module.MemoryIndex

    def test_fts_search_returns_focused_chunk_result(self):
        with TemporaryDirectory() as tmp_dir:
            index_path = Path(tmp_dir) / "memory_index.pkl"
            idx = self.MemoryIndex(sandbox=None, workspace_path="/workspace", index_path=str(index_path))

            content = "\n".join(
                [
                    "ordinary line 1",
                    "ordinary line 2",
                    "ordinary line 3",
                    "P2ChunkUniqueOmega",
                    "ordinary line 5",
                ]
            )
            idx._replace_file_documents("/workspace/p2_chunk_test.txt", content, 1.0, len(content))
            idx._sync_file_to_fts("/workspace/p2_chunk_test.txt")
            idx._save_index()

            results = idx.search("P2ChunkUniqueOmega", top_k=3)

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].path, "/workspace/p2_chunk_test.txt")
            self.assertEqual(results[0].line_number, 4)
            self.assertIn("P2ChunkUniqueOmega", results[0].content)

    def test_init_clears_stale_fts_rows_when_sidecar_is_empty(self):
        with TemporaryDirectory() as tmp_dir:
            index_path = Path(tmp_dir) / "memory_index.pkl"
            idx = self.MemoryIndex(sandbox=None, workspace_path="/workspace", index_path=str(index_path))
            content = "stale keyword"
            idx._replace_file_documents("/workspace/stale.txt", content, 1.0, len(content))
            idx._sync_file_to_fts("/workspace/stale.txt")
            idx._save_index()

            stale_sqlite = index_path.with_suffix(".sqlite3")
            self.assertTrue(stale_sqlite.exists())
            self.assertTrue(idx._fts_has_documents())

            with open(index_path, "wb") as f:
                pickle.dump(
                    {
                        "schema_version": self.MemoryIndex.INDEX_SCHEMA_VERSION,
                        "bm25": None,
                        "documents": {},
                        "path_to_doc_ids": {},
                        "dir_mtime_cache": {},
                        "document_count": 0,
                    },
                    f,
                )

            reloaded = self.MemoryIndex(sandbox=None, workspace_path="/workspace", index_path=str(index_path))

            self.assertEqual(reloaded.get_document_count(), 0)
            self.assertFalse(reloaded._fts_has_documents())
            self.assertEqual(reloaded.search("stale", top_k=5), [])

    def test_search_prefers_file_with_multiple_relevant_chunks(self):
        with TemporaryDirectory() as tmp_dir:
            index_path = Path(tmp_dir) / "memory_index.pkl"
            idx = self.MemoryIndex(sandbox=None, workspace_path="/workspace", index_path=str(index_path))
            idx.DEFAULT_CHUNK_SIZE = 60
            idx.DEFAULT_CHUNK_OVERLAP = 0

            single_hit_content = "\n".join(
                [
                    "ordinary filler line 1",
                    "ordinary filler line 2",
                    "P1ChunkUniqueGamma appears once here",
                    "ordinary filler line 4",
                    "ordinary filler line 5",
                ]
            )
            multi_hit_content = "\n".join(
                [
                    "P1ChunkUniqueGamma appears in the opening section",
                    "ordinary filler block A " * 3,
                    "ordinary filler block B " * 3,
                    "ordinary filler block C " * 3,
                    "P1ChunkUniqueGamma appears again in a later section",
                    "ordinary filler block D " * 3,
                ]
            )

            idx._replace_file_documents("/workspace/single_hit.txt", single_hit_content, 1.0, len(single_hit_content))
            idx._replace_file_documents("/workspace/multi_hit.txt", multi_hit_content, 1.0, len(multi_hit_content))
            idx._sync_file_to_fts("/workspace/single_hit.txt")
            idx._sync_file_to_fts("/workspace/multi_hit.txt")
            idx._save_index()

            results = idx.search("P1ChunkUniqueGamma", top_k=2)

            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].path, "/workspace/multi_hit.txt")
            self.assertEqual(results[1].path, "/workspace/single_hit.txt")
            self.assertIn("P1ChunkUniqueGamma", results[0].content)

    def test_search_prefers_file_covering_more_query_terms_across_chunks(self):
        with TemporaryDirectory() as tmp_dir:
            index_path = Path(tmp_dir) / "memory_index.pkl"
            idx = self.MemoryIndex(sandbox=None, workspace_path="/workspace", index_path=str(index_path))
            idx.DEFAULT_CHUNK_SIZE = 50
            idx.DEFAULT_CHUNK_OVERLAP = 0

            split_terms_content = "\n".join(
                [
                    "AlphaBridgeUnique appears in the opening section",
                    "ordinary filler block " * 4,
                    "ordinary filler block " * 4,
                    "BetaSignalUnique appears in the closing section",
                ]
            )
            single_term_content = "\n".join(
                [
                    "AlphaBridgeUnique appears repeatedly",
                    "AlphaBridgeUnique appears repeatedly again",
                    "ordinary filler block " * 4,
                    "ordinary filler ending",
                ]
            )

            idx._replace_file_documents("/workspace/split_terms.txt", split_terms_content, 1.0, len(split_terms_content))
            idx._replace_file_documents("/workspace/single_term.txt", single_term_content, 1.0, len(single_term_content))
            idx._sync_file_to_fts("/workspace/split_terms.txt")
            idx._sync_file_to_fts("/workspace/single_term.txt")
            idx._save_index()

            results = idx.search("AlphaBridgeUnique BetaSignalUnique", top_k=2)

            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].path, "/workspace/split_terms.txt")
            self.assertTrue(
                "AlphaBridgeUnique" in results[0].content
                or "BetaSignalUnique" in results[0].content
            )

    def test_search_prefers_query_coverage_over_single_term_repetition(self):
        with TemporaryDirectory() as tmp_dir:
            index_path = Path(tmp_dir) / "memory_index.pkl"
            idx = self.MemoryIndex(sandbox=None, workspace_path="/workspace", index_path=str(index_path))
            idx.DEFAULT_CHUNK_SIZE = 45
            idx.DEFAULT_CHUNK_OVERLAP = 0

            repeated_single_term_content = "\n".join(
                [
                    "AlphaBridgeUnique repeated heavily in section one",
                    "AlphaBridgeUnique repeated heavily in section two",
                    "AlphaBridgeUnique repeated heavily in section three",
                    "AlphaBridgeUnique repeated heavily in section four",
                    "ordinary filler ending",
                ]
            )
            full_query_coverage_content = "\n".join(
                [
                    "AlphaBridgeUnique appears in the first section",
                    "ordinary filler block " * 3,
                    "BetaSignalUnique appears in the middle section",
                    "ordinary filler block " * 3,
                    "GammaTraceUnique appears in the closing section",
                ]
            )

            idx._replace_file_documents("/workspace/repeated_single_term.txt", repeated_single_term_content, 1.0, len(repeated_single_term_content))
            idx._replace_file_documents("/workspace/full_query_coverage.txt", full_query_coverage_content, 1.0, len(full_query_coverage_content))
            idx._sync_file_to_fts("/workspace/repeated_single_term.txt")
            idx._sync_file_to_fts("/workspace/full_query_coverage.txt")
            idx._save_index()

            results = idx.search("AlphaBridgeUnique BetaSignalUnique GammaTraceUnique", top_k=2)

            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].path, "/workspace/full_query_coverage.txt")
            self.assertEqual(results[1].path, "/workspace/repeated_single_term.txt")

    def test_multi_term_preview_can_include_multiple_chunks(self):
        with TemporaryDirectory() as tmp_dir:
            index_path = Path(tmp_dir) / "memory_index.pkl"
            idx = self.MemoryIndex(sandbox=None, workspace_path="/workspace", index_path=str(index_path))
            idx.DEFAULT_CHUNK_SIZE = 45
            idx.DEFAULT_CHUNK_OVERLAP = 0

            content = "\n".join(
                [
                    "AlphaBridgeUnique appears in the opening section",
                    "ordinary filler block " * 3,
                    "BetaSignalUnique appears in the middle section",
                    "ordinary filler block " * 3,
                    "GammaTraceUnique appears in the closing section",
                ]
            )

            idx._replace_file_documents("/workspace/multi_preview.txt", content, 1.0, len(content))
            idx._sync_file_to_fts("/workspace/multi_preview.txt")
            idx._save_index()

            results = idx.search("AlphaBridgeUnique BetaSignalUnique GammaTraceUnique", top_k=1)

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].path, "/workspace/multi_preview.txt")
            self.assertIn("AlphaBridgeUnique", results[0].content)
            self.assertIn("BetaSignalUnique", results[0].content)
            self.assertIn("GammaTraceUnique", results[0].content)

    def test_search_prefers_nearby_term_clusters_over_scattered_hits(self):
        with TemporaryDirectory() as tmp_dir:
            index_path = Path(tmp_dir) / "memory_index.pkl"
            idx = self.MemoryIndex(sandbox=None, workspace_path="/workspace", index_path=str(index_path))
            idx.DEFAULT_CHUNK_SIZE = 45
            idx.DEFAULT_CHUNK_OVERLAP = 0

            clustered_content = "\n".join(
                [
                    "AlphaBridgeUnique BetaSignalUnique appear together",
                    "GammaTraceUnique appears immediately after",
                    "ordinary filler ending",
                ]
            )
            scattered_content = "\n".join(
                [
                    "AlphaBridgeUnique appears first",
                    "ordinary filler block " * 3,
                    "BetaSignalUnique appears later",
                    "ordinary filler block " * 3,
                    "GammaTraceUnique appears last",
                ]
            )

            idx._replace_file_documents("/workspace/clustered_terms.txt", clustered_content, 1.0, len(clustered_content))
            idx._replace_file_documents("/workspace/scattered_terms.txt", scattered_content, 1.0, len(scattered_content))
            idx._sync_file_to_fts("/workspace/clustered_terms.txt")
            idx._sync_file_to_fts("/workspace/scattered_terms.txt")
            idx._save_index()

            results = idx.search("AlphaBridgeUnique BetaSignalUnique GammaTraceUnique", top_k=2)

            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].path, "/workspace/clustered_terms.txt")
            self.assertEqual(results[1].path, "/workspace/scattered_terms.txt")

    def test_search_prefers_tighter_full_query_chunk_span(self):
        with TemporaryDirectory() as tmp_dir:
            index_path = Path(tmp_dir) / "memory_index.pkl"
            idx = self.MemoryIndex(sandbox=None, workspace_path="/workspace", index_path=str(index_path))
            idx.DEFAULT_CHUNK_SIZE = 45
            idx.DEFAULT_CHUNK_OVERLAP = 0

            tighter_span_content = "\n".join(
                [
                    "AlphaBridgeUnique appears first",
                    "BetaSignalUnique appears immediately after",
                    "GammaTraceUnique appears right after that",
                    "ordinary filler ending",
                ]
            )
            wider_span_content = "\n".join(
                [
                    "AlphaBridgeUnique appears first",
                    "ordinary filler block " * 3,
                    "BetaSignalUnique appears later",
                    "ordinary filler block " * 3,
                    "GammaTraceUnique appears much later",
                ]
            )

            idx._replace_file_documents("/workspace/tighter_span.txt", tighter_span_content, 1.0, len(tighter_span_content))
            idx._replace_file_documents("/workspace/wider_span.txt", wider_span_content, 1.0, len(wider_span_content))
            idx._sync_file_to_fts("/workspace/tighter_span.txt")
            idx._sync_file_to_fts("/workspace/wider_span.txt")
            idx._save_index()

            results = idx.search("AlphaBridgeUnique BetaSignalUnique GammaTraceUnique", top_k=2)

            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].path, "/workspace/tighter_span.txt")
            self.assertEqual(results[1].path, "/workspace/wider_span.txt")

    def test_multi_term_candidate_fetch_prefers_full_matches_before_partial_matches(self):
        with TemporaryDirectory() as tmp_dir:
            index_path = Path(tmp_dir) / "memory_index.pkl"
            idx = self.MemoryIndex(sandbox=None, workspace_path="/workspace", index_path=str(index_path))
            idx.DEFAULT_CHUNK_SIZE = 45
            idx.DEFAULT_CHUNK_OVERLAP = 0

            for i in range(24):
                noisy_content = "\n".join(
                    [
                        f"AlphaBridgeUnique repeated heavily in noisy file {i}",
                        "AlphaBridgeUnique repeated again",
                        "AlphaBridgeUnique repeated a third time",
                        "AlphaBridgeUnique repeated a fourth time",
                        "ordinary filler ending",
                    ]
                )
                noisy_path = f"/workspace/noisy_alpha_{i}.txt"
                idx._replace_file_documents(noisy_path, noisy_content, 1.0, len(noisy_content))
                idx._sync_file_to_fts(noisy_path)

            full_match_content = "\n".join(
                [
                    "AlphaBridgeUnique appears first",
                    "BetaSignalUnique appears next",
                    "GammaTraceUnique appears after that",
                    "ordinary filler ending",
                ]
            )
            idx._replace_file_documents("/workspace/full_match.txt", full_match_content, 1.0, len(full_match_content))
            idx._sync_file_to_fts("/workspace/full_match.txt")
            idx._save_index()

            results = idx.search("AlphaBridgeUnique BetaSignalUnique GammaTraceUnique", top_k=3)

            self.assertGreaterEqual(len(results), 1)
            self.assertEqual(results[0].path, "/workspace/full_match.txt")

    def test_preview_row_selection_skips_redundant_overlapping_chunks(self):
        with TemporaryDirectory() as tmp_dir:
            index_path = Path(tmp_dir) / "memory_index.pkl"
            idx = self.MemoryIndex(sandbox=None, workspace_path="/workspace", index_path=str(index_path))

            rows = [
                {
                    "content": "AlphaBridgeUnique and BetaSignalUnique appear together in the first chunk",
                    "line_start": 10,
                    "line_end": 20,
                    "chunk_index": 0,
                    "raw_score": -10.0,
                },
                {
                    "content": "AlphaBridgeUnique and BetaSignalUnique appear together again in an overlapping chunk",
                    "line_start": 12,
                    "line_end": 22,
                    "chunk_index": 1,
                    "raw_score": -9.0,
                },
                {
                    "content": "GammaTraceUnique appears later in a separate chunk",
                    "line_start": 30,
                    "line_end": 36,
                    "chunk_index": 3,
                    "raw_score": -8.0,
                },
            ]

            selected = idx._select_preview_rows(
                rows,
                ["AlphaBridgeUnique", "BetaSignalUnique", "GammaTraceUnique"],
                max_rows=3,
            )

            self.assertEqual(len(selected), 2)
            self.assertEqual(int(selected[0]["chunk_index"]), 0)
            self.assertEqual(int(selected[1]["chunk_index"]), 3)

    def test_search_can_use_directory_path_signal_as_tiebreaker(self):
        with TemporaryDirectory() as tmp_dir:
            index_path = Path(tmp_dir) / "memory_index.pkl"
            idx = self.MemoryIndex(sandbox=None, workspace_path="/workspace", index_path=str(index_path))
            idx.DEFAULT_CHUNK_SIZE = 80
            idx.DEFAULT_CHUNK_OVERLAP = 0

            shared_content = "\n".join(
                [
                    "AlphaBridgeUnique appears in the implementation notes",
                    "ordinary filler ending",
                ]
            )

            idx._replace_file_documents("/workspace/app/cli/notes.txt", shared_content, 1.0, len(shared_content))
            idx._replace_file_documents("/workspace/docs/misc/notes.txt", shared_content, 1.0, len(shared_content))
            idx._sync_file_to_fts("/workspace/app/cli/notes.txt")
            idx._sync_file_to_fts("/workspace/docs/misc/notes.txt")
            idx._save_index()

            results = idx.search("cli AlphaBridgeUnique", top_k=2)

            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].path, "/workspace/app/cli/notes.txt")
            self.assertEqual(results[1].path, "/workspace/docs/misc/notes.txt")

    def test_search_can_match_identifier_parts_from_snake_and_camel_case_tokens(self):
        with TemporaryDirectory() as tmp_dir:
            index_path = Path(tmp_dir) / "memory_index.pkl"
            idx = self.MemoryIndex(sandbox=None, workspace_path="/workspace", index_path=str(index_path))
            idx.DEFAULT_CHUNK_SIZE = 80
            idx.DEFAULT_CHUNK_OVERLAP = 0

            code_content = "\n".join(
                [
                    "def search_memory(query):",
                    "    user_id = 'alice'",
                    "    SessionMemoryGamma = user_id",
                ]
            )

            idx._replace_file_documents("/workspace/app/cli/memory_search.py", code_content, 1.0, len(code_content))
            idx._sync_file_to_fts("/workspace/app/cli/memory_search.py")
            idx._save_index()

            snake_results = idx.search("search memory user id", top_k=1)
            self.assertEqual(len(snake_results), 1)
            self.assertEqual(snake_results[0].path, "/workspace/app/cli/memory_search.py")

            camel_results = idx.search("session memory gamma", top_k=1)
            self.assertEqual(len(camel_results), 1)
            self.assertEqual(camel_results[0].path, "/workspace/app/cli/memory_search.py")

    def test_search_can_find_files_by_directory_terms_even_without_content_match(self):
        with TemporaryDirectory() as tmp_dir:
            index_path = Path(tmp_dir) / "memory_index.pkl"
            idx = self.MemoryIndex(sandbox=None, workspace_path="/workspace", index_path=str(index_path))
            idx.DEFAULT_CHUNK_SIZE = 80
            idx.DEFAULT_CHUNK_OVERLAP = 0

            content = "ordinary implementation notes with no directory keywords"
            idx._replace_file_documents("/workspace/app/cli/notes.txt", content, 1.0, len(content))
            idx._replace_file_documents("/workspace/docs/misc/notes.txt", content, 1.0, len(content))
            idx._sync_file_to_fts("/workspace/app/cli/notes.txt")
            idx._sync_file_to_fts("/workspace/docs/misc/notes.txt")
            idx._save_index()

            results = idx.search("app cli", top_k=2)

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].path, "/workspace/app/cli/notes.txt")

    def test_realistic_query_prefers_cli_provider_implementation(self):
        with TemporaryDirectory() as tmp_dir:
            index_path = Path(tmp_dir) / "memory_index.pkl"
            idx = self.MemoryIndex(sandbox=None, workspace_path="/workspace", index_path=str(index_path))
            idx.DEFAULT_CHUNK_SIZE = 90
            idx.DEFAULT_CHUNK_OVERLAP = 0

            cli_provider_content = "\n".join(
                [
                    "def provider_list():",
                    "    return ['default']",
                    "def provider_create(base_url, api_key, model):",
                    "    verify_provider_connectivity(base_url, api_key, model)",
                ]
            )
            service_provider_content = "\n".join(
                [
                    "class LLMProviderService:",
                    "    def verify_provider(self, base_url, api_key, model):",
                    "        raise NotImplementedError",
                ]
            )
            docs_provider_content = "\n".join(
                [
                    "# CLI Guide",
                    "Use sage provider list to inspect providers.",
                    "Use sage provider create to add one.",
                ]
            )

            idx._replace_file_documents("/workspace/app/cli/provider_commands.py", cli_provider_content, 1.0, len(cli_provider_content))
            idx._replace_file_documents("/workspace/common/services/llm_provider_service.py", service_provider_content, 1.0, len(service_provider_content))
            idx._replace_file_documents("/workspace/docs/CLI.md", docs_provider_content, 1.0, len(docs_provider_content))
            idx._sync_file_to_fts("/workspace/app/cli/provider_commands.py")
            idx._sync_file_to_fts("/workspace/common/services/llm_provider_service.py")
            idx._sync_file_to_fts("/workspace/docs/CLI.md")
            idx._save_index()

            results = idx.search("provider cli", top_k=3)

            self.assertEqual(len(results), 3)
            self.assertEqual(results[0].path, "/workspace/app/cli/provider_commands.py")

    def test_realistic_query_prefers_memory_search_implementation_over_generic_notes(self):
        with TemporaryDirectory() as tmp_dir:
            index_path = Path(tmp_dir) / "memory_index.pkl"
            idx = self.MemoryIndex(sandbox=None, workspace_path="/workspace", index_path=str(index_path))
            idx.DEFAULT_CHUNK_SIZE = 90
            idx.DEFAULT_CHUNK_OVERLAP = 0

            impl_content = "\n".join(
                [
                    "class MemoryIndex:",
                    "    def search(self, query, top_k=5):",
                    "        return self._fetch_candidate_file_rows(query_tokens, top_k)",
                    "    def _score_file_candidate(self, path, file_score, rows, query, query_tokens):",
                    "        return file_score",
                ]
            )
            notes_content = "\n".join(
                [
                    "# memory notes",
                    "memory retrieval should be faster",
                    "search quality is important for memory",
                    "memory search should feel stable",
                ]
            )

            idx._replace_file_documents("/workspace/sagents/tool/impl/memory_index.py", impl_content, 1.0, len(impl_content))
            idx._replace_file_documents("/workspace/docs/memory_notes.md", notes_content, 1.0, len(notes_content))
            idx._sync_file_to_fts("/workspace/sagents/tool/impl/memory_index.py")
            idx._sync_file_to_fts("/workspace/docs/memory_notes.md")
            idx._save_index()

            results = idx.search("memory search", top_k=2)

            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].path, "/workspace/sagents/tool/impl/memory_index.py")

    def test_realistic_query_prefers_session_user_id_implementation(self):
        with TemporaryDirectory() as tmp_dir:
            index_path = Path(tmp_dir) / "memory_index.pkl"
            idx = self.MemoryIndex(sandbox=None, workspace_path="/workspace", index_path=str(index_path))
            idx.DEFAULT_CHUNK_SIZE = 90
            idx.DEFAULT_CHUNK_OVERLAP = 0

            impl_content = "\n".join(
                [
                    "def resume_session(session_id, user_id):",
                    "    return {'session_id': session_id, 'user_id': user_id}",
                    "def list_sessions(user_id):",
                    "    return []",
                ]
            )
            docs_content = "\n".join(
                [
                    "# Sessions",
                    "A session can be resumed later.",
                    "Users may want to inspect sessions.",
                    "The guide explains resume behavior.",
                ]
            )

            idx._replace_file_documents("/workspace/app/cli/session_store.py", impl_content, 1.0, len(impl_content))
            idx._replace_file_documents("/workspace/docs/sessions.md", docs_content, 1.0, len(docs_content))
            idx._sync_file_to_fts("/workspace/app/cli/session_store.py")
            idx._sync_file_to_fts("/workspace/docs/sessions.md")
            idx._save_index()

            results = idx.search("session user id", top_k=2)

            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].path, "/workspace/app/cli/session_store.py")

    def test_realistic_query_prefers_provider_verify_model_implementation(self):
        with TemporaryDirectory() as tmp_dir:
            index_path = Path(tmp_dir) / "memory_index.pkl"
            idx = self.MemoryIndex(sandbox=None, workspace_path="/workspace", index_path=str(index_path))
            idx.DEFAULT_CHUNK_SIZE = 90
            idx.DEFAULT_CHUNK_OVERLAP = 0

            impl_content = "\n".join(
                [
                    "def verify_provider(base_url, api_key, model):",
                    "    if not model:",
                    "        raise ValueError('model required')",
                    "    return probe_model_connectivity(base_url, api_key, model)",
                ]
            )
            docs_content = "\n".join(
                [
                    "# Provider verification",
                    "Run provider verify before saving configuration.",
                    "Make sure the model is available.",
                ]
            )

            idx._replace_file_documents("/workspace/app/cli/provider_verify.py", impl_content, 1.0, len(impl_content))
            idx._replace_file_documents("/workspace/docs/provider_verify.md", docs_content, 1.0, len(docs_content))
            idx._sync_file_to_fts("/workspace/app/cli/provider_verify.py")
            idx._sync_file_to_fts("/workspace/docs/provider_verify.md")
            idx._save_index()

            results = idx.search("provider verify model", top_k=2)

            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].path, "/workspace/app/cli/provider_verify.py")

    def test_realistic_query_prefers_memory_index_search_implementation(self):
        with TemporaryDirectory() as tmp_dir:
            index_path = Path(tmp_dir) / "memory_index.pkl"
            idx = self.MemoryIndex(sandbox=None, workspace_path="/workspace", index_path=str(index_path))
            idx.DEFAULT_CHUNK_SIZE = 90
            idx.DEFAULT_CHUNK_OVERLAP = 0

            impl_content = "\n".join(
                [
                    "class MemoryIndex:",
                    "    def search(self, query, top_k=5):",
                    "        match_expr = self._build_match_expr(self._tokenize(query), operator='OR')",
                    "        return self._fetch_candidate_file_rows(None, [], top_k)",
                ]
            )
            generic_content = "\n".join(
                [
                    "# Search overview",
                    "The memory feature uses indexing.",
                    "Users can search project notes quickly.",
                ]
            )

            idx._replace_file_documents("/workspace/sagents/tool/impl/memory_index.py", impl_content, 1.0, len(impl_content))
            idx._replace_file_documents("/workspace/docs/search_overview.md", generic_content, 1.0, len(generic_content))
            idx._sync_file_to_fts("/workspace/sagents/tool/impl/memory_index.py")
            idx._sync_file_to_fts("/workspace/docs/search_overview.md")
            idx._save_index()

            results = idx.search("memory index search", top_k=2)

            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].path, "/workspace/sagents/tool/impl/memory_index.py")

    def test_realistic_query_prefers_resume_session_user_implementation(self):
        with TemporaryDirectory() as tmp_dir:
            index_path = Path(tmp_dir) / "memory_index.pkl"
            idx = self.MemoryIndex(sandbox=None, workspace_path="/workspace", index_path=str(index_path))
            idx.DEFAULT_CHUNK_SIZE = 90
            idx.DEFAULT_CHUNK_OVERLAP = 0

            impl_content = "\n".join(
                [
                    "def resume_session(session_id, user_id):",
                    "    return load_session_for_user(session_id, user_id)",
                    "def load_session_for_user(session_id, user_id):",
                    "    return {'session_id': session_id, 'user_id': user_id}",
                ]
            )
            docs_content = "\n".join(
                [
                    "# Resume guide",
                    "A user can resume a previous session from the CLI.",
                    "The guide explains how session history is loaded.",
                ]
            )

            idx._replace_file_documents("/workspace/app/cli/resume_session.py", impl_content, 1.0, len(impl_content))
            idx._replace_file_documents("/workspace/docs/resume_guide.md", docs_content, 1.0, len(docs_content))
            idx._sync_file_to_fts("/workspace/app/cli/resume_session.py")
            idx._sync_file_to_fts("/workspace/docs/resume_guide.md")
            idx._save_index()

            results = idx.search("resume session user", top_k=2)

            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].path, "/workspace/app/cli/resume_session.py")

    def test_realistic_query_prefers_cli_chat_session_implementation(self):
        with TemporaryDirectory() as tmp_dir:
            index_path = Path(tmp_dir) / "memory_index.pkl"
            idx = self.MemoryIndex(sandbox=None, workspace_path="/workspace", index_path=str(index_path))
            idx.DEFAULT_CHUNK_SIZE = 90
            idx.DEFAULT_CHUNK_OVERLAP = 0

            impl_content = "\n".join(
                [
                    "class ChatSessionRunner:",
                    "    def run_chat_session(self, session_id):",
                    "        return stream_chat_events(session_id)",
                    "def stream_chat_events(session_id):",
                    "    return []",
                ]
            )
            docs_content = "\n".join(
                [
                    "# CLI chat",
                    "The CLI supports interactive chat mode.",
                    "A session can be resumed from history.",
                ]
            )

            idx._replace_file_documents("/workspace/app/cli/chat_session_runner.py", impl_content, 1.0, len(impl_content))
            idx._replace_file_documents("/workspace/docs/cli_chat.md", docs_content, 1.0, len(docs_content))
            idx._sync_file_to_fts("/workspace/app/cli/chat_session_runner.py")
            idx._sync_file_to_fts("/workspace/docs/cli_chat.md")
            idx._save_index()

            results = idx.search("cli chat session", top_k=2)

            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].path, "/workspace/app/cli/chat_session_runner.py")

    def test_mixed_language_query_prefers_resume_session_user_implementation(self):
        with TemporaryDirectory() as tmp_dir:
            index_path = Path(tmp_dir) / "memory_index.pkl"
            idx = self.MemoryIndex(sandbox=None, workspace_path="/workspace", index_path=str(index_path))
            idx.DEFAULT_CHUNK_SIZE = 90
            idx.DEFAULT_CHUNK_OVERLAP = 0

            impl_content = "\n".join(
                [
                    "# 恢复用户 session",
                    "def resume_session(session_id, user_id):",
                    "    return load_session_for_user(session_id, user_id)",
                    "def load_session_for_user(session_id, user_id):",
                    "    return {'session_id': session_id, 'user_id': user_id}",
                ]
            )
            docs_content = "\n".join(
                [
                    "# 恢复指南",
                    "用户可以从 CLI 恢复之前的 session。",
                    "文档说明如何继续历史会话。",
                ]
            )

            idx._replace_file_documents("/workspace/app/cli/resume_session.py", impl_content, 1.0, len(impl_content))
            idx._replace_file_documents("/workspace/docs/resume_guide.md", docs_content, 1.0, len(docs_content))
            idx._sync_file_to_fts("/workspace/app/cli/resume_session.py")
            idx._sync_file_to_fts("/workspace/docs/resume_guide.md")
            idx._save_index()

            results = idx.search("恢复 用户 session user id", top_k=2)

            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].path, "/workspace/app/cli/resume_session.py")

    def test_mixed_language_query_prefers_provider_verify_implementation(self):
        with TemporaryDirectory() as tmp_dir:
            index_path = Path(tmp_dir) / "memory_index.pkl"
            idx = self.MemoryIndex(sandbox=None, workspace_path="/workspace", index_path=str(index_path))
            idx.DEFAULT_CHUNK_SIZE = 90
            idx.DEFAULT_CHUNK_OVERLAP = 0

            impl_content = "\n".join(
                [
                    "# 验证 provider model",
                    "def verify_provider(base_url, api_key, model):",
                    "    return probe_model_connectivity(base_url, api_key, model)",
                ]
            )
            docs_content = "\n".join(
                [
                    "# Provider 验证指南",
                    "运行 provider verify 可以检查配置。",
                    "文档也会提到 model 可用性。",
                ]
            )

            idx._replace_file_documents("/workspace/app/cli/provider_verify.py", impl_content, 1.0, len(impl_content))
            idx._replace_file_documents("/workspace/docs/provider_verify.md", docs_content, 1.0, len(docs_content))
            idx._sync_file_to_fts("/workspace/app/cli/provider_verify.py")
            idx._sync_file_to_fts("/workspace/docs/provider_verify.md")
            idx._save_index()

            results = idx.search("provider 验证 model", top_k=2)

            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].path, "/workspace/app/cli/provider_verify.py")

    def test_mixed_language_query_prefers_memory_search_identifier_implementation(self):
        with TemporaryDirectory() as tmp_dir:
            index_path = Path(tmp_dir) / "memory_index.pkl"
            idx = self.MemoryIndex(sandbox=None, workspace_path="/workspace", index_path=str(index_path))
            idx.DEFAULT_CHUNK_SIZE = 90
            idx.DEFAULT_CHUNK_OVERLAP = 0

            impl_content = "\n".join(
                [
                    "# 记忆 search helper",
                    "def search_memory(user_id, query):",
                    "    return {'user_id': user_id, 'query': query}",
                ]
            )
            docs_content = "\n".join(
                [
                    "# memory 文档",
                    "搜索记忆功能很重要。",
                    "这个指南解释 search 行为。",
                ]
            )

            idx._replace_file_documents("/workspace/app/cli/memory_search.py", impl_content, 1.0, len(impl_content))
            idx._replace_file_documents("/workspace/docs/memory_search.md", docs_content, 1.0, len(docs_content))
            idx._sync_file_to_fts("/workspace/app/cli/memory_search.py")
            idx._sync_file_to_fts("/workspace/docs/memory_search.md")
            idx._save_index()

            results = idx.search("记忆 search user id", top_k=2)

            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].path, "/workspace/app/cli/memory_search.py")

    def test_search_latency_stays_reasonable_on_moderate_synthetic_corpus(self):
        with TemporaryDirectory() as tmp_dir:
            index_path = Path(tmp_dir) / "memory_index.pkl"
            idx = self.MemoryIndex(sandbox=None, workspace_path="/workspace", index_path=str(index_path))
            idx.DEFAULT_CHUNK_SIZE = 120
            idx.DEFAULT_CHUNK_OVERLAP = 0

            for i in range(250):
                noisy_content = "\n".join(
                    [
                        f"ordinary filler line {i}",
                        "generic implementation detail",
                        "another unrelated search note",
                    ]
                )
                path = f"/workspace/noise/file_{i}.txt"
                idx._replace_file_documents(path, noisy_content, 1.0, len(noisy_content))
                idx._sync_file_to_fts(path)

            target_content = "\n".join(
                [
                    "def resume_session(session_id, user_id):",
                    "    return load_session_for_user(session_id, user_id)",
                    "def load_session_for_user(session_id, user_id):",
                    "    return {'session_id': session_id, 'user_id': user_id}",
                ]
            )
            idx._replace_file_documents("/workspace/app/cli/resume_session.py", target_content, 1.0, len(target_content))
            idx._sync_file_to_fts("/workspace/app/cli/resume_session.py")
            idx._save_index()

            search_start = time.perf_counter()
            results = idx.search("resume session user", top_k=3)
            elapsed = time.perf_counter() - search_start

            self.assertGreaterEqual(len(results), 1)
            self.assertEqual(results[0].path, "/workspace/app/cli/resume_session.py")
            self.assertLess(elapsed, 2.0)

    def test_realistic_query_prefers_doctor_config_cli_implementation(self):
        with TemporaryDirectory() as tmp_dir:
            index_path = Path(tmp_dir) / "memory_index.pkl"
            idx = self.MemoryIndex(sandbox=None, workspace_path="/workspace", index_path=str(index_path))
            idx.DEFAULT_CHUNK_SIZE = 90
            idx.DEFAULT_CHUNK_OVERLAP = 0

            impl_content = "\n".join(
                [
                    "def doctor_command(show_config=False):",
                    "    if show_config:",
                    "        return load_cli_config()",
                    "def load_cli_config():",
                    "    return {'app_mode': 'server'}",
                ]
            )
            docs_content = "\n".join(
                [
                    "# Doctor guide",
                    "The CLI has a doctor command.",
                    "The config can also be shown in the guide.",
                ]
            )

            idx._replace_file_documents("/workspace/app/cli/doctor_config.py", impl_content, 1.0, len(impl_content))
            idx._replace_file_documents("/workspace/docs/doctor.md", docs_content, 1.0, len(docs_content))
            idx._sync_file_to_fts("/workspace/app/cli/doctor_config.py")
            idx._sync_file_to_fts("/workspace/docs/doctor.md")
            idx._save_index()

            results = idx.search("doctor config cli", top_k=2)

            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].path, "/workspace/app/cli/doctor_config.py")

    def test_realistic_query_prefers_sessions_inspect_latest_implementation(self):
        with TemporaryDirectory() as tmp_dir:
            index_path = Path(tmp_dir) / "memory_index.pkl"
            idx = self.MemoryIndex(sandbox=None, workspace_path="/workspace", index_path=str(index_path))
            idx.DEFAULT_CHUNK_SIZE = 90
            idx.DEFAULT_CHUNK_OVERLAP = 0

            impl_content = "\n".join(
                [
                    "def inspect_latest_session(user_id):",
                    "    return inspect_session('latest', user_id)",
                    "def inspect_session(session_id, user_id):",
                    "    return {'session_id': session_id, 'user_id': user_id}",
                ]
            )
            docs_content = "\n".join(
                [
                    "# Sessions inspect",
                    "The guide explains how to inspect a session.",
                    "Users can choose the latest entry from history.",
                ]
            )

            idx._replace_file_documents("/workspace/app/cli/sessions_inspect.py", impl_content, 1.0, len(impl_content))
            idx._replace_file_documents("/workspace/docs/sessions_inspect.md", docs_content, 1.0, len(docs_content))
            idx._sync_file_to_fts("/workspace/app/cli/sessions_inspect.py")
            idx._sync_file_to_fts("/workspace/docs/sessions_inspect.md")
            idx._save_index()

            results = idx.search("sessions inspect latest", top_k=2)

            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].path, "/workspace/app/cli/sessions_inspect.py")

    def test_realistic_query_prefers_memory_report_scheduler_implementation(self):
        with TemporaryDirectory() as tmp_dir:
            index_path = Path(tmp_dir) / "memory_index.pkl"
            idx = self.MemoryIndex(sandbox=None, workspace_path="/workspace", index_path=str(index_path))
            idx.DEFAULT_CHUNK_SIZE = 90
            idx.DEFAULT_CHUNK_OVERLAP = 0

            impl_content = "\n".join(
                [
                    "def initialize_task_scheduler(memory_report_enabled=True):",
                    "    if memory_report_enabled:",
                    "        return build_memory_report_scheduler()",
                    "def build_memory_report_scheduler():",
                    "    return {}",
                ]
            )
            docs_content = "\n".join(
                [
                    "# Runtime notes",
                    "Task scheduling is initialized during startup.",
                    "A memory report may be enabled in configuration.",
                ]
            )

            idx._replace_file_documents("/workspace/app/server/task_scheduler.py", impl_content, 1.0, len(impl_content))
            idx._replace_file_documents("/workspace/docs/runtime_notes.md", docs_content, 1.0, len(docs_content))
            idx._sync_file_to_fts("/workspace/app/server/task_scheduler.py")
            idx._sync_file_to_fts("/workspace/docs/runtime_notes.md")
            idx._save_index()

            results = idx.search("memory report scheduler", top_k=2)

            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].path, "/workspace/app/server/task_scheduler.py")

    def test_mixed_language_query_prefers_doctor_config_implementation(self):
        with TemporaryDirectory() as tmp_dir:
            index_path = Path(tmp_dir) / "memory_index.pkl"
            idx = self.MemoryIndex(sandbox=None, workspace_path="/workspace", index_path=str(index_path))
            idx.DEFAULT_CHUNK_SIZE = 90
            idx.DEFAULT_CHUNK_OVERLAP = 0

            impl_content = "\n".join(
                [
                    "# CLI doctor 配置",
                    "def doctor_command(show_config=False):",
                    "    return load_cli_config() if show_config else {}",
                    "def load_cli_config():",
                    "    return {'env_file': '.env'}",
                ]
            )
            docs_content = "\n".join(
                [
                    "# doctor 文档",
                    "这里说明 doctor 命令的用途。",
                    "配置显示方式也会在这里解释。",
                ]
            )

            idx._replace_file_documents("/workspace/app/cli/doctor_config.py", impl_content, 1.0, len(impl_content))
            idx._replace_file_documents("/workspace/docs/doctor.md", docs_content, 1.0, len(docs_content))
            idx._sync_file_to_fts("/workspace/app/cli/doctor_config.py")
            idx._sync_file_to_fts("/workspace/docs/doctor.md")
            idx._save_index()

            results = idx.search("doctor 配置 cli", top_k=2)

            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].path, "/workspace/app/cli/doctor_config.py")

    def test_index_build_and_batch_search_latency_stay_reasonable(self):
        with TemporaryDirectory() as tmp_dir:
            index_path = Path(tmp_dir) / "memory_index.pkl"
            idx = self.MemoryIndex(sandbox=None, workspace_path="/workspace", index_path=str(index_path))
            idx.DEFAULT_CHUNK_SIZE = 120
            idx.DEFAULT_CHUNK_OVERLAP = 0

            build_start = time.perf_counter()
            for i in range(300):
                noisy_content = "\n".join(
                    [
                        f"generic filler note {i}",
                        "ordinary search context",
                        "miscellaneous runtime implementation detail",
                    ]
                )
                path = f"/workspace/noise/batch_{i}.txt"
                idx._replace_file_documents(path, noisy_content, 1.0, len(noisy_content))
                idx._sync_file_to_fts(path)

            target_files = {
                "/workspace/app/cli/resume_session.py": "\n".join(
                    [
                        "def resume_session(session_id, user_id):",
                        "    return load_session_for_user(session_id, user_id)",
                        "def load_session_for_user(session_id, user_id):",
                        "    return {'session_id': session_id, 'user_id': user_id}",
                    ]
                ),
                "/workspace/app/cli/doctor_config.py": "\n".join(
                    [
                        "def doctor_command(show_config=False):",
                        "    return load_cli_config() if show_config else {}",
                        "def load_cli_config():",
                        "    return {'env_file': '.env'}",
                    ]
                ),
                "/workspace/app/cli/provider_verify.py": "\n".join(
                    [
                        "def verify_provider(base_url, api_key, model):",
                        "    return probe_model_connectivity(base_url, api_key, model)",
                    ]
                ),
                "/workspace/sagents/tool/impl/memory_index.py": "\n".join(
                    [
                        "class MemoryIndex:",
                        "    def search(self, query, top_k=5):",
                        "        return self._fetch_candidate_file_rows(None, [], top_k)",
                    ]
                ),
                "/workspace/app/cli/sessions_inspect.py": "\n".join(
                    [
                        "def inspect_latest_session(user_id):",
                        "    return inspect_session('latest', user_id)",
                        "def inspect_session(session_id, user_id):",
                        "    return {'session_id': session_id, 'user_id': user_id}",
                    ]
                ),
            }
            for path, content in target_files.items():
                idx._replace_file_documents(path, content, 1.0, len(content))
                idx._sync_file_to_fts(path)
            idx._save_index()
            build_elapsed = time.perf_counter() - build_start

            query_start = time.perf_counter()
            queries = [
                "resume session user",
                "doctor config cli",
                "provider verify model",
                "memory index search",
                "sessions inspect latest",
            ]
            for query in queries:
                results = idx.search(query, top_k=3)
                self.assertGreaterEqual(len(results), 1)
            query_elapsed = time.perf_counter() - query_start

            self.assertLess(build_elapsed, 4.0)
            self.assertLess(query_elapsed, 2.5)


if __name__ == "__main__":
    unittest.main()

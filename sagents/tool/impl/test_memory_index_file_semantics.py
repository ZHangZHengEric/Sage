#!/usr/bin/env python3
import importlib.util
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_memory_index_module():
    module_path = Path(__file__).resolve().with_name("memory_index.py")
    spec = importlib.util.spec_from_file_location("memory_index_under_test_file_semantics", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestMemoryIndexFileSemantics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_memory_index_module()
        cls.MemoryIndex = cls.module.MemoryIndex

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


if __name__ == "__main__":
    unittest.main()

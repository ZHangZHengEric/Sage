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
    spec = importlib.util.spec_from_file_location("memory_index_under_test_ranking", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestMemoryIndexRanking(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_memory_index_module()
        cls.MemoryIndex = cls.module.MemoryIndex

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


if __name__ == "__main__":
    unittest.main()

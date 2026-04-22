#!/usr/bin/env python3
import argparse
import importlib.util
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_memory_index_module():
    module_path = REPO_ROOT / "sagents" / "tool" / "impl" / "memory_index.py"
    spec = importlib.util.spec_from_file_location("memory_index_benchmark", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _build_target_files():
    return {
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
        "/workspace/app/server/task_scheduler.py": "\n".join(
            [
                "def initialize_task_scheduler(memory_report_enabled=True):",
                "    if memory_report_enabled:",
                "        return build_memory_report_scheduler()",
                "def build_memory_report_scheduler():",
                "    return {}",
            ]
        ),
    }


def _build_queries():
    return [
        "resume session user",
        "doctor config cli",
        "provider verify model",
        "memory index search",
        "sessions inspect latest",
        "memory report scheduler",
        "恢复 用户 session user id",
        "provider 验证 model",
    ]


def run_benchmark(noise_files: int, chunk_size: int, chunk_overlap: int, top_k: int) -> int:
    module = _load_memory_index_module()
    MemoryIndex = module.MemoryIndex

    with TemporaryDirectory() as tmp_dir:
        index_path = Path(tmp_dir) / "memory_index.pkl"
        idx = MemoryIndex(sandbox=None, workspace_path="/workspace", index_path=str(index_path))
        idx.DEFAULT_CHUNK_SIZE = chunk_size
        idx.DEFAULT_CHUNK_OVERLAP = chunk_overlap

        build_start = time.perf_counter()
        for i in range(noise_files):
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

        for path, content in _build_target_files().items():
            idx._replace_file_documents(path, content, 1.0, len(content))
            idx._sync_file_to_fts(path)
        idx._save_index()
        build_elapsed = time.perf_counter() - build_start

        print(f"build_seconds={build_elapsed:.4f}")
        print(f"noise_files={noise_files}")
        print(f"indexed_documents={idx.get_document_count()}")

        query_timings = []
        for query in _build_queries():
            search_start = time.perf_counter()
            results = idx.search(query, top_k=top_k)
            elapsed = time.perf_counter() - search_start
            query_timings.append(elapsed)
            top_path = results[0].path if results else "NOT_FOUND"
            top_score = f"{results[0].score:.4f}" if results else "n/a"
            print(f"query={query}")
            print(f"  search_seconds={elapsed:.4f}")
            print(f"  top_path={top_path}")
            print(f"  top_score={top_score}")

        if query_timings:
            total_query_seconds = sum(query_timings)
            avg_query_seconds = total_query_seconds / len(query_timings)
            print(f"total_query_seconds={total_query_seconds:.4f}")
            print(f"avg_query_seconds={avg_query_seconds:.4f}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a synthetic benchmark for memory search quality and latency.")
    parser.add_argument("--noise-files", type=int, default=300, help="Number of unrelated synthetic files to index.")
    parser.add_argument("--chunk-size", type=int, default=120, help="Chunk size for the benchmark index.")
    parser.add_argument("--chunk-overlap", type=int, default=0, help="Chunk overlap for the benchmark index.")
    parser.add_argument("--top-k", type=int, default=3, help="Top K results to fetch per query.")
    args = parser.parse_args()
    return run_benchmark(args.noise_files, args.chunk_size, args.chunk_overlap, args.top_k)


if __name__ == "__main__":
    raise SystemExit(main())

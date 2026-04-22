#!/usr/bin/env python3
import contextlib
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


import app.cli.service as cli_service


class _StubConfig:
    app_mode = "server"
    auth_mode = "native"
    port = 8080
    db_type = "file"
    default_llm_api_base_url = "https://example.com/v1"
    default_llm_model_name = "example-model"
    agents_dir = "/tmp/agents"
    session_dir = "/tmp/sessions"
    logs_dir = "/tmp/logs"


class TestDoctorMemoryBackends(unittest.TestCase):
    @contextlib.contextmanager
    def _patched_runtime(self):
        with contextlib.ExitStack() as stack:
            stack.enter_context(
                patch.object(cli_service, "init_cli_config", return_value=_StubConfig())
            )
            stack.enter_context(
                patch.object(
                    cli_service.config,
                    "get_local_storage_defaults",
                    return_value={"env_file": "/tmp/.sage_env", "sage_home": "/tmp/.sage"},
                )
            )
            stack.enter_context(
                patch.object(
                    cli_service,
                    "_dependency_status",
                    return_value={"dotenv": True},
                )
            )
            stack.enter_context(
                patch.object(
                    cli_service,
                    "_collect_runtime_issues",
                    return_value={"errors": [], "warnings": [], "next_steps": []},
                )
            )
            stack.enter_context(
                patch.object(cli_service, "get_default_cli_user_id", return_value="default_user")
            )
            stack.enter_context(
                patch.object(cli_service, "get_default_cli_max_loop_count", return_value=50)
            )
            stack.enter_context(patch("os.path.exists", return_value=True))
            stack.enter_context(
                patch.dict(
                    "os.environ",
                    {
                        "SAGE_SESSION_MEMORY_BACKEND": "noop",
                        "SAGE_SESSION_MEMORY_STRATEGY": "grouped_chat",
                        "SAGE_FILE_MEMORY_BACKEND": "scoped_index",
                    },
                    clear=False,
                )
            )
            yield

    def test_collect_doctor_info_includes_memory_backend_diagnostics(self):
        with self._patched_runtime():
            info = cli_service.collect_doctor_info()

        self.assertIn("memory_backends", info)
        self.assertEqual(info["memory_backends"]["session_history"]["status"], "ok")
        self.assertEqual(info["memory_backends"]["file_memory"]["status"], "ok")
        self.assertEqual(info["memory_backends"]["session_history"]["resolved"], "noop")
        self.assertEqual(info["memory_backends"]["file_memory"]["resolved"], "scoped_index")
        self.assertIn("bm25", info["memory_backends"]["session_history"]["available"])
        self.assertIn("noop", info["memory_backends"]["session_history"]["available"])
        self.assertIn("scoped_index", info["memory_backends"]["file_memory"]["available"])
        self.assertIn("noop", info["memory_backends"]["file_memory"]["available"])
        self.assertIn("memory_strategies", info)
        self.assertEqual(info["memory_strategies"]["session_history"]["status"], "ok")
        self.assertEqual(
            info["memory_strategies"]["session_history"]["resolved"],
            "grouped_chat",
        )
        self.assertIn(
            "messages",
            info["memory_strategies"]["session_history"]["available"],
        )
        self.assertIn(
            "grouped_chat",
            info["memory_strategies"]["session_history"]["available"],
        )
        self.assertEqual(
            info["memory_strategies"]["session_history"]["env"],
            "grouped_chat",
        )

    def test_collect_config_info_includes_memory_backend_diagnostics(self):
        with self._patched_runtime():
            info = cli_service.collect_config_info()

        self.assertIn("memory_backends", info)
        self.assertEqual(info["memory_backends"]["session_history"]["status"], "ok")
        self.assertEqual(info["memory_backends"]["file_memory"]["status"], "ok")
        self.assertEqual(info["memory_backends"]["session_history"]["resolved"], "noop")
        self.assertEqual(info["memory_backends"]["file_memory"]["resolved"], "scoped_index")
        self.assertIn("memory_strategies", info)
        self.assertEqual(info["memory_strategies"]["session_history"]["status"], "ok")
        self.assertEqual(
            info["memory_strategies"]["session_history"]["resolved"],
            "grouped_chat",
        )
        self.assertEqual(
            info["memory_strategies"]["session_history"]["env"],
            "grouped_chat",
        )
        self.assertEqual(info["env_sources"]["SAGE_SESSION_MEMORY_BACKEND"], "noop")
        self.assertEqual(info["env_sources"]["SAGE_FILE_MEMORY_BACKEND"], "scoped_index")
        self.assertEqual(info["env_sources"]["SAGE_SESSION_MEMORY_STRATEGY"], "grouped_chat")

    def test_collect_doctor_info_surfaces_invalid_memory_configuration(self):
        with self._patched_runtime():
            with patch.dict(
                "os.environ",
                {
                    "SAGE_SESSION_MEMORY_BACKEND": "broken_backend",
                    "SAGE_SESSION_MEMORY_STRATEGY": "broken_strategy",
                },
                clear=False,
            ):
                info = cli_service.collect_doctor_info()

        self.assertEqual(info["status"], "error")
        self.assertEqual(info["memory_backends"]["session_history"]["status"], "error")
        self.assertIsNone(info["memory_backends"]["session_history"]["resolved"])
        self.assertIn(
            "Unsupported session memory backend",
            info["memory_backends"]["session_history"]["error"],
        )
        self.assertEqual(info["memory_strategies"]["session_history"]["status"], "error")
        self.assertIsNone(info["memory_strategies"]["session_history"]["resolved"])
        self.assertIn(
            "Unsupported session memory strategy",
            info["memory_strategies"]["session_history"]["error"],
        )
        self.assertTrue(
            any("Invalid memory_backends.session_history" in item for item in info["errors"])
        )
        self.assertTrue(
            any("Invalid memory_strategies.session_history" in item for item in info["errors"])
        )

    def test_collect_config_info_surfaces_invalid_memory_configuration(self):
        with self._patched_runtime():
            with patch.dict(
                "os.environ",
                {
                    "SAGE_FILE_MEMORY_BACKEND": "broken_file_backend",
                },
                clear=False,
            ):
                info = cli_service.collect_config_info()

        self.assertEqual(info["memory_backends"]["file_memory"]["status"], "error")
        self.assertIsNone(info["memory_backends"]["file_memory"]["resolved"])
        self.assertIn(
            "Unsupported file memory backend",
            info["memory_backends"]["file_memory"]["error"],
        )

    def test_build_minimal_cli_env_template_includes_memory_overrides(self):
        with self._patched_runtime():
            template = cli_service.build_minimal_cli_env_template()

        self.assertIn("# Optional memory-search overrides", template)
        self.assertIn("# SAGE_SESSION_MEMORY_BACKEND=bm25", template)
        self.assertIn("# SAGE_FILE_MEMORY_BACKEND=scoped_index", template)
        self.assertIn("# SAGE_SESSION_MEMORY_STRATEGY=messages", template)


if __name__ == "__main__":
    unittest.main()

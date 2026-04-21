#!/usr/bin/env python3
import importlib
import importlib.util
import io
import json
import os
import sys
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli.main import main


def _integration_deps_available() -> bool:
    required = ["sqlalchemy", "aiosqlite", "loguru"]
    return all(importlib.util.find_spec(name) is not None for name in required)


@unittest.skipUnless(
    _integration_deps_available(),
    "provider CLI integration test requires sqlalchemy, aiosqlite, and loguru",
)
class TestProviderCliIntegration(unittest.TestCase):
    def _run_cli(self, argv):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = main(argv)
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def _run_cli_json_ok(self, argv):
        exit_code, stdout, stderr = self._run_cli(argv)
        self.assertEqual(exit_code, 0, msg=f"stdout={stdout}\nstderr={stderr}")
        self.assertTrue(stdout.strip(), msg=f"stderr={stderr}")
        return json.loads(stdout), stderr

    def test_provider_lifecycle_against_temp_file_db(self):
        async def fake_probe(api_key, base_url, model):
            return {
                "supported": True,
                "response": f"ok:{model}@{base_url}",
            }

        class _StubLogger:
            def bind(self, **_kwargs):
                return self

            def __getattr__(self, _name):
                return lambda *args, **kwargs: None

        with TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            fake_home = tmp_root / "home"
            fake_home.mkdir()
            fake_workdir = tmp_root / "workdir"
            fake_workdir.mkdir()

            env_updates = {
                "HOME": str(fake_home),
                "SAGE_DB_TYPE": "file",
                "SAGE_AUTH_MODE": "native",
            }

            old_cwd = os.getcwd()
            try:
                os.chdir(fake_workdir)
                with patch.dict(os.environ, env_updates, clear=False):
                    fake_loguru = types.ModuleType("loguru")
                    fake_loguru.logger = _StubLogger()
                    with patch.dict(sys.modules, {"loguru": fake_loguru}):
                        llm_provider_service = importlib.import_module("common.services.llm_provider_service")
                        with patch.object(llm_provider_service, "probe_connection", new=fake_probe):
                            create_result, _ = self._run_cli_json_ok(
                                [
                                    "provider",
                                    "create",
                                    "--user-id",
                                    "alice",
                                    "--name",
                                    "DeepSeek Main",
                                    "--base-url",
                                    "https://api.deepseek.com/v1/",
                                    "--model",
                                    "deepseek-chat",
                                    "--api-key",
                                    "sk-test-12345678",
                                    "--set-default",
                                    "--json",
                                ]
                            )

                            provider_id = create_result["provider_id"]
                            self.assertTrue(provider_id)
                            self.assertEqual(create_result["status"], "ok")
                            self.assertEqual(create_result["provider"]["name"], "DeepSeek Main")
                            self.assertEqual(create_result["provider"]["model"], "deepseek-chat")
                            self.assertEqual(create_result["provider"]["base_url"], "https://api.deepseek.com/v1")
                            self.assertTrue(create_result["provider"]["is_default"])
                            self.assertEqual(create_result["provider"]["api_key_preview"], "sk-t...5678")

                            inspect_result, _ = self._run_cli_json_ok(
                                [
                                    "provider",
                                    "inspect",
                                    provider_id,
                                    "--user-id",
                                    "alice",
                                    "--json",
                                ]
                            )

                            self.assertEqual(inspect_result["provider_id"], provider_id)
                            self.assertEqual(inspect_result["provider"]["name"], "DeepSeek Main")
                            self.assertEqual(inspect_result["provider"]["api_keys"], ["sk-t...5678"])
                            self.assertTrue(inspect_result["provider"]["is_default"])

                            update_result, _ = self._run_cli_json_ok(
                                [
                                    "provider",
                                    "update",
                                    provider_id,
                                    "--user-id",
                                    "alice",
                                    "--name",
                                    "DeepSeek Updated",
                                    "--model",
                                    "deepseek-reasoner",
                                    "--unset-default",
                                    "--json",
                                ]
                            )

                            self.assertEqual(update_result["status"], "ok")
                            self.assertEqual(update_result["provider"]["name"], "DeepSeek Updated")
                            self.assertEqual(update_result["provider"]["model"], "deepseek-reasoner")
                            self.assertFalse(update_result["provider"]["is_default"])

                            list_result, _ = self._run_cli_json_ok(
                                [
                                    "provider",
                                    "list",
                                    "--user-id",
                                    "alice",
                                    "--model",
                                    "deepseek-reasoner",
                                    "--name-contains",
                                    "updated",
                                    "--json",
                                ]
                            )

                            self.assertEqual(list_result["total"], 1)
                            self.assertEqual(list_result["list"][0]["id"], provider_id)
                            self.assertEqual(
                                list_result["filters"],
                                {
                                    "default_only": False,
                                    "model": "deepseek-reasoner",
                                    "name_contains": "updated",
                                },
                            )

                            delete_result, _ = self._run_cli_json_ok(
                                [
                                    "provider",
                                    "delete",
                                    provider_id,
                                    "--user-id",
                                    "alice",
                                    "--json",
                                ]
                            )

                            self.assertEqual(delete_result["status"], "ok")
                            self.assertTrue(delete_result["deleted"])

                            final_list_result, _ = self._run_cli_json_ok(
                                [
                                    "provider",
                                    "list",
                                    "--user-id",
                                    "alice",
                                    "--json",
                                ]
                            )

                            self.assertEqual(final_list_result["total"], 0)
                            self.assertEqual(final_list_result["list"], [])

                            db_file = fake_home / ".sage" / "sage.db"
                            self.assertTrue(db_file.exists(), msg=f"expected db file at {db_file}")
            finally:
                os.chdir(old_cwd)

    def test_provider_default_switch_is_unique_across_real_cli_commands(self):
        async def fake_probe(api_key, base_url, model):
            return {
                "supported": True,
                "response": f"ok:{model}@{base_url}",
            }

        class _StubLogger:
            def bind(self, **_kwargs):
                return self

            def __getattr__(self, _name):
                return lambda *args, **kwargs: None

        with TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            fake_home = tmp_root / "home"
            fake_home.mkdir()
            fake_workdir = tmp_root / "workdir"
            fake_workdir.mkdir()

            env_updates = {
                "HOME": str(fake_home),
                "SAGE_DB_TYPE": "file",
                "SAGE_AUTH_MODE": "native",
            }

            old_cwd = os.getcwd()
            try:
                os.chdir(fake_workdir)
                with patch.dict(os.environ, env_updates, clear=False):
                    fake_loguru = types.ModuleType("loguru")
                    fake_loguru.logger = _StubLogger()
                    with patch.dict(sys.modules, {"loguru": fake_loguru}):
                        llm_provider_service = importlib.import_module("common.services.llm_provider_service")
                        with patch.object(llm_provider_service, "probe_connection", new=fake_probe):
                            first_create, _ = self._run_cli_json_ok(
                                [
                                    "provider",
                                    "create",
                                    "--user-id",
                                    "alice",
                                    "--name",
                                    "Provider One",
                                    "--base-url",
                                    "https://api.one.example/v1",
                                    "--model",
                                    "model-one",
                                    "--api-key",
                                    "sk-provider-one-1234",
                                    "--set-default",
                                    "--json",
                                ]
                            )
                            provider_one_id = first_create["provider_id"]
                            self.assertTrue(first_create["provider"]["is_default"])

                            second_create, _ = self._run_cli_json_ok(
                                [
                                    "provider",
                                    "create",
                                    "--user-id",
                                    "alice",
                                    "--name",
                                    "Provider Two",
                                    "--base-url",
                                    "https://api.two.example/v1",
                                    "--model",
                                    "model-two",
                                    "--api-key",
                                    "sk-provider-two-5678",
                                    "--set-default",
                                    "--json",
                                ]
                            )
                            provider_two_id = second_create["provider_id"]
                            self.assertTrue(second_create["provider"]["is_default"])

                            inspect_first, _ = self._run_cli_json_ok(
                                [
                                    "provider",
                                    "inspect",
                                    provider_one_id,
                                    "--user-id",
                                    "alice",
                                    "--json",
                                ]
                            )
                            self.assertFalse(inspect_first["provider"]["is_default"])

                            inspect_second, _ = self._run_cli_json_ok(
                                [
                                    "provider",
                                    "inspect",
                                    provider_two_id,
                                    "--user-id",
                                    "alice",
                                    "--json",
                                ]
                            )
                            self.assertTrue(inspect_second["provider"]["is_default"])

                            default_only_list, _ = self._run_cli_json_ok(
                                [
                                    "provider",
                                    "list",
                                    "--user-id",
                                    "alice",
                                    "--default-only",
                                    "--json",
                                ]
                            )
                            self.assertEqual(default_only_list["total"], 1)
                            self.assertEqual(default_only_list["list"][0]["id"], provider_two_id)

                            update_first_to_default, _ = self._run_cli_json_ok(
                                [
                                    "provider",
                                    "update",
                                    provider_one_id,
                                    "--user-id",
                                    "alice",
                                    "--set-default",
                                    "--json",
                                ]
                            )
                            self.assertTrue(update_first_to_default["provider"]["is_default"])

                            inspect_first_after, _ = self._run_cli_json_ok(
                                [
                                    "provider",
                                    "inspect",
                                    provider_one_id,
                                    "--user-id",
                                    "alice",
                                    "--json",
                                ]
                            )
                            self.assertTrue(inspect_first_after["provider"]["is_default"])

                            inspect_second_after, _ = self._run_cli_json_ok(
                                [
                                    "provider",
                                    "inspect",
                                    provider_two_id,
                                    "--user-id",
                                    "alice",
                                    "--json",
                                ]
                            )
                            self.assertFalse(inspect_second_after["provider"]["is_default"])

                            delete_default_exit, delete_default_stdout, _ = self._run_cli(
                                [
                                    "provider",
                                    "delete",
                                    provider_one_id,
                                    "--user-id",
                                    "alice",
                                    "--json",
                                ]
                            )
                            self.assertEqual(delete_default_exit, 1)
                            delete_default_payload = json.loads(delete_default_stdout)
                            self.assertIn("Cannot delete default provider", delete_default_payload["message"])
            finally:
                os.chdir(old_cwd)

    def test_provider_verify_and_create_surface_friendly_probe_errors(self):
        async def fake_probe(api_key, base_url, model):
            raise RuntimeError("401 unauthorized")

        class _StubLogger:
            def bind(self, **_kwargs):
                return self

            def __getattr__(self, _name):
                return lambda *args, **kwargs: None

        with TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            fake_home = tmp_root / "home"
            fake_home.mkdir()
            fake_workdir = tmp_root / "workdir"
            fake_workdir.mkdir()

            env_updates = {
                "HOME": str(fake_home),
                "SAGE_DB_TYPE": "file",
                "SAGE_AUTH_MODE": "native",
            }

            old_cwd = os.getcwd()
            try:
                os.chdir(fake_workdir)
                with patch.dict(os.environ, env_updates, clear=False):
                    fake_loguru = types.ModuleType("loguru")
                    fake_loguru.logger = _StubLogger()
                    with patch.dict(sys.modules, {"loguru": fake_loguru}):
                        llm_provider_service = importlib.import_module("common.services.llm_provider_service")
                        with patch.object(llm_provider_service, "probe_connection", new=fake_probe):
                            verify_exit, verify_stdout, _ = self._run_cli(
                                [
                                    "provider",
                                    "verify",
                                    "--base-url",
                                    "https://api.deepseek.com/v1",
                                    "--model",
                                    "deepseek-chat",
                                    "--api-key",
                                    "sk-test-12345678",
                                    "--json",
                                ]
                            )
                            self.assertEqual(verify_exit, 1)
                            verify_payload = json.loads(verify_stdout)
                            self.assertEqual(
                                verify_payload["message"],
                                "Provider authentication failed. Please check the API key.",
                            )
                            self.assertTrue(verify_payload["next_steps"])
                            self.assertEqual(verify_payload["exit_code"], 1)

                            create_exit, create_stdout, _ = self._run_cli(
                                [
                                    "provider",
                                    "create",
                                    "--user-id",
                                    "alice",
                                    "--name",
                                    "Broken Provider",
                                    "--base-url",
                                    "https://api.deepseek.com/v1",
                                    "--model",
                                    "deepseek-chat",
                                    "--api-key",
                                    "sk-test-12345678",
                                    "--json",
                                ]
                            )
                            self.assertEqual(create_exit, 1)
                            create_payload = json.loads(create_stdout)
                            self.assertEqual(
                                create_payload["message"],
                                "Cannot save provider. Provider authentication failed. Please check the API key.",
                            )
                            self.assertEqual(create_payload["exit_code"], 1)

                            list_result, _ = self._run_cli_json_ok(
                                [
                                    "provider",
                                    "list",
                                    "--user-id",
                                    "alice",
                                    "--json",
                                ]
                            )
                            self.assertEqual(list_result["total"], 0)
                            self.assertEqual(list_result["list"], [])
            finally:
                os.chdir(old_cwd)

    def test_provider_verify_and_create_surface_model_not_found_errors(self):
        async def fake_probe(api_key, base_url, model):
            raise RuntimeError("model not found")

        class _StubLogger:
            def bind(self, **_kwargs):
                return self

            def __getattr__(self, _name):
                return lambda *args, **kwargs: None

        with TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            fake_home = tmp_root / "home"
            fake_home.mkdir()
            fake_workdir = tmp_root / "workdir"
            fake_workdir.mkdir()

            env_updates = {
                "HOME": str(fake_home),
                "SAGE_DB_TYPE": "file",
                "SAGE_AUTH_MODE": "native",
            }

            old_cwd = os.getcwd()
            try:
                os.chdir(fake_workdir)
                with patch.dict(os.environ, env_updates, clear=False):
                    fake_loguru = types.ModuleType("loguru")
                    fake_loguru.logger = _StubLogger()
                    with patch.dict(sys.modules, {"loguru": fake_loguru}):
                        llm_provider_service = importlib.import_module("common.services.llm_provider_service")
                        with patch.object(llm_provider_service, "probe_connection", new=fake_probe):
                            verify_exit, verify_stdout, _ = self._run_cli(
                                [
                                    "provider",
                                    "verify",
                                    "--base-url",
                                    "https://api.deepseek.com/v1",
                                    "--model",
                                    "missing-model",
                                    "--api-key",
                                    "sk-test-12345678",
                                    "--json",
                                ]
                            )
                            self.assertEqual(verify_exit, 1)
                            verify_payload = json.loads(verify_stdout)
                            self.assertEqual(
                                verify_payload["message"],
                                "Provider model is not available. Please check the model name.",
                            )
                            self.assertEqual(verify_payload["exit_code"], 1)

                            create_exit, create_stdout, _ = self._run_cli(
                                [
                                    "provider",
                                    "create",
                                    "--user-id",
                                    "alice",
                                    "--name",
                                    "Missing Model Provider",
                                    "--base-url",
                                    "https://api.deepseek.com/v1",
                                    "--model",
                                    "missing-model",
                                    "--api-key",
                                    "sk-test-12345678",
                                    "--json",
                                ]
                            )
                            self.assertEqual(create_exit, 1)
                            create_payload = json.loads(create_stdout)
                            self.assertEqual(
                                create_payload["message"],
                                "Cannot save provider. Provider model is not available. Please check the model name.",
                            )
                            self.assertEqual(create_payload["exit_code"], 1)

                            list_result, _ = self._run_cli_json_ok(
                                [
                                    "provider",
                                    "list",
                                    "--user-id",
                                    "alice",
                                    "--json",
                                ]
                            )
                            self.assertEqual(list_result["total"], 0)
                            self.assertEqual(list_result["list"], [])
            finally:
                os.chdir(old_cwd)

    def test_provider_update_surfaces_timeout_errors_without_mutating_provider(self):
        async def fake_probe(api_key, base_url, model):
            if model == "stable-model":
                return {
                    "supported": True,
                    "response": f"ok:{model}@{base_url}",
                }
            raise RuntimeError("connection timeout")

        class _StubLogger:
            def bind(self, **_kwargs):
                return self

            def __getattr__(self, _name):
                return lambda *args, **kwargs: None

        with TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            fake_home = tmp_root / "home"
            fake_home.mkdir()
            fake_workdir = tmp_root / "workdir"
            fake_workdir.mkdir()

            env_updates = {
                "HOME": str(fake_home),
                "SAGE_DB_TYPE": "file",
                "SAGE_AUTH_MODE": "native",
            }

            old_cwd = os.getcwd()
            try:
                os.chdir(fake_workdir)
                with patch.dict(os.environ, env_updates, clear=False):
                    fake_loguru = types.ModuleType("loguru")
                    fake_loguru.logger = _StubLogger()
                    with patch.dict(sys.modules, {"loguru": fake_loguru}):
                        llm_provider_service = importlib.import_module("common.services.llm_provider_service")
                        with patch.object(llm_provider_service, "probe_connection", new=fake_probe):
                            create_result, _ = self._run_cli_json_ok(
                                [
                                    "provider",
                                    "create",
                                    "--user-id",
                                    "alice",
                                    "--name",
                                    "Stable Provider",
                                    "--base-url",
                                    "https://api.deepseek.com/v1",
                                    "--model",
                                    "stable-model",
                                    "--api-key",
                                    "sk-test-12345678",
                                    "--json",
                                ]
                            )
                            provider_id = create_result["provider_id"]

                            update_exit, update_stdout, _ = self._run_cli(
                                [
                                    "provider",
                                    "update",
                                    provider_id,
                                    "--user-id",
                                    "alice",
                                    "--model",
                                    "timeout-model",
                                    "--json",
                                ]
                            )
                            self.assertEqual(update_exit, 1)
                            update_payload = json.loads(update_stdout)
                            self.assertEqual(
                                update_payload["message"],
                                "Cannot update provider. Provider connection failed. Please check the base URL and network connectivity.",
                            )
                            self.assertEqual(update_payload["exit_code"], 1)

                            inspect_result, _ = self._run_cli_json_ok(
                                [
                                    "provider",
                                    "inspect",
                                    provider_id,
                                    "--user-id",
                                    "alice",
                                    "--json",
                                ]
                            )
                            self.assertEqual(inspect_result["provider"]["model"], "stable-model")
                            self.assertEqual(inspect_result["provider"]["name"], "Stable Provider")
            finally:
                os.chdir(old_cwd)

    def test_provider_verify_uses_env_defaults_when_args_are_omitted(self):
        captured = {}

        async def fake_probe(api_key, base_url, model):
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            captured["model"] = model
            return {
                "supported": True,
                "response": f"ok:{model}@{base_url}",
            }

        class _StubLogger:
            def bind(self, **_kwargs):
                return self

            def __getattr__(self, _name):
                return lambda *args, **kwargs: None

        with TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            fake_home = tmp_root / "home"
            fake_home.mkdir()
            fake_workdir = tmp_root / "workdir"
            fake_workdir.mkdir()

            env_updates = {
                "HOME": str(fake_home),
                "SAGE_DB_TYPE": "file",
                "SAGE_AUTH_MODE": "native",
                "SAGE_DEFAULT_LLM_API_BASE_URL": "https://api.defaults.example/v1/",
                "SAGE_DEFAULT_LLM_API_KEY": "sk-default-87654321",
                "SAGE_DEFAULT_LLM_MODEL_NAME": "default-model",
            }

            old_cwd = os.getcwd()
            try:
                os.chdir(fake_workdir)
                with patch.dict(os.environ, env_updates, clear=False):
                    fake_loguru = types.ModuleType("loguru")
                    fake_loguru.logger = _StubLogger()
                    with patch.dict(sys.modules, {"loguru": fake_loguru}):
                        llm_provider_service = importlib.import_module("common.services.llm_provider_service")
                        with patch.object(llm_provider_service, "probe_connection", new=fake_probe):
                            verify_result, _ = self._run_cli_json_ok(
                                [
                                    "provider",
                                    "verify",
                                    "--json",
                                ]
                            )

                            self.assertEqual(verify_result["status"], "ok")
                            self.assertEqual(
                                verify_result["sources"],
                                {
                                    "base_url": "default",
                                    "api_key": "default",
                                    "model": "default",
                                },
                            )
                            self.assertEqual(captured["api_key"], "sk-default-87654321")
                            self.assertEqual(captured["base_url"], "https://api.defaults.example/v1")
                            self.assertEqual(captured["model"], "default-model")
            finally:
                os.chdir(old_cwd)

    def test_provider_create_uses_env_defaults_when_args_are_omitted(self):
        captured = {}

        async def fake_probe(api_key, base_url, model):
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            captured["model"] = model
            return {
                "supported": True,
                "response": f"ok:{model}@{base_url}",
            }

        class _StubLogger:
            def bind(self, **_kwargs):
                return self

            def __getattr__(self, _name):
                return lambda *args, **kwargs: None

        with TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            fake_home = tmp_root / "home"
            fake_home.mkdir()
            fake_workdir = tmp_root / "workdir"
            fake_workdir.mkdir()

            env_updates = {
                "HOME": str(fake_home),
                "SAGE_DB_TYPE": "file",
                "SAGE_AUTH_MODE": "native",
                "SAGE_DEFAULT_LLM_API_BASE_URL": "https://api.defaults.example/v1/",
                "SAGE_DEFAULT_LLM_API_KEY": "sk-default-87654321",
                "SAGE_DEFAULT_LLM_MODEL_NAME": "default-model",
            }

            old_cwd = os.getcwd()
            try:
                os.chdir(fake_workdir)
                with patch.dict(os.environ, env_updates, clear=False):
                    fake_loguru = types.ModuleType("loguru")
                    fake_loguru.logger = _StubLogger()
                    with patch.dict(sys.modules, {"loguru": fake_loguru}):
                        llm_provider_service = importlib.import_module("common.services.llm_provider_service")
                        with patch.object(llm_provider_service, "probe_connection", new=fake_probe):
                            create_result, _ = self._run_cli_json_ok(
                                [
                                    "provider",
                                    "create",
                                    "--user-id",
                                    "alice",
                                    "--name",
                                    "Default Backed Provider",
                                    "--json",
                                ]
                            )

                            self.assertEqual(create_result["status"], "ok")
                            self.assertEqual(create_result["provider"]["name"], "Default Backed Provider")
                            self.assertEqual(create_result["provider"]["model"], "default-model")
                            self.assertEqual(create_result["provider"]["base_url"], "https://api.defaults.example/v1")
                            self.assertEqual(
                                create_result["sources"],
                                {
                                    "base_url": "default",
                                    "api_key": "default",
                                    "model": "default",
                                },
                            )
                            self.assertEqual(captured["api_key"], "sk-default-87654321")
                            self.assertEqual(captured["base_url"], "https://api.defaults.example/v1")
                            self.assertEqual(captured["model"], "default-model")
            finally:
                os.chdir(old_cwd)

    def test_provider_verify_missing_config_returns_friendly_json_error(self):
        class _StubLogger:
            def bind(self, **_kwargs):
                return self

            def __getattr__(self, _name):
                return lambda *args, **kwargs: None

        with TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            fake_home = tmp_root / "home"
            fake_home.mkdir()
            fake_workdir = tmp_root / "workdir"
            fake_workdir.mkdir()

            env_updates = {
                "HOME": str(fake_home),
                "SAGE_DB_TYPE": "file",
                "SAGE_AUTH_MODE": "native",
                "SAGE_DEFAULT_LLM_API_BASE_URL": "",
                "SAGE_DEFAULT_LLM_API_KEY": "",
                "SAGE_DEFAULT_LLM_MODEL_NAME": "",
            }

            old_cwd = os.getcwd()
            try:
                os.chdir(fake_workdir)
                with patch.dict(os.environ, env_updates, clear=False):
                    fake_loguru = types.ModuleType("loguru")
                    fake_loguru.logger = _StubLogger()
                    with patch.dict(sys.modules, {"loguru": fake_loguru}):
                        verify_exit, verify_stdout, _ = self._run_cli(
                            [
                                "provider",
                                "verify",
                                "--json",
                            ]
                        )
                        self.assertEqual(verify_exit, 1)
                        verify_payload = json.loads(verify_stdout)
                        self.assertEqual(
                            verify_payload["message"],
                            "Provider configuration is incomplete for create/verify.",
                        )
                        self.assertEqual(
                            verify_payload["next_steps"],
                            [
                                "Pass `--api-key`, or set `SAGE_DEFAULT_LLM_API_KEY` in `~/.sage/.sage_env` or local `.env`.",
                                "Pass `--base-url`, or set `SAGE_DEFAULT_LLM_API_BASE_URL` in `~/.sage/.sage_env` or local `.env`.",
                                "Pass `--model`, or set `SAGE_DEFAULT_LLM_MODEL_NAME` in `~/.sage/.sage_env` or local `.env`.",
                            ],
                        )
            finally:
                os.chdir(old_cwd)

    def test_provider_update_rejects_empty_api_key(self):
        async def fake_probe(api_key, base_url, model):
            return {
                "supported": True,
                "response": f"ok:{model}@{base_url}",
            }

        class _StubLogger:
            def bind(self, **_kwargs):
                return self

            def __getattr__(self, _name):
                return lambda *args, **kwargs: None

        with TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            fake_home = tmp_root / "home"
            fake_home.mkdir()
            fake_workdir = tmp_root / "workdir"
            fake_workdir.mkdir()

            env_updates = {
                "HOME": str(fake_home),
                "SAGE_DB_TYPE": "file",
                "SAGE_AUTH_MODE": "native",
            }

            old_cwd = os.getcwd()
            try:
                os.chdir(fake_workdir)
                with patch.dict(os.environ, env_updates, clear=False):
                    fake_loguru = types.ModuleType("loguru")
                    fake_loguru.logger = _StubLogger()
                    with patch.dict(sys.modules, {"loguru": fake_loguru}):
                        llm_provider_service = importlib.import_module("common.services.llm_provider_service")
                        with patch.object(llm_provider_service, "probe_connection", new=fake_probe):
                            create_result, _ = self._run_cli_json_ok(
                                [
                                    "provider",
                                    "create",
                                    "--user-id",
                                    "alice",
                                    "--name",
                                    "API Key Target",
                                    "--base-url",
                                    "https://api.update.example/v1",
                                    "--model",
                                    "update-model",
                                    "--api-key",
                                    "sk-update-12345678",
                                    "--json",
                                ]
                            )
                            provider_id = create_result["provider_id"]

                            update_exit, update_stdout, _ = self._run_cli(
                                [
                                    "provider",
                                    "update",
                                    provider_id,
                                    "--user-id",
                                    "alice",
                                    "--api-key",
                                    "   ",
                                    "--json",
                                ]
                            )
                            self.assertEqual(update_exit, 1)
                            update_payload = json.loads(update_stdout)
                            self.assertEqual(
                                update_payload["message"],
                                "Provider API key cannot be empty.",
                            )
                            self.assertEqual(
                                update_payload["next_steps"],
                                ["Pass a non-empty `--api-key` value."],
                            )
            finally:
                os.chdir(old_cwd)

    def test_provider_update_without_fields_returns_cli_error(self):
        async def fake_probe(api_key, base_url, model):
            return {
                "supported": True,
                "response": f"ok:{model}@{base_url}",
            }

        class _StubLogger:
            def bind(self, **_kwargs):
                return self

            def __getattr__(self, _name):
                return lambda *args, **kwargs: None

        with TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            fake_home = tmp_root / "home"
            fake_home.mkdir()
            fake_workdir = tmp_root / "workdir"
            fake_workdir.mkdir()

            env_updates = {
                "HOME": str(fake_home),
                "SAGE_DB_TYPE": "file",
                "SAGE_AUTH_MODE": "native",
            }

            old_cwd = os.getcwd()
            try:
                os.chdir(fake_workdir)
                with patch.dict(os.environ, env_updates, clear=False):
                    fake_loguru = types.ModuleType("loguru")
                    fake_loguru.logger = _StubLogger()
                    with patch.dict(sys.modules, {"loguru": fake_loguru}):
                        llm_provider_service = importlib.import_module("common.services.llm_provider_service")
                        with patch.object(llm_provider_service, "probe_connection", new=fake_probe):
                            create_result, _ = self._run_cli_json_ok(
                                [
                                    "provider",
                                    "create",
                                    "--user-id",
                                    "alice",
                                    "--name",
                                    "Update Target",
                                    "--base-url",
                                    "https://api.update.example/v1",
                                    "--model",
                                    "update-model",
                                    "--api-key",
                                    "sk-update-12345678",
                                    "--json",
                                ]
                            )
                            provider_id = create_result["provider_id"]

                            update_exit, update_stdout, _ = self._run_cli(
                                [
                                    "provider",
                                    "update",
                                    provider_id,
                                    "--user-id",
                                    "alice",
                                    "--json",
                                ]
                            )
                            self.assertEqual(update_exit, 1)
                            update_payload = json.loads(update_stdout)
                            self.assertEqual(
                                update_payload["message"],
                                "No provider fields were supplied for update.",
                            )
                            self.assertEqual(
                                update_payload["next_steps"],
                                [
                                    "Pass at least one field such as `--model`, `--base-url`, `--api-key`, or `--name`.",
                                ],
                            )
            finally:
                os.chdir(old_cwd)

    def test_provider_delete_default_non_json_writes_plain_stderr_message(self):
        async def fake_probe(api_key, base_url, model):
            return {
                "supported": True,
                "response": f"ok:{model}@{base_url}",
            }

        class _StubLogger:
            def bind(self, **_kwargs):
                return self

            def __getattr__(self, _name):
                return lambda *args, **kwargs: None

        with TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            fake_home = tmp_root / "home"
            fake_home.mkdir()
            fake_workdir = tmp_root / "workdir"
            fake_workdir.mkdir()

            env_updates = {
                "HOME": str(fake_home),
                "SAGE_DB_TYPE": "file",
                "SAGE_AUTH_MODE": "native",
            }

            old_cwd = os.getcwd()
            try:
                os.chdir(fake_workdir)
                with patch.dict(os.environ, env_updates, clear=False):
                    fake_loguru = types.ModuleType("loguru")
                    fake_loguru.logger = _StubLogger()
                    with patch.dict(sys.modules, {"loguru": fake_loguru}):
                        llm_provider_service = importlib.import_module("common.services.llm_provider_service")
                        with patch.object(llm_provider_service, "probe_connection", new=fake_probe):
                            create_result, _ = self._run_cli_json_ok(
                                [
                                    "provider",
                                    "create",
                                    "--user-id",
                                    "alice",
                                    "--name",
                                    "Default Provider",
                                    "--base-url",
                                    "https://api.default.example/v1",
                                    "--model",
                                    "default-model",
                                    "--api-key",
                                    "sk-default-12345678",
                                    "--set-default",
                                    "--json",
                                ]
                            )
                            provider_id = create_result["provider_id"]

                            delete_exit, delete_stdout, delete_stderr = self._run_cli(
                                [
                                    "provider",
                                    "delete",
                                    provider_id,
                                    "--user-id",
                                    "alice",
                                ]
                            )
                            self.assertEqual(delete_exit, 1)
                            self.assertEqual(delete_stdout, "")
                            self.assertIn("Cannot delete default provider", delete_stderr)
            finally:
                os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()

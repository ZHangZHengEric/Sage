#!/usr/bin/env python3
import sys
import types
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import app.cli.service as cli_service
from app.cli.service import CLIError


class StubConfig:
    default_llm_api_key = "sk-default-12345678"
    default_llm_api_base_url = "https://example.com/v1"
    default_llm_model_name = "example-model"


class TestProviderHelpers(unittest.TestCase):
    def test_mask_api_key_hides_middle(self):
        self.assertEqual(cli_service._mask_api_key("sk-abcdefghijkl"), "sk-a...ijkl")

    def test_sanitize_provider_record_masks_api_keys(self):
        result = cli_service._sanitize_provider_record(
            {
                "id": "provider-1",
                "api_keys": ["sk-abcdefghijkl"],
            }
        )
        self.assertEqual(result["api_keys"], ["sk-a...ijkl"])
        self.assertEqual(result["api_key_preview"], "sk-a...ijkl")

    def test_resolve_provider_create_data_uses_cli_defaults(self):
        original_init_cli_config = cli_service.init_cli_config
        try:
            cli_service.init_cli_config = lambda init_logging=False: StubConfig()
            result = cli_service._resolve_provider_create_data()
        finally:
            cli_service.init_cli_config = original_init_cli_config

        data = result["data"]
        self.assertEqual(data.base_url, "https://example.com/v1")
        self.assertEqual(data.api_keys, ["sk-default-12345678"])
        self.assertEqual(data.model, "example-model")
        self.assertEqual(
            result["sources"],
            {"base_url": "default", "api_key": "default", "model": "default"},
        )

    def test_build_provider_update_data_requires_at_least_one_field(self):
        with self.assertRaises(CLIError) as ctx:
            cli_service._build_provider_update_data()
        self.assertIn("No provider fields were supplied", str(ctx.exception))

    def test_verify_cli_provider_maps_probe_errors_to_cli_error(self):
        original_init_cli_config = cli_service.init_cli_config
        original_common_services = sys.modules.get("common.services")

        async def _run():
            fake_common_services = types.ModuleType("common.services")
            fake_common_services.llm_provider_service = types.SimpleNamespace(
                verify_provider=_fake_verify_provider,
            )
            sys.modules["common.services"] = fake_common_services
            try:
                cli_service.init_cli_config = lambda init_logging=False: StubConfig()
                with self.assertRaises(CLIError) as ctx:
                    await cli_service.verify_cli_provider()
                self.assertIn("Provider authentication failed", str(ctx.exception))
            finally:
                cli_service.init_cli_config = original_init_cli_config
                if original_common_services is None:
                    sys.modules.pop("common.services", None)
                else:
                    sys.modules["common.services"] = original_common_services

        async def _fake_verify_provider(_data):
            raise RuntimeError("401 unauthorized")

        import asyncio

        asyncio.run(_run())

    def test_inspect_cli_provider_rejects_foreign_user(self):
        original_common_models = sys.modules.get("common.models.llm_provider")

        async def _run():
            fake_module = types.ModuleType("common.models.llm_provider")

            class _Provider:
                user_id = "bob"

                def to_dict(self):
                    return {
                        "id": "provider-1",
                        "name": "foreign",
                        "api_keys": ["sk-abcdefghijkl"],
                    }

            class _Dao:
                async def get_by_id(self, provider_id):
                    return _Provider()

            fake_module.LLMProviderDao = _Dao
            sys.modules["common.models.llm_provider"] = fake_module
            try:
                with self.assertRaises(CLIError) as ctx:
                    await cli_service.inspect_cli_provider(provider_id="provider-1", user_id="alice")
                self.assertIn("is not visible to user alice", str(ctx.exception))
            finally:
                if original_common_models is None:
                    sys.modules.pop("common.models.llm_provider", None)
                else:
                    sys.modules["common.models.llm_provider"] = original_common_models

        import asyncio

        asyncio.run(_run())

    def test_query_cli_providers_applies_filters(self):
        original_list_cli_providers = cli_service.list_cli_providers

        async def _run():
            async def _fake_list_cli_providers(*, user_id=None):
                return {
                    "user_id": user_id or "alice",
                    "total": 3,
                    "list": [
                        {"id": "p1", "name": "DeepSeek Main", "model": "deepseek-chat", "is_default": True},
                        {"id": "p2", "name": "DeepSeek Backup", "model": "deepseek-chat", "is_default": False},
                        {"id": "p3", "name": "Qwen Fast", "model": "qwen-max", "is_default": False},
                    ],
                }

            cli_service.list_cli_providers = _fake_list_cli_providers
            try:
                result = await cli_service.query_cli_providers(
                    user_id="alice",
                    default_only=True,
                    model="deepseek-chat",
                    name_contains="main",
                )
            finally:
                cli_service.list_cli_providers = original_list_cli_providers

            self.assertEqual(result["total"], 1)
            self.assertEqual(result["list"][0]["id"], "p1")
            self.assertEqual(
                result["filters"],
                {
                    "default_only": True,
                    "model": "deepseek-chat",
                    "name_contains": "main",
                },
            )

        import asyncio

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()

import unittest

from sagents.llm import model_capabilities
from sagents.llm.model_capabilities import (
    build_llm_extra_body,
    get_default_thinking_level,
    get_supported_thinking_levels,
    is_deepseek_model,
    is_official_minimax_endpoint,
    is_minimax_model,
    is_openai_reasoning_model,
    normalize_reasoning_effort,
    resolve_reasoning_effort,
)


class TestResolveReasoningEffort(unittest.TestCase):
    def test_thinking_enabled_uses_medium(self):
        self.assertEqual(
            resolve_reasoning_effort(enable_thinking=True, env_value=None),
            "medium",
        )
        # 思考开启时即便环境变量给了别的值，也不应被覆盖
        self.assertEqual(
            resolve_reasoning_effort(enable_thinking=True, env_value="minimal"),
            "medium",
        )

    def test_thinking_disabled_default_medium(self):
        self.assertEqual(
            resolve_reasoning_effort(enable_thinking=False, env_value=None),
            "medium",
        )
        self.assertEqual(
            resolve_reasoning_effort(enable_thinking=False, env_value=""),
            "medium",
        )

    def test_thinking_disabled_env_override(self):
        for v in [
            "minimal",
            "low",
            "medium",
            "high",
            "xhigh",
            "MINIMAL",
            " High ",
        ]:
            with self.subTest(env=v):
                self.assertEqual(
                    resolve_reasoning_effort(enable_thinking=False, env_value=v),
                    v.strip().lower(),
                )

    def test_thinking_disabled_invalid_env_falls_back(self):
        for v in ["foobar", "off", "none", "0"]:
            with self.subTest(env=v):
                self.assertEqual(
                    resolve_reasoning_effort(enable_thinking=False, env_value=v),
                    "medium",
                )

    def test_custom_default_off(self):
        self.assertEqual(
            resolve_reasoning_effort(
                enable_thinking=False, env_value=None, default_off="minimal"
            ),
            "minimal",
        )


class TestBuildClient(unittest.TestCase):
    def test_disables_response_compression_for_streaming_probes(self):
        client = model_capabilities._build_client(
            "test-key", "https://provider.example/v1", timeout=10.0
        )

        try:
            self.assertEqual(
                client._client.headers["Accept-Encoding"], "identity"
            )
        finally:
            import asyncio

            asyncio.run(client.close())


class TestIsOpenAIReasoningModel(unittest.TestCase):
    def test_reasoning_models_recognized(self):
        for name in [
            "o1",
            "o1-mini",
            "o1-preview",
            "o3",
            "o3-mini",
            "o3-pro",
            "o4",
            "o4-mini",
            "gpt-5",
            "gpt-5-mini",
            "gpt-5.1",
            "gpt-5.4-mini",
            "gpt-5.4-mini-2026-03-17",
            "GPT-5",  # 大小写无关
        ]:
            with self.subTest(model=name):
                self.assertTrue(is_openai_reasoning_model(name))

    def test_non_reasoning_models_not_recognized(self):
        for name in [
            "",
            None,
            "gpt-4",
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4-turbo",
            "gpt-3.5-turbo",
            "qwen-max",
            "qwen2.5-7b",
            "deepseek-chat",
            "deepseek-r1",  # 非 OpenAI 系，走 enable_thinking 路径
            "claude-3-5-sonnet",
            "o100",  # 不应被宽匹配
        ]:
            with self.subTest(model=name):
                self.assertFalse(is_openai_reasoning_model(name))


class TestBuildLlmExtraBody(unittest.TestCase):
    def test_reasoning_model_sets_effort_and_step(self):
        body = build_llm_extra_body(
            "gpt-5.6-luna",
            enable_thinking=False,
            step_name="compress_history",
        )
        self.assertEqual(body["_step_name"], "compress_history")
        self.assertEqual(body["reasoning_effort"], "medium")
        self.assertNotIn("enable_thinking", body)

    def test_reasoning_model_thinking_on_uses_medium(self):
        body = build_llm_extra_body("o3-mini", enable_thinking=True)
        self.assertEqual(body["reasoning_effort"], "medium")

    def test_explicit_openai_thinking_level_is_used(self):
        body = build_llm_extra_body(
            "gpt-5.4", enable_thinking=True, thinking_level="high"
        )
        self.assertEqual(body["reasoning_effort"], "high")

    def test_deepseek_thinking_level_uses_native_effort(self):
        body = build_llm_extra_body(
            "deepseek-v4-flash",
            base_url="https://api.deepseek.com",
            enable_thinking=True,
            thinking_level="max",
        )
        self.assertEqual(body["reasoning_effort"], "max")
        self.assertEqual(body["thinking"], {"type": "enabled"})
        self.assertNotIn("enable_thinking", body)
        self.assertNotIn("chat_template_kwargs", body)

    def test_minimax_native_api_splits_reasoning_without_generic_flags(self):
        body = build_llm_extra_body(
            "MiniMax-M2.7",
            base_url="https://api.minimaxi.com/v1",
            enable_thinking=False,
            step_name="task_execution",
        )

        self.assertTrue(is_minimax_model("MiniMax-M2.7-highspeed"))
        self.assertTrue(
            is_official_minimax_endpoint("https://api.minimax.io/v1")
        )
        self.assertEqual(
            body,
            {"_step_name": "task_execution", "reasoning_split": True},
        )

    def test_minimax_slug_on_third_party_endpoint_stays_generic(self):
        body = build_llm_extra_body(
            "MiniMax-M2.7",
            base_url="https://gateway.example/v1",
            enable_thinking=False,
        )

        self.assertNotIn("reasoning_split", body)
        self.assertFalse(body["enable_thinking"])

    def test_deepseek_uses_accepted_low_high_max_levels(self):
        self.assertTrue(is_deepseek_model("DeepSeek-V4-Pro"))
        self.assertTrue(is_deepseek_model("deepseek/deepseek-v4-pro"))
        self.assertEqual(
            normalize_reasoning_effort(
                "deepseek-v4-flash",
                "minimal",
                base_url="https://api.deepseek.com",
            ),
            "low",
        )
        self.assertEqual(
            normalize_reasoning_effort(
                "deepseek-v4-pro",
                "medium",
                base_url="https://api.deepseek.com",
            ),
            "high",
        )
        self.assertEqual(
            normalize_reasoning_effort(
                "deepseek-v4-flash",
                "low",
                base_url="https://api.deepseek.com",
            ),
            "low",
        )
        self.assertEqual(
            get_supported_thinking_levels(
                "deepseek-v4-pro", "https://api.deepseek.com"
            ),
            ("low", "high", "max"),
        )

    def test_openai_levels_are_model_specific(self):
        self.assertEqual(
            get_supported_thinking_levels("gpt-5"),
            ("minimal", "low", "medium", "high"),
        )
        self.assertEqual(
            get_supported_thinking_levels("gpt-5.4-mini"),
            ("low", "medium", "high", "xhigh"),
        )
        self.assertEqual(
            get_supported_thinking_levels("gpt-5.6-sol"),
            ("low", "medium", "high", "xhigh", "max"),
        )
        self.assertEqual(
            normalize_reasoning_effort("gpt-5.4", "max"),
            "xhigh",
        )
        self.assertEqual(
            normalize_reasoning_effort("gpt-5.4", "minimal"),
            "low",
        )
        self.assertEqual(get_default_thinking_level("gpt-5.6"), "medium")

    def test_provider_specific_non_openai_levels(self):
        aliyun_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        self.assertEqual(
            get_supported_thinking_levels("qwen3.8-max-preview", aliyun_url),
            ("low", "medium", "xhigh"),
        )
        self.assertEqual(
            get_default_thinking_level("qwen3.8-max-preview", aliyun_url),
            "medium",
        )
        qwen_body = build_llm_extra_body(
            "qwen3.8-max-preview",
            base_url=aliyun_url,
            enable_thinking=True,
            thinking_level="max",
        )
        self.assertEqual(
            qwen_body,
            {"enable_thinking": True, "reasoning_effort": "xhigh"},
        )
        self.assertEqual(
            get_supported_thinking_levels(
                "glm-5.2", "https://open.bigmodel.cn/api/paas/v4"
            ),
            ("high", "max"),
        )
        body = build_llm_extra_body(
            "glm-5.2",
            base_url="https://open.bigmodel.cn/api/paas/v4",
            enable_thinking=True,
            thinking_level="max",
        )
        self.assertEqual(body["reasoning_effort"], "max")
        self.assertEqual(body["thinking"], {"type": "enabled"})
        self.assertNotIn("enable_thinking", body)
        self.assertNotIn("chat_template_kwargs", body)

    def test_aliyun_deepseek_uses_compatible_protocol_fields(self):
        body = build_llm_extra_body(
            "deepseek-v4-flash",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            enable_thinking=True,
            thinking_level="max",
        )
        self.assertEqual(body["reasoning_effort"], "max")
        self.assertTrue(body["enable_thinking"])
        self.assertNotIn("thinking", body)

    def test_non_reasoning_model_sets_thinking_flags(self):
        body = build_llm_extra_body(
            "gpt-4o",
            enable_thinking=False,
            step_name="agent_step",
        )
        self.assertEqual(body["_step_name"], "agent_step")
        self.assertFalse(body["enable_thinking"])
        self.assertEqual(body["thinking"], {"type": "disabled"})
        self.assertEqual(
            body["chat_template_kwargs"], {"enable_thinking": False}
        )
        self.assertNotIn("reasoning_effort", body)

    def test_extra_fields_merged(self):
        body = build_llm_extra_body(
            "gpt-4o",
            enable_thinking=False,
            step_name="capability_probe_structured_output",
            extra={"top_k": 20},
        )
        self.assertEqual(body["top_k"], 20)
        self.assertFalse(body["enable_thinking"])
        self.assertEqual(body["_step_name"], "capability_probe_structured_output")


class TestProbeLlmCapabilities(unittest.IsolatedAsyncioTestCase):
    async def test_optional_capability_probe_failures_do_not_fail_connection_probe(
        self,
    ):
        calls = []

        async def fake_connection(api_key, base_url, model):
            calls.append(("connection", api_key, base_url, model))
            return {"supported": True, "response": "ok"}

        async def fake_multimodal(api_key, base_url, model):
            calls.append(("multimodal", api_key, base_url, model))
            raise RuntimeError(
                "Failed to deserialize the JSON body into the target type: "
                "messages[0]: unknown variant `image_url`, expected `text`"
            )

        async def fake_structured_output(api_key, base_url, model):
            calls.append(("structured_output", api_key, base_url, model))
            return {"supported": True, "response": '{"ok": true}'}

        original_connection = model_capabilities.probe_connection
        original_multimodal = model_capabilities.probe_multimodal
        original_structured_output = model_capabilities.probe_structured_output
        model_capabilities.probe_connection = fake_connection
        model_capabilities.probe_multimodal = fake_multimodal
        model_capabilities.probe_structured_output = fake_structured_output
        try:
            result = await model_capabilities.probe_llm_capabilities(
                "sk-test",
                "https://example.com/v1",
                "text-only-model",
            )
        finally:
            model_capabilities.probe_connection = original_connection
            model_capabilities.probe_multimodal = original_multimodal
            model_capabilities.probe_structured_output = original_structured_output

        self.assertEqual(
            calls,
            [
                ("connection", "sk-test", "https://example.com/v1", "text-only-model"),
                ("multimodal", "sk-test", "https://example.com/v1", "text-only-model"),
                (
                    "structured_output",
                    "sk-test",
                    "https://example.com/v1",
                    "text-only-model",
                ),
            ],
        )
        self.assertTrue(result["connection"]["supported"])
        self.assertFalse(result["supports_multimodal"])
        self.assertIn("unknown variant `image_url`", result["multimodal"]["error"])
        self.assertTrue(result["supports_structured_output"])


if __name__ == "__main__":
    unittest.main()

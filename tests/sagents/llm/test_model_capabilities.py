import unittest

from sagents.llm import model_capabilities
from sagents.llm.model_capabilities import (
    is_openai_reasoning_model,
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

    def test_thinking_disabled_default_low(self):
        self.assertEqual(
            resolve_reasoning_effort(enable_thinking=False, env_value=None),
            "low",
        )
        self.assertEqual(
            resolve_reasoning_effort(enable_thinking=False, env_value=""),
            "low",
        )

    def test_thinking_disabled_env_override(self):
        for v in ["minimal", "low", "medium", "high", "MINIMAL", " High "]:
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
                    "low",
                )

    def test_custom_default_off(self):
        self.assertEqual(
            resolve_reasoning_effort(enable_thinking=False, env_value=None, default_off="minimal"),
            "minimal",
        )


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


class TestProbeLlmCapabilities(unittest.IsolatedAsyncioTestCase):
    async def test_optional_capability_probe_failures_do_not_fail_connection_probe(self):
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
                ("structured_output", "sk-test", "https://example.com/v1", "text-only-model"),
            ],
        )
        self.assertTrue(result["connection"]["supported"])
        self.assertFalse(result["supports_multimodal"])
        self.assertIn("unknown variant `image_url`", result["multimodal"]["error"])
        self.assertTrue(result["supports_structured_output"])


if __name__ == "__main__":
    unittest.main()

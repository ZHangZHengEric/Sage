import unittest

from sagents.llm import model_capabilities


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

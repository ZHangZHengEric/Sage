"""Small protocol adapter for the standalone MCP simulator.

Configuration comes from the caller or standalone JSON config, never Sage DAOs.
"""
from __future__ import annotations

from types import SimpleNamespace

import httpx


class SimulatorClient:
    def __init__(self, config: dict):
        self.config = dict(config)
        self.chat = SimpleNamespace(completions=self)

    async def create(self, *, model, messages, temperature, extra_body=None, response_format=None):
        config = self.config
        protocol = config.get("protocol", "openai-chat-completions")
        base = config["base_url"].rstrip("/")
        headers = {"Authorization": f"Bearer {config['api_key']}"}
        payload = {"model": model, "temperature": temperature}
        if protocol == "openai-chat-completions":
            url = base + "/chat/completions"
            payload.update(messages=messages)
            # Provider-specific request extensions must be explicitly configured.
            payload.update(config.get("extra_body") or {})
            if response_format:
                payload["response_format"] = response_format
            if config.get("max_tokens"):
                payload[config.get("max_tokens_field", "max_tokens")] = config["max_tokens"]
        elif protocol == "openai-responses":
            url = base + "/responses"
            payload["input"] = messages
            if response_format:
                payload["text"] = {"format": response_format}
            if config.get("max_tokens"):
                payload["max_output_tokens"] = config["max_tokens"]
        elif protocol == "anthropic-messages":
            url = base + ("/messages" if base.endswith("/v1") else "/v1/messages")
            headers = {"x-api-key": config["api_key"], "anthropic-version": "2023-06-01"}
            payload.update(
                system="\n".join(m["content"] for m in messages if m["role"] == "system"),
                messages=[m for m in messages if m["role"] != "system"],
                max_tokens=config.get("max_tokens", 4096),
            )
        else:
            raise ValueError(f"Unsupported AnyTool model protocol: {protocol}")
        async with httpx.AsyncClient(timeout=config.get("timeout", 60.0)) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        if protocol == "openai-chat-completions":
            text = data["choices"][0]["message"].get("content") or ""
        elif protocol == "openai-responses":
            text = "".join(
                block.get("text", "") for item in data.get("output", [])
                for block in item.get("content", []) if block.get("type") == "output_text"
            )
        else:
            text = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


async def resolve_model_client(user_id, server_config, *, session_id=None, prefer_first_provider=False):
    config = server_config.get("simulator") or {}
    if not all(config.get(field) for field in ("api_key", "base_url", "model")):
        raise RuntimeError("AnyTool requires simulator api_key, base_url, and model")
    return SimulatorClient(config), config["model"]

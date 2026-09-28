"""Standalone AnyTool simulation; no Sage runtime or persistence dependencies."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple
from loguru import logger
from .model_client import resolve_model_client

def _build_no_thinking_extra_body(model: str) -> Dict[str, Any]:
    """复用与各 agent 一致的"禁用思考/推理"请求参数。"""
    model_name = (model or "").lower()
    is_openai_reasoning_model = (
        model_name.startswith("o1")
        or model_name.startswith("o3")
        or model_name.startswith("gpt-5")
    )
    if is_openai_reasoning_model:
        return {"reasoning_effort": "medium"}
    return {
        "chat_template_kwargs": {"enable_thinking": False},
        "enable_thinking": False,
        "thinking": {"type": "disabled"},
    }


def normalize_anytool_tools(raw_tools: Any) -> List[Dict[str, Any]]:
    tools: List[Dict[str, Any]] = []
    if not isinstance(raw_tools, list):
        return tools

    for raw_tool in raw_tools:
        if not isinstance(raw_tool, dict):
            continue

        name = str(raw_tool.get("name", "")).strip()
        if not name:
            continue

        parameters = raw_tool.get("parameters") or {}
        if not isinstance(parameters, dict):
            parameters = {}

        returns = raw_tool.get("returns") or {}
        if not isinstance(returns, dict):
            returns = {}

        tools.append(
            {
                "name": name,
                "description": str(raw_tool.get("description", "")).strip(),
                "parameters": parameters,
                "returns": returns,
                "prompt_template": raw_tool.get("prompt_template")
                or raw_tool.get("prompt")
                or "",
                "example_input": raw_tool.get("example_input")
                or raw_tool.get("example")
                or {},
                "example_output": raw_tool.get("example_output") or {},
                "notes": raw_tool.get("notes") or "",
            }
        )

    return tools


def _normalize_schema(schema: Any) -> Dict[str, Any]:
    if isinstance(schema, dict):
        return schema
    return {}


def _build_tool_prompt(
    *,
    server_name: str,
    tool_def: Dict[str, Any],
    arguments: Dict[str, Any],
    server_config: Dict[str, Any],
) -> List[Dict[str, str]]:
    simulator = server_config.get("simulator") or {}
    system_prompt = simulator.get("system_prompt") or (
        "You are an AnyTool simulator for Sage. "
        "Return only valid JSON. "
        "Use the tool definition, input schema, and output schema to produce a realistic result."
    )

    returns_schema = _normalize_schema(tool_def.get("returns"))
    input_schema = _normalize_schema(tool_def.get("parameters"))

    tool_context = {
        "server_name": server_name,
        "tool_name": tool_def.get("name", ""),
        "tool_description": tool_def.get("description", ""),
        "input_schema": input_schema,
        "returns_schema": returns_schema,
        "example_input": tool_def.get("example_input") or {},
        "example_output": tool_def.get("example_output") or {},
        "arguments": arguments,
        "notes": tool_def.get("notes") or "",
        "prompt_template": tool_def.get("prompt_template") or "",
    }

    user_prompt = (
        "Simulate the following tool call and respond with JSON only.\n"
        f"{json.dumps(tool_context, ensure_ascii=False, indent=2)}\n\n"
        "If the tool definition includes a prompt_template, treat it as additional guidance.\n"
        "Do not include markdown fences or explanations."
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _extract_json_result(raw_text: str) -> Tuple[Optional[Any], Optional[str]]:
    if raw_text is None:
        return None, "empty response"

    text = str(raw_text).strip()
    if not text:
        return None, "empty response"

    try:
        return json.loads(text), None
    except Exception:
        pass

    try:
        match = re.search(r"```(?:json)?\s*\n([\s\S]*?)\n```", text)
        extracted = match.group(1) if match else text
        if extracted != text:
            return json.loads(extracted), None
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1]), None
        except Exception as exc:
            return None, str(exc)

    return None, "unable to parse JSON from model output"


async def generate_anytool_result(
    *,
    server_name: str,
    tool_def: Dict[str, Any],
    arguments: Dict[str, Any],
    server_config: Dict[str, Any],
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    prefer_first_provider: bool = False,
    model_resolver=None,
) -> Dict[str, Any]:
    sanitized_arguments = {
        key: value
        for key, value in (arguments or {}).items()
        if key not in {"session_id", "user_id"}
    }
    messages = _build_tool_prompt(
        server_name=server_name,
        tool_def=tool_def,
        arguments=sanitized_arguments,
        server_config=server_config,
    )
    simulator = server_config.get("simulator") or {}
    temperature = simulator.get("temperature", 0.2)

    model_client, model_name = await (model_resolver or resolve_model_client)(
        user_id,
        server_config,
        session_id=session_id,
        prefer_first_provider=prefer_first_provider,
    )
    logger.info(
        f"[AnyTool] Simulating tool={tool_def.get('name')} server={server_name} model={model_name}"
    )

    request_kwargs: Dict[str, Any] = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
        # Ask for JSON output without a visible reasoning trace.
        "extra_body": _build_no_thinking_extra_body(model_name),
    }
    try:
        request_kwargs["response_format"] = {"type": "json_object"}
    except Exception:
        pass

    raw_text = ""
    response = None
    try:
        response = await model_client.chat.completions.create(**request_kwargs)
        choice = response.choices[0] if getattr(response, "choices", None) else None
        message = getattr(choice, "message", None) if choice else None
        raw_text = getattr(message, "content", "") or ""
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        if status is None:
            status = getattr(getattr(exc, "response", None), "status_code", None)
        if status not in {400, 422}:
            raise
        logger.warning(
            f"[AnyTool] JSON mode failed, retrying without response_format: {exc}"
        )
        request_kwargs.pop("response_format", None)
        response = await model_client.chat.completions.create(**request_kwargs)
        choice = response.choices[0] if getattr(response, "choices", None) else None
        message = getattr(choice, "message", None) if choice else None
        raw_text = getattr(message, "content", "") or ""

    parsed, parse_error = _extract_json_result(raw_text)
    if parse_error:
        logger.warning(
            f"[AnyTool] Failed to parse JSON for tool={tool_def.get('name')}: {parse_error}"
        )
        parsed = {
            "content": raw_text,
            "_parse_error": parse_error,
        }

    return {
        "server_name": server_name,
        "tool_name": tool_def.get("name", ""),
        "model": model_name,
        "raw_text": raw_text,
        "parsed": parsed,
        "tool_definition": tool_def,
        "arguments": sanitized_arguments,
    }

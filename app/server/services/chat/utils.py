import asyncio
import json
from typing import Any, AsyncGenerator, Dict, List, Tuple

from loguru import logger
from openai import AsyncOpenAI

from ...core.client.chat import get_chat_client
from ...core.config import StartupConfig


def resolve_llm_config(request_llm_config: dict, server_args: StartupConfig) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    raw_config = {k: v for k, v in (request_llm_config or {}).items() if v is not None and v != ""}
    model_name = raw_config.get("model", server_args.default_llm_model_name)
    final_model_config = {"model": model_name}
    if "max_tokens" in raw_config:
        final_model_config["max_tokens"] = int(raw_config["max_tokens"])
    elif server_args.default_llm_max_tokens is not None:
        final_model_config["max_tokens"] = int(server_args.default_llm_max_tokens)
    if "temperature" in raw_config:
        final_model_config["temperature"] = float(raw_config["temperature"])
    elif server_args.default_llm_temperature is not None:
        final_model_config["temperature"] = float(server_args.default_llm_temperature)
    if "top_p" in raw_config:
        final_model_config["top_p"] = float(raw_config["top_p"])
    elif server_args.default_llm_top_p is not None:
        final_model_config["top_p"] = float(server_args.default_llm_top_p)
    if "presence_penalty" in raw_config:
        final_model_config["presence_penalty"] = float(raw_config["presence_penalty"])
    elif server_args.default_llm_presence_penalty is not None:
        final_model_config["presence_penalty"] = float(server_args.default_llm_presence_penalty)
    client_params = {
        "use_default_client": not raw_config,
        "api_key": raw_config.get("apiKey", server_args.default_llm_api_key),
        "base_url": raw_config.get("baseUrl", server_args.default_llm_api_base_url),
    }
    return raw_config, final_model_config, client_params


def create_model_client(client_params: Dict[str, Any], model_name: str) -> Any:
    if client_params.get("use_default_client"):
        logger.info("使用默认模型客户端")
        return get_chat_client()
    api_key = client_params.get("api_key")
    base_url = client_params.get("base_url")
    logger.info(f"初始化自定义模型客户端: model={model_name}, base_url={base_url}")
    model_client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
    )
    model_client.model = model_name
    return model_client

def create_tool_proxy(available_tools: List[str], multi_agent: bool):
    from sagents.tool.tool_manager import get_tool_manager
    from sagents.tool.tool_proxy import ToolProxy
    if not available_tools:
        return ToolProxy(get_tool_manager(), [])

    logger.info(f"初始化工具代理，可用工具: {available_tools}")

    if multi_agent and "complete_task" in available_tools:
        available_tools.remove("complete_task")

    tool_proxy = ToolProxy(get_tool_manager(), available_tools)
    return tool_proxy

def create_skill_proxy(available_skills: List[str]):
    from sagents.skill.skill_manager import get_skill_manager
    from sagents.skill.skill_proxy import SkillProxy
    if not available_skills:
        return SkillProxy(get_skill_manager(), [])

    logger.info(f"初始化技能代理，可用技能: {available_skills}")

    skill_proxy = SkillProxy(get_skill_manager(), available_skills)
    return skill_proxy

async def send_chunked_json(result: Dict[str, Any]) -> AsyncGenerator[str, None]:
    """发送分块JSON数据"""
    json_str = json.dumps(result, ensure_ascii=False)
    json_size = len(json_str)

    if json_size > 32768:
        chunk_size = 8192
        total_chunks = (json_size + chunk_size - 1) // chunk_size

        start_marker = {
            "type": "chunk_start",
            "message_id": result.get("message_id", "unknown"),
            "total_size": json_size,
            "total_chunks": total_chunks,
            "chunk_size": chunk_size,
            "original_type": result.get("type", "unknown"),
        }
        yield json.dumps(start_marker, ensure_ascii=False) + "\n"
        await asyncio.sleep(0.01)

        for i in range(total_chunks):
            start = i * chunk_size
            end = min(start + chunk_size, json_size)
            chunk_data = json_str[start:end]
            chunk_message = {
                "type": "json_chunk",
                "message_id": result.get("message_id", "unknown"),
                "chunk_id": f"{result.get('message_id', 'unknown')}_{i}",
                "chunk_index": i,
                "total_chunks": total_chunks,
                "chunk_data": chunk_data,
                "chunk_size": len(chunk_data),
                "is_final": i == total_chunks - 1,
                "checksum": hash(chunk_data) % 1000000,
            }
            yield json.dumps(chunk_message, ensure_ascii=False) + "\n"
            await asyncio.sleep(0.005)

        end_marker = {
            "type": "chunk_end",
            "message_id": result.get("message_id", "unknown"),
            "total_chunks": total_chunks,
            "total_size": json_size,
        }
        yield json.dumps(end_marker, ensure_ascii=False) + "\n"
    else:
        yield json.dumps(result, ensure_ascii=False) + "\n"

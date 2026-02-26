import asyncio
import json
import random
from typing import Any, AsyncGenerator, Dict, List, Tuple

from loguru import logger
from openai import AsyncOpenAI

def create_model_client(client_params: Dict[str, Any]) -> Any:
    api_key = client_params.get("api_key")
    base_url = client_params.get("base_url")
    if api_key and isinstance(api_key, str) and "," in api_key:
        keys = [k.strip() for k in api_key.split(",") if k.strip()]
        if keys:
            api_key = random.choice(keys)
            logger.info(f"Using random key from {len(keys)} available keys")
            
    logger.info(f"初始化Chat模型客户端: model={client_params.get('model')}, base_url={base_url}")
    model_client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
    )
    model_client.model = client_params.get("model")
    return model_client

def create_tool_proxy(available_tools: List[str]):
    from sagents.tool.tool_manager import get_tool_manager
    from sagents.tool.tool_proxy import ToolProxy
    if not available_tools:
        return ToolProxy(get_tool_manager(), [])
    logger.info(f"初始化工具代理，可用工具: {available_tools}")
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

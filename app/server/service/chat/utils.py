import asyncio
import json
from typing import Dict, Any, AsyncGenerator, List, Tuple
from loguru import logger
from openai import AsyncOpenAI
from core.config import StartupConfig
from core.client.chat import get_chat_client


def initialize_chat_resources(request_llm_config: dict, server_args: StartupConfig) -> Tuple[Any, Dict[str, Any]]:
    """初始化聊天相关资源（客户端和配置）
    
    统一处理配置清理、客户端创建和模型配置构建，优化业务逻辑流程。
    """
    # 1. 清理并提取配置
    # 移除空值，避免覆盖默认值
    raw_config = {k: v for k, v in (request_llm_config or {}).items() if v is not None and v != ""}
    
    # 2. 准备配置参数 (优先使用请求参数，否则使用系统默认)
    model_name = raw_config.get("model", server_args.default_llm_model_name)
    
    # 构建最终传给 Agent 的模型配置
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
        
    # 3. 初始化客户端
    # 如果没有自定义配置，直接使用全局默认客户端
    if not raw_config:
        logger.info("使用默认模型客户端")
        model_client = get_chat_client()
    else:
        # 有自定义配置（包括 model, apiKey, baseUrl 等），创建新客户端实例
        api_key = raw_config.get("apiKey", server_args.default_llm_api_key)
        base_url = raw_config.get("baseUrl", server_args.default_llm_api_base_url)
        
        logger.info(f"初始化自定义模型客户端: model={model_name}, base_url={base_url}")
        
        # 直接使用 AsyncOpenAI
        model_client = AsyncOpenAI(
            api_key=api_key, 
            base_url=base_url, 
        )
        model_client.model = model_name
        
    return model_client, final_model_config


def create_tool_proxy(available_tools: List[str], multi_agent: bool):
    from sagents.tool.tool_proxy import ToolProxy
    from sagents.tool.tool_manager import get_tool_manager
    if not available_tools:
        return ToolProxy(get_tool_manager(), [])

    logger.info(f"初始化工具代理，可用工具: {available_tools}")

    if multi_agent and "complete_task" in available_tools:
        available_tools.remove("complete_task")

    tool_proxy = ToolProxy(get_tool_manager(), available_tools)
    return tool_proxy

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

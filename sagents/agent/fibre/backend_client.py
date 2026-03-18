"""
Fibre Backend API Client

用于通过后端 API 管理子 Agent 和调用任务
"""
import os
import json
import uuid
from typing import Optional, Dict, Any, AsyncGenerator, List

from loguru import logger

from sagents.context.messages.message import MessageChunk


class FibreBackendClient:
    """后端 API 客户端"""

    def __init__(self):
        self.port = self._get_backend_port()
        self.base_url = f"http://127.0.0.1:{self.port}" if self.port else None
        self._available = self.port is not None

    def _get_backend_port(self) -> Optional[int]:
        """从环境变量获取后端端口"""
        port_env = os.environ.get("SAGE_PORT")
        if port_env:
            try:
                return int(port_env)
            except ValueError:
                logger.warning(f"Invalid SAGE_PORT: {port_env}")
        return None

    @property
    def available(self) -> bool:
        """检查后端是否可用"""
        return self._available

    async def check_health(self) -> bool:
        """检查后端服务是否健康"""
        if not self.available:
            return False
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}/active", timeout=5) as resp:
                    return resp.status == 200
        except Exception as e:
            logger.debug(f"Backend health check failed: {e}")
            return False

    # ========== Agent 管理 ==========

    async def create_agent(
        self,
        agent_id: str,
        name: str,
        system_prompt: str,
        description: str = "",
        available_tools: Optional[List[str]] = None,
        available_skills: Optional[List[str]] = None,
        available_workflows: Optional[Dict[str, List[str]]] = None,
        system_context: Optional[Dict[str, Any]] = None,
        available_sub_agent_ids: Optional[List[str]] = None,
        llm_provider_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        创建 Agent 到后端

        Args:
            user_id: User ID for the request (required)

        Returns:
            agent_id 如果成功，None 如果失败
        """
        if not self.available:
            return None

        payload = {
            "id": agent_id,
            "name": name or agent_id,
            "systemPrefix": system_prompt,
            "description": description,
            "availableTools": available_tools or [],
            "availableSkills": available_skills or [],
            "availableWorkflows": available_workflows or {},
            "systemContext": system_context or {},
            "availableSubAgentIds": available_sub_agent_ids or [],
            "memoryType": "session",
            "maxLoopCount": 100,
            "deepThinking": False,
            "llm_provider_id": llm_provider_id,
            "multiAgent": False,
            "agentMode": "fibre",
        }

        # Use provided user_id or fallback to a default
        headers_user_id = user_id if user_id else "unknown"
        
        logger.info(f"[Backend API] Creating agent: POST {self.base_url}/api/agent/create, payload: {json.dumps(payload, ensure_ascii=False)}")
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/api/agent/create",
                    json=payload,
                    headers={"X-Sage-Internal-UserId": headers_user_id},
                    timeout=30
                ) as resp:
                    resp_text = await resp.text()
                    logger.info(f"[Backend API] Create agent response: status={resp.status}, body={resp_text}")
                    if resp.status == 200:
                        data = json.loads(resp_text)
                        # Check success by "success" field or "code" field
                        is_success = data.get("success") or data.get("code") == 200
                        if is_success:
                            # 后端返回的 data 可能是对象或包含 agent_id 的字符串
                            resp_data = data.get("data")
                            if isinstance(resp_data, dict):
                                return resp_data.get("agent_id", agent_id)
                            elif isinstance(resp_data, str):
                                return resp_data
                            else:
                                return agent_id
                    logger.warning(f"Failed to create agent via backend: {resp_text}")
                    return None
        except Exception as e:
            logger.warning(f"Error creating agent via backend: {e}")
            return None

    async def get_agent(self, agent_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """获取 Agent 配置

        Args:
            agent_id: Agent ID
            user_id: User ID for the request (required)
        """
        if not self.available:
            return None

        headers_user_id = user_id if user_id else "unknown"
        
        logger.info(f"[Backend API] Getting agent: GET {self.base_url}/api/agent/{agent_id}")
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/api/agent/{agent_id}",
                    headers={"X-Sage-Internal-UserId": headers_user_id},
                    timeout=10
                ) as resp:
                    resp_text = await resp.text()
                    logger.debug(f"[Backend API] Get agent response: status={resp.status}, body={resp_text}")
                    if resp.status == 200:
                        data = json.loads(resp_text)
                        # Check success by "success" field or "code" field
                        is_success = data.get("success") or data.get("code") == 200
                        if is_success:
                            return data.get("data")
                    return None
        except Exception as e:
            logger.debug(f"Error getting agent: {e}")
            return None

    async def list_agents(self, user_id: Optional[str] = None) -> List[str]:
        """
        获取所有 Agent ID 列表

        Args:
            user_id: User ID for the request (required)

        Returns:
            List of agent IDs
        """
        if not self.available:
            return []

        headers_user_id = user_id if user_id else "unknown"

        logger.info(f"[Backend API] Listing agents: GET {self.base_url}/api/agent/list")
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/api/agent/list",
                    headers={"X-Sage-Internal-UserId": headers_user_id},
                    timeout=10
                ) as resp:
                    resp_text = await resp.text()
                    logger.info(f"[Backend API] List agents response: status={resp.status}, body={resp_text}")
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("success"):
                            agents_data = data.get("data", [])
                            return [agent.get("id") for agent in agents_data if agent.get("id")]
                    return []
        except Exception as e:
            logger.debug(f"Error listing agents: {e}")
            return []

    async def create_llm_provider(
        self,
        base_url: str,
        api_keys: List[str],
        model: str,
        name: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        创建 LLM Provider 并返回 provider ID

        Args:
            base_url: API base URL
            api_keys: API keys 列表
            model: 模型名称
            name: Provider 名称（可选）
            user_id: User ID for the request (required)

        Returns:
            provider_id 如果成功，None 如果失败
        """
        if not self.available:
            return None

        payload = {
            "base_url": base_url,
            "api_keys": api_keys,
            "model": model,
        }
        if name:
            payload["name"] = name

        headers_user_id = user_id if user_id else "unknown"

        logger.info(f"[Backend API] Creating LLM provider: POST {self.base_url}/api/llm-provider/create, payload: {json.dumps(payload, ensure_ascii=False)}")
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/api/llm-provider/create",
                    json=payload,
                    headers={"X-Sage-Internal-UserId": headers_user_id},
                    timeout=30
                ) as resp:
                    resp_text = await resp.text()
                    logger.info(f"[Backend API] Create LLM provider response: status={resp.status}, body={resp_text}")
                    if resp.status == 200:
                        data = json.loads(resp_text)
                        # Check success by "success" field or "code" field
                        is_success = data.get("success") or data.get("code") == 200
                        if is_success:
                            # 后端返回的 data 可能是对象或字符串
                            resp_data = data.get("data")
                            if isinstance(resp_data, dict):
                                return resp_data.get("provider_id")
                            elif isinstance(resp_data, str):
                                return resp_data
                    logger.warning(f"Failed to create LLM provider: {resp_text}")
                    return None
        except Exception as e:
            logger.warning(f"Error creating LLM provider: {e}")
            return None

    # ========== 任务执行 ==========

    async def stream_chat(
        self,
        agent_id: str,
        messages: List[Dict[str, str]],
        session_id: Optional[str] = None,
        system_context: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> AsyncGenerator[List[MessageChunk], None]:
        """
        流式执行 Agent 任务，解析 SSE 返回结构化数据并合并 chunks

        后端返回的是 MessageChunk 的流，我们需要将同一 message_id 的 chunks 合并成完整消息

        Args:
            user_id: User ID for the request (required)

        Yields:
            MessageChunk 对象列表（与 run_stream_with_flow 返回格式一致）
        """
        if not self.available:
            raise RuntimeError("Backend not available")

        payload = {
            "agent_id": agent_id,
            "messages": messages,
            "session_id": session_id,
            "system_context": system_context or {},
        }
        
        headers_user_id = user_id if user_id else "unknown"
        
        logger.info(f"[Backend API] Stream chat: POST {self.base_url}/api/chat, payload: {json.dumps(payload, ensure_ascii=False)}")

        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/api/chat",
                json=payload,
                headers={"X-Sage-Internal-UserId": headers_user_id},
                timeout=None
            ) as resp:
                logger.info(f"[Backend API] Stream chat response: status={resp.status}")
                # 用于缓存和合并 chunks
                pending_messages: Dict[str, Dict[str, Any]] = {}

                async for line in resp.content:
                    line = line.decode('utf-8').strip()
                    if not line:
                        continue

                    # 解析 SSE 数据
                    data = None
                    if line.startswith('data:'):
                        try:
                            data = json.loads(line[5:])  # 去掉 "data:" 前缀
                        except json.JSONDecodeError:
                            continue
                    else:
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                    if not data:
                        continue

                    # 获取 message_id，如果没有则生成一个临时 ID
                    message_id = data.get('message_id') or data.get('chunk_id') or str(uuid.uuid4())

                    # 跳过没有 role 字段的消息（如 stream_end 元数据消息）
                    if 'role' not in data:
                        continue

                    # 检查是否是新消息
                    if message_id not in pending_messages:
                        # 如果是完整消息（不是 chunk），直接 yield
                        if not data.get('is_chunk', False):
                            chunk = MessageChunk.from_dict(data)
                            yield [chunk]
                            continue

                        # 初始化 pending message
                        pending_messages[message_id] = {
                            'message_id': message_id,
                            'role': data.get('role', 'assistant'),
                            'content': data.get('content', '') or '',
                            'tool_calls': data.get('tool_calls', []),
                            'type': data.get('type'),
                            'session_id': data.get('session_id', session_id),
                            'agent_name': data.get('agent_name'),
                            'timestamp': data.get('timestamp'),
                            'metadata': data.get('metadata', {}),
                            'is_final': data.get('is_final', False),
                        }
                    else:
                        # 合并到已有消息
                        pending = pending_messages[message_id]

                        # 合并 content
                        if data.get('content'):
                            pending['content'] = (pending['content'] or '') + data['content']

                        # 合并 tool_calls（通常 tool_calls 是一次性的，不需要合并）
                        if data.get('tool_calls'):
                            pending['tool_calls'] = data['tool_calls']

                        # 更新其他字段
                        if data.get('type'):
                            pending['type'] = data['type']
                        if data.get('is_final'):
                            pending['is_final'] = True

                    # 检查是否是最终消息
                    if data.get('is_final', False) or not data.get('is_chunk', False):
                        if message_id in pending_messages:
                            msg_data = pending_messages.pop(message_id)
                            chunk = MessageChunk.from_dict(msg_data)
                            yield [chunk]

                # 流结束，yield 所有剩余的 pending messages
                for message in pending_messages.values():
                    chunk = MessageChunk.from_dict(message)
                    yield [chunk]

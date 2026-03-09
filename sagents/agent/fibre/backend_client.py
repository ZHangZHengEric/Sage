"""
Fibre Backend API Client

用于通过后端 API 管理子 Agent 和调用任务
"""
import os
import json
from typing import Optional, Dict, Any, AsyncGenerator, List

from loguru import logger


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
    ) -> Optional[str]:
        """
        创建 Agent 到后端

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

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/api/agent/create",
                    json=payload,
                    timeout=30
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("success"):
                            return data.get("data", {}).get("agent_id", agent_id)
                    logger.warning(f"Failed to create agent via backend: {await resp.text()}")
                    return None
        except Exception as e:
            logger.warning(f"Error creating agent via backend: {e}")
            return None

    async def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """获取 Agent 配置"""
        if not self.available:
            return None

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/api/agent/{agent_id}",
                    timeout=10
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("success"):
                            return data.get("data")
                    return None
        except Exception as e:
            logger.debug(f"Error getting agent: {e}")
            return None

    async def list_agents(self) -> List[str]:
        """
        获取所有 Agent ID 列表

        Returns:
            List of agent IDs
        """
        if not self.available:
            return []

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/api/agent/list",
                    timeout=10
                ) as resp:
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
        name: str,
        base_url: str,
        api_keys: List[str],
        model: str,
    ) -> Optional[str]:
        """
        创建 LLM Provider 并返回 provider ID

        Args:
            name: Provider 名称
            base_url: API base URL
            api_keys: API keys 列表
            model: 模型名称

        Returns:
            provider_id 如果成功，None 如果失败
        """
        if not self.available:
            return None

        payload = {
            "name": name,
            "base_url": base_url,
            "api_keys": api_keys,
            "model": model,
        }

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/api/llm-provider/create",
                    json=payload,
                    timeout=30
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("success"):
                            # 从响应中获取 provider_id
                            # 注意：后端返回的是 StandardResponse，data 中可能包含 provider 信息
                            # 需要查看实际的返回结构
                            return data.get("data", {}).get("id")
                    logger.warning(f"Failed to create LLM provider: {await resp.text()}")
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
        max_loop_count: int = 10,
        agent_mode: str = "simple",
        deep_thinking: bool = False,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式执行 Agent 任务，解析 SSE 返回结构化数据

        Yields:
            {
                "type": "content"|"tool_call"|"stream_end"|"error",
                "content": str,
                "tool_calls": List[Dict],
                "session_id": str,
                ...
            }
        """
        if not self.available:
            raise RuntimeError("Backend not available")

        payload = {
            "agent_id": agent_id,
            "messages": messages,
            "session_id": session_id,
            "system_context": system_context or {},
            "max_loop_count": max_loop_count,
            "agent_mode": agent_mode,
            "deep_thinking": deep_thinking,
        }

        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=None
            ) as resp:
                async for line in resp.content:
                    line = line.decode('utf-8').strip()
                    if line.startswith('data:'):
                        try:
                            data = json.loads(line[5:])  # 去掉 "data:" 前缀
                            yield data
                        except json.JSONDecodeError:
                            continue
                    elif line:
                        # 尝试直接解析（非标准 SSE 格式）
                        try:
                            data = json.loads(line)
                            yield data
                        except json.JSONDecodeError:
                            continue

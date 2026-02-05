import logging
from typing import Dict, Any
from sagents.context.session_context import SessionContext
from sagents.tool.tool_base import tool

logger = logging.getLogger(__name__)

class FibreTools:
    """
    System-level tools for Fibre Agents.
    """
    
    def __init__(self, orchestrator, session_context: SessionContext):
        self.orchestrator = orchestrator
        self.session_context = session_context

    @tool(
        description_i18n={"zh": "创建一个新的子智能体来处理特定任务。"},
        param_description_i18n={
            "agent_name": {"zh": "智能体的唯一标识符（例如 'sql_expert_1'）"},
            "role_description": {"zh": "智能体角色的简短摘要"},
            "system_instruction": {"zh": "定义智能体角色和约束的系统提示词"}
        }
    )
    async def sys_spawn_agent(self, agent_name: str, role_description: str, system_instruction: str) -> str:
        """
        Create a new sub-agent.
        
        Args:
            agent_name: Unique identifier for the agent (e.g., "sql_expert_1")
            role_description: Short summary of the agent's role
            system_instruction: The System Prompt defining the agent's persona and constraints
        """
        logger.info(f"Tool Call: sys_spawn_agent(name={agent_name}, role={role_description})")
        
        agent_id = await self.orchestrator.spawn_agent(
            parent_context=self.session_context,
            name=agent_name,
            role=role_description,
            instruction=system_instruction
        )
        return f"Agent spawned successfully. ID: {agent_id}. Ready to receive messages."

    @tool(
        description_i18n={"zh": "向已存在的子智能体发送消息。"},
        param_description_i18n={
            "agent_id": {"zh": "由 sys_spawn_agent 返回的智能体 ID"},
            "content": {"zh": "消息内容"}
        }
    )
    async def sys_send_message(self, agent_id: str, content: str) -> str:
        """
        Send a message to an existing sub-agent.

        Args:
            agent_id: The agent ID returned by sys_spawn_agent
            content: The message content
        """
        logger.info(f"Tool Call: sys_send_message(to={agent_id})")
        response = await self.orchestrator.send_message(agent_id, content)
        return response

    @tool(
        description_i18n={"zh": "向父节点报告最终结果。"},
        param_description_i18n={
            "status": {"zh": "任务状态 (success/failed)"},
            "result": {"zh": "最终结果的总结，包括执行结果和产生的资源"}
        }
    )
    async def sys_finish_task(self, status: str, result: str) -> str:
        """
        Report final result to parent.

        Args:
            status: Task status (success/failed)
            result: The final result, including execution process and any generated resources.
        """
        # This is typically called by the sub-agent, not the parent.
        # But if the parent calls it, it ends the main session?
        return f"Task finished: {status}. Result: {result}"


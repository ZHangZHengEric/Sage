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
            "system_prompt": {"zh": "定义智能体角色、能力要求和限制的系统提示词（不需要包含具体任务信息）"}
        }
    )
    async def sys_spawn_agent(self, agent_name: str, role_description: str, system_prompt: str) -> str:
        """
        Create a new sub-agent.
        
        Args:
            agent_name: Unique identifier for the agent (e.g., "sql_expert_1")
            role_description: Short summary of the agent's role
            system_prompt: The System Prompt defining the agent's persona, capabilities, and constraints
        """
        logger.info(f"Tool Call: sys_spawn_agent(name={agent_name}, role={role_description})")
        
        agent_id = await self.orchestrator.spawn_agent(
            parent_context=self.session_context,
            name=agent_name,
            role=role_description,
            system_prompt=system_prompt
        )
        return f"Agent spawned successfully. ID: {agent_id}. Ready to receive messages."

    @tool(
        description_i18n={"zh": "给子agent 分配任务并执行，支持并发执行多个子任务"},
        param_description_i18n={
            "tasks": {"zh": "任务列表，每个任务包含 'agent_id' 和 'content' 字段。'content' 必须包含详细的任务描述、具体要求以及期望的返回格式（明确指出需要 sys_finish_task 返回哪些字段）。例如：[{'agent_id': 'agent1', 'content': '请分析...并返回...'}, ...]"}
        }
    )
    async def sys_delegate_task(self, tasks: list[Dict[str, str]]) -> str:
        """
        Delegate tasks to existing sub-agents and wait for the results. Supports parallel execution.

        Args:
            tasks: A list of tasks, where each task is a dictionary containing 'agent_id' and 'content'.
                   'content' should be detailed and specify exactly what information needs to be returned via sys_finish_task.
        """
        logger.info(f"Tool Call: sys_delegate_task(tasks_count={len(tasks)})")
        response = await self.orchestrator.delegate_tasks(tasks)
        return response

    @tool(
        description_i18n={"zh": "向父节点报告最终结果。"},
        param_description_i18n={
            "status": {"zh": "任务状态 (success/failed)"},
            "result": {"zh": "最终结果的详细总结。必须包含父 Agent 所需的所有信息，包括执行过程的关键步骤、生成的资源路径、以及具体的分析结论。不要只返回简单的'完成'。"}
        }
    )
    async def sys_finish_task(self, status: str, result: str) -> str:
        """
        Report final result to parent.

        Args:
            status: Task status (success/failed)
            result: The detailed final result. Must include all information requested by the parent agent, 
                    including key execution steps, paths to generated resources, and specific conclusions.
        """
        # This is typically called by the sub-agent, not the parent.
        # But if the parent calls it, it ends the main session?
        return f"Task finished: {status}. Result: {result}"


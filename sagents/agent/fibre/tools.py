import logging
from typing import Dict, Any
from sagents.context.session_context import SessionContext
from sagents.tool.tool_base import tool

logger = logging.getLogger(__name__)

class FibreTools:
    """
    System-level tools for Fibre Agents.
    """
    
    @tool(
        description_i18n={"zh": "创建一个新的子智能体（专家角色）。注意：创建的必须是具备通用能力的领域专家（如'Python专家'），而不是针对当前具体任务的一次性执行者（如'贪吃蛇编写者'）。"},
        param_description_i18n={
            "agent_name": {"zh": "智能体的唯一标识符（建议使用通用角色名，如 'python_expert_1', 'data_analyst_1'）"},
            "description": {"zh": "智能体的职能描述。**必须**定义为一类通用的专业能力（如'Python编程专家'），**严禁**描述为具体的单一任务（如'写贪吃蛇代码'）。"},
            "system_prompt": {"zh": "智能体的详细系统设定（Persona）。为了确保子智能体表现出高水平的专业能力，**System Prompt 必须详尽且结构化，字数不得少于300字**。请严格按照以下结构编写：\n1. **角色定义**：清晰定义专家的身份、背景及核心职责（如'资深Python架构师，拥有10年分布式系统开发经验...'）。\n2. **能力范围**：列举其精通的技术栈、解决的问题类型及专业技能。\n3. **行为偏好**：规定其思维方式、代码风格（如'追求极致性能'、'遵循PEP8'）及沟通习惯。\n4. **限制与约束**：明确其不应做的事情及伦理边界。\n**注意**：System Prompt 仅用于定义角色属性，**严禁**包含具体的任务指令（如'写贪吃蛇'），具体任务请在 `sys_delegate_task` 中下发。"}
        }
    )
    async def sys_spawn_agent(self, agent_name: str, description: str, system_prompt: str, session_id: str = "") -> str:
        """
        Create a new sub-agent.
        
        Args:
            agent_name: Unique identifier for the agent (e.g., "sql_expert_1")
            description: Short summary of the agent's role (should describe a class of tasks)
            system_prompt: The System Prompt defining the agent's persona, capabilities, and constraints
            session_id: The current session ID (auto-injected)
        """
        logger.info(f"Tool Call: sys_spawn_agent(name={agent_name}, description={description})")
        
        from sagents.context.session_context import get_session_context
        session_context = get_session_context(session_id)
        if not session_context:
            return f"Error: Session context not found for session_id: {session_id}"
            
        orchestrator = getattr(session_context, "orchestrator", None)
        if not orchestrator:
             return "Error: Orchestrator not found in session context."

        agent_id = await orchestrator.spawn_agent(
            parent_context=session_context,
            name=agent_name,
            description=description,
            system_prompt=system_prompt
        )
        return f"Agent spawned successfully. ID: {agent_id}. Ready to receive messages."

    @tool(
        description_i18n={"zh": "给子agent 分配具体任务并执行，支持并发执行多个子任务。具体任务细节（如'写贪吃蛇'）应在这里通过 content 指定。"},
        param_description_i18n={
            "tasks": {"zh": "任务列表，每个任务包含 'agent_id' 和 'content' 字段。'content' 必须包含详细的具体任务描述、上下文信息、具体要求以及期望的返回格式。"}
        },
        param_schema={
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "agent_id": {
                            "type": "string",
                            "description": "The target agent ID to delegate the task to (e.g., 'python_expert_1').",
                            "description_i18n": {"zh": "目标子智能体ID（例如 'python_expert_1'）。"}
                        },
                        "content": {
                            "type": "string",
                            "description": "Detailed task description, context, requirements, and expected return format.",
                            "description_i18n": {"zh": "详细的任务描述、上下文信息、具体要求以及期望的返回格式。"}
                        }
                    },
                    "required": ["agent_id", "content"]
                }
            }
        }
    )
    async def sys_delegate_task(self, tasks: list[Dict[str, str]], session_id: str = "") -> str:
        """
        Delegate tasks to existing sub-agents and wait for the results. Supports parallel execution.

        Args:
            tasks: A list of tasks, where each task is a dictionary containing 'agent_id' and 'content'.
                   'content' should be detailed and specify exactly what information needs to be returned via sys_finish_task.
            session_id: The current session ID (auto-injected)
        """
        logger.info(f"Tool Call: sys_delegate_task(tasks_count={len(tasks)})")
        
        from sagents.context.session_context import get_session_context
        session_context = get_session_context(session_id)
        if not session_context:
            return f"Error: Session context not found for session_id: {session_id}"
            
        orchestrator = getattr(session_context, "orchestrator", None)
        if not orchestrator:
             return "Error: Orchestrator not found in session context."

        response = await orchestrator.delegate_tasks(tasks)
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

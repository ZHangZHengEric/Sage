import logging
from typing import Dict, Any, List
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
            "agent_id": {"zh": "智能体的唯一标识符（建议使用通用角色名，如 'python_expert_1', 'data_analyst_1'）"},
            "name": {"zh": "智能体的拟人化昵称（花名），例如，'乔巴'或'Eric'，用于显示和交互。请选择自然、亲切的人名风格，避免使用专业术语（如'Python专家'）。"},
            "description": {"zh": "智能体的职能描述。**必须**定义为一类通用的专业能力（如'Python编程专家'），**严禁**描述为具体的单一任务（如'写贪吃蛇代码'）。"},
            "system_prompt": {"zh": "智能体的详细系统设定（Persona）。为了确保子智能体表现出高水平的专业能力，**System Prompt 必须详尽且结构化，字数不得少于300字**。请严格按照以下结构编写：\n1. **角色定义**：清晰定义专家的身份、背景及核心职责（如'资深Python架构师，拥有10年分布式系统开发经验...'）。\n2. **能力范围**：列举其精通的技术栈、解决的问题类型及专业技能。\n3. **行为偏好**：规定其思维方式、代码风格（如'追求极致性能'、'遵循PEP8'）及沟通习惯。\n4. **限制与约束**：明确其不应做的事情及伦理边界。\n**注意**：System Prompt 仅用于定义角色属性，**严禁**包含具体的任务指令（如'写贪吃蛇'），具体任务请在 `sys_delegate_task` 中下发。"}
        }
    )
    async def sys_spawn_agent(self, agent_id: str, name: str, description: str, system_prompt: str, session_id: str = "") -> str:
        """
        Create a new sub-agent.

        Args:
            agent_id: Unique identifier for the agent (e.g., "sql_expert_1")
            name: Human-readable nickname (a warm, real-person name like "乔巴" or "Eric") for display. Must match the conversation language:
            description: Short summary of the agent's role (should describe a class of tasks)
            system_prompt: The System Prompt defining the agent's persona, capabilities, and constraints
            session_id: The current session ID (auto-injected)
        """
        logger.info(f"Tool Call: sys_spawn_agent(id={agent_id}, name={name}, description={description})")

        from sagents.context.session_context import get_session_context
        session_context = get_session_context(session_id)
        if not session_context:
            return f"Error: Session context not found for session_id: {session_id}"

        orchestrator = getattr(session_context, "orchestrator", None)
        if not orchestrator:
             return "Error: Orchestrator not found in session context."

        # New architecture: pass parent_session_id instead of parent_context
        new_agent_id = await orchestrator.spawn_agent(
            parent_session_id=session_id,
            agent_id=agent_id,
            name=name,
            description=description,
            system_prompt=system_prompt
        )
        return f"Agent spawned successfully. ID: {new_agent_id}. Ready to receive messages."

    @tool(
        description_i18n={"zh": "给子agent 分配具体任务并执行，支持并发执行多个子任务。具体任务细节（如'写贪吃蛇'）应在这里通过 content 指定。"},
        param_description_i18n={
            "tasks": {"zh": "任务列表，每个任务包含 'agent_id', 'content', 'session_id' 字段。其中 'session_id' 为必填项，用于明确指定上下文。'content' 必须包含详细的具体任务描述、上下文信息、具体要求以及期望的返回格式。"}
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
                        "task_name": {
                            "type": "string",
                            "description": "A unique identifier for the task (e.g., 'task_write_snake').",
                            "description_i18n": {"zh": "任务的唯一标识符（例如 'task_write_snake'）。用于后续查询任务状态或结果。"}
                        },
                        "original_task": {
                            "type": "string",
                            "description": "The original task description provided by the user.",
                            "description_i18n": {"zh": "最初的任务初衷，用于记录和跟踪任务的原始需求。"}
                        },
                        "content": {
                            "type": "string",
                            "description": "Detailed task description, context, requirements, and expected return format.",
                            "description_i18n": {"zh": "详细的子任务描述、上下文信息、具体要求以及期望的返回格式。"}
                        },
                        "session_id": {
                            "type": "string",
                            "description": "Specific session ID to reuse or create. If it's a new task, generate a new ID based on the agent name (e.g., 'session_python_expert_1_0').",
                            "description_i18n": {"zh": "必填：指定 Session ID。如果是新任务，请基于 agent_id 生成一个新的（例如 'session_python_expert_1_0'）；如果是继续之前的任务，请复用旧的 ID。不要使用当前的Session ID"}
                        }
                    },
                    "required": ["agent_id", "task_name", "original_task", "content", "session_id"]
                }
            }
        }
    )
    async def sys_delegate_task(self, tasks: List[Dict[str, str]], session_id: str = "") -> str:
        """
        Delegate tasks to existing sub-agents and wait for the results. Supports parallel execution.

        Args:
            tasks: A list of tasks, where each task is a dictionary containing 'agent_id', 'content', and 'session_id'.
                   'session_id' is required to explicitly manage conversation context.
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

        response = await orchestrator.delegate_tasks(tasks, caller_session_id=session_id)
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
        return f"Task finished: {status}. Result had been reported to parent agent."

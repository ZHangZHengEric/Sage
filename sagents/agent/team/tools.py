from typing import Dict, List

from sagents.tool.tool_base import tool
from sagents.utils.logger import logger


class TeamTools:
    """System-level tools for Team mode.

    Team mode intentionally exposes only delegation. Members complete work in
    their own normal mode; the orchestrator summarizes their trajectory.
    """

    @tool(
        description_i18n={
            "zh": "给已有 Team Member 分配具体任务并执行，tasks 列表中的任务会并发执行。Team 模式不允许创建新智能体，只能委派给当前可用的已有成员。",
            "en": "Assign concrete tasks to existing Team Members and execute them concurrently. Team mode cannot create new agents; it can only delegate to currently available members.",
        },
        param_description_i18n={
            "tasks": {
                "zh": "任务列表。每个任务必须包含 agent_id、task_name、original_task、content；session_id 可选，仅在继续已有子会话时填写。content 必须说明背景、目标、输入路径、输出路径、验收标准。所有路径必须使用绝对路径。",
                "en": "Task list. Each task must include agent_id, task_name, original_task, and content; session_id is optional and only for continuing an existing child session. content must describe context, goal, input paths, output paths, and acceptance criteria. All paths must be absolute.",
            }
        },
        param_schema={
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "agent_id": {"type": "string"},
                        "task_name": {"type": "string"},
                        "original_task": {"type": "string"},
                        "content": {"type": "string"},
                        "session_id": {"type": "string"},
                    },
                    "required": ["agent_id", "task_name", "original_task", "content"],
                },
            }
        },
    )
    async def sys_team_delegate_task(
        self, tasks: List[Dict[str, str]], session_id: str = ""
    ) -> str:
        logger.info(f"Tool Call: sys_team_delegate_task(tasks_count={len(tasks)})")

        from sagents.utils.agent_session_helper import get_live_session

        session = get_live_session(
            session_id, log_prefix="TeamTools.sys_team_delegate_task"
        )
        if not session:
            return f"Error: Session not found for session_id: {session_id}"
        session_context = session.session_context
        orchestrator = getattr(session_context, "orchestrator", None)
        if not orchestrator:
            return "Error: Team orchestrator not found in session context."

        response = await orchestrator.delegate_tasks(
            tasks, caller_session_id=session_id
        )
        return response

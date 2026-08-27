import asyncio
from types import SimpleNamespace

from sagents.context.messages.message import MessageChunk, MessageRole
from sagents.context.session_context import SessionContext
from sagents.skill.skill_tool import SkillTool


class _RecordingToolManager:
    def __init__(self):
        self.calls = []

    async def run_tool_async(self, **kwargs):
        self.calls.append(kwargs)


def test_recent_skill_loading_only_logs_summary_at_info(monkeypatch, tmp_path):
    info_messages = []
    debug_messages = []
    tool_manager = _RecordingToolManager()
    context = SessionContext(
        session_id="skill-log-session",
        user_id="user",
        agent_id="agent",
        session_root_space=str(tmp_path),
        tool_manager=tool_manager,
        skill_manager=object(),
    )
    context.message_manager.messages = [
        MessageChunk(
            role=MessageRole.USER.value,
            content="<skill>proactive-assistant</skill><skill>task-management</skill>",
        )
    ]

    monkeypatch.setattr(
        "sagents.context.session_context.logger.info", info_messages.append
    )
    monkeypatch.setattr(
        "sagents.context.session_context.logger.debug", debug_messages.append
    )

    asyncio.run(context.load_recent_skill_to_context())

    assert info_messages == [
        "SessionContext: Loading 2 skills: ['proactive-assistant', 'task-management']"
    ]
    assert debug_messages == [
        "SessionContext: Found skill tag: proactive-assistant",
        "SessionContext: Found skill tag: task-management",
        "SessionContext: Loading skill 'proactive-assistant' via ToolManager...",
        "SessionContext: Loading skill 'task-management' via ToolManager...",
    ]
    assert [call["skill_name"] for call in tool_manager.calls] == [
        "proactive-assistant",
        "task-management",
    ]


def test_active_skill_update_is_debug_only(monkeypatch):
    info_messages = []
    debug_messages = []
    context = SimpleNamespace(system_context={})

    monkeypatch.setattr("sagents.skill.skill_tool.logger.info", info_messages.append)
    monkeypatch.setattr("sagents.skill.skill_tool.logger.debug", debug_messages.append)

    SkillTool()._update_active_skills(context, "task-management", "instructions")

    assert info_messages == []
    assert debug_messages == [
        "Updated active_skills in session_context. Active skills: task-management"
    ]

from typing import Dict, Any
from sagents.tool.tool_base import tool
from sagents.utils.logger import logger

class SkillTool:
    """
    Skill Tool
    提供加载和管理技能的工具。
    """

    @tool(
        description_i18n={
            "zh": "加载指定技能的详细信息（说明文档、文件结构等）到当前会话中。",
            "en": "Load detailed information (instructions, file structure, etc.) of a specified skill into the current session."
        },
        param_description_i18n={
            "skill_name": {
                "zh": "要加载的技能名称",
                "en": "The name of the skill to load"
            }
        }
    )
    def load_skill(self, skill_name: str, session_id: str = None) -> str:
        """
        Load a skill into the current context.
        加载一个技能到当前上下文中。

        Args:
            skill_name: The name of the skill to load.
            session_id: The current session ID (injected by system).

        Returns:
            str: A message indicating the result of the operation.
        """
        if not session_id:
            raise ValueError("session_id is required for load_skill")

        from sagents.utils.agent_session_helper import get_live_session
        session = get_live_session(session_id, log_prefix="SkillTool")
        if not session or not session.session_context:
            raise ValueError(f"Invalid session_id: {session_id}")

        session_context = session.session_context

        # Use sandbox skill manager if available, otherwise raise error
        if hasattr(session_context, 'sandbox_skill_manager') and session_context.sandbox_skill_manager:
            skill_manager = session_context.sandbox_skill_manager
        else:
            raise ValueError("Sandbox skill manager not available")

        # 检查技能是否存在
        if skill_name not in skill_manager.skills:
            return f"Error: Skill '{skill_name}' not found. Available skills: {', '.join(skill_manager.list_skills())}"

        # 获取技能信息
        skill = skill_manager.skills[skill_name]

        # 获取沙箱虚拟路径（通过统一接口）
        sandbox_virtual_path = "/sage-workspace"  # 默认值
        if session_context and hasattr(session_context, 'sandbox') and session_context.sandbox:
            sandbox_virtual_path = session_context.sandbox.workspace_path

        # 构建技能内容
        result_content = [
            f"## Skill: {skill.name}",
            "",
            "### Skill Folder Path:",
            f"{sandbox_virtual_path}/skills/{skill.name}/",
            "",
            "### File Structure:",
            skill.file_list,
            "",
            "### Instructions (SKILL.md):",
            skill.instructions
        ]

        skill_content = "\n".join(result_content)

        # 更新 session_context 中的 active_skills
        if session_context:
            try:
                self._update_active_skills(session_context, skill.name, skill_content)
            except Exception as e:
                logger.error(f"Failed to update active_skills for skill '{skill_name}': {e}")

        # 返回简洁的成功消息
        active_skills = session_context.system_context.get('active_skills', []) if session_context else []
        skill_list = ", ".join([s.get('skill_name', 'Unknown') for s in active_skills])
        return f"Skill '{skill.name}' loaded successfully. Current Active skills: {skill_list}. Total skills: {len(active_skills)}. Please follow the instructions in the System Prompt."

    def _update_active_skills(self, session_context, skill_name: str, skill_content: str):
        """
        更新 session_context 中的 active_skills 列表
        """
        from sagents.context.messages.message_manager import MessageManager

        # Initialize active_skills list if not exists
        if 'active_skills' not in session_context.system_context:
            session_context.system_context['active_skills'] = []

        active_skills = session_context.system_context['active_skills']

        # Check if skill already exists, remove old entry
        active_skills = [s for s in active_skills if s.get('skill_name') != skill_name]

        # Add new skill to the end (newest)
        active_skills.append({
            'skill_name': skill_name,
            'skill_content': skill_content
        })

        # Limit total tokens to 8000, remove oldest if exceeded
        MAX_SKILL_TOKENS = 18000
        total_tokens = 0

        for skill in active_skills:
            content = skill.get('skill_content', '')
            tokens = MessageManager.calculate_str_token_length(content)
            total_tokens += tokens

        # Remove oldest skills if total exceeds limit, but keep at least one
        while total_tokens > MAX_SKILL_TOKENS and len(active_skills) > 1:
            removed_skill = active_skills.pop(0)
            removed_content = removed_skill.get('skill_content', '')
            removed_tokens = MessageManager.calculate_str_token_length(removed_content)
            total_tokens -= removed_tokens
            logger.info(f"Removed skill '{removed_skill.get('skill_name')}' due to token limit. Total tokens: {total_tokens}")

        session_context.system_context['active_skills'] = active_skills

        # Also update legacy field for backward compatibility
        all_instructions = "\n\n".join([
            f"=== {s.get('skill_name', 'Unknown')} ===\n{s.get('skill_content', '')}"
            for s in active_skills
        ])
        session_context.system_context['active_skill_instruction'] = all_instructions

        logger.info(f"Updated active_skills in session_context. Active skills: {', '.join([s.get('skill_name', 'Unknown') for s in active_skills])}")

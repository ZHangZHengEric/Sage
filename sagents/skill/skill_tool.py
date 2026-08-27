from sagents.tool.tool_base import tool
from sagents.utils.logger import logger
from sagents.utils.i18n import tool_t


class SkillTool:
    """
    Skill Tool
    提供加载和管理技能的工具。
    """

    @tool(
        description_i18n={
            "zh": "加载指定技能的详细信息（说明文档、文件结构等）到当前会话中。",
            "en": "Load detailed information (instructions, file structure, etc.) of a specified skill into the current session.",
        },
        param_description_i18n={
            "skill_name": {
                "zh": "要加载的技能名称",
                "en": "The name of the skill to load",
            }
        },
    )
    async def load_skill(self, skill_name: str, session_id: str = None) -> str:  # pyright: ignore[reportArgumentType]
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
            raise ValueError(tool_t("skill.error.session_required"))

        from sagents.utils.agent_session_helper import get_live_session

        session = get_live_session(session_id, log_prefix="SkillTool")
        if not session or not session.session_context:
            raise ValueError(
                tool_t("skill.error.invalid_session", params={"session_id": session_id})
            )

        session_context = session.session_context

        # Use sandbox skill manager if available, otherwise raise error
        if (
            hasattr(session_context, "sandbox_skill_manager")
            and session_context.sandbox_skill_manager
        ):
            skill_manager = session_context.sandbox_skill_manager
        else:
            raise ValueError(tool_t("skill.error.manager_unavailable"))

        # 懒加载：确保技能已落地到沙箱（首次调用会现拷），再读取其文件信息。
        # 未落地的系统技能不占用启动时间，只有真正 load 的才拷进工作区。
        ensure = getattr(skill_manager, "ensure_materialized", None)
        if callable(ensure):
            skill = await ensure(skill_name)
        else:
            # 兼容不支持懒加载的旧管理器
            skill = skill_manager.skills.get(skill_name)
        if skill is None:
            return tool_t(
                "skill.error.not_found",
                params={
                    "skill_name": skill_name,
                    "available": ", ".join(skill_manager.list_skills()),
                },
            )

        # 获取沙箱虚拟路径（通过统一接口）
        sandbox_virtual_path = "/sage-workspace"  # 默认值
        if (
            session_context
            and hasattr(session_context, "sandbox")
            and session_context.sandbox
        ):
            sandbox_virtual_path = session_context.sandbox.workspace_path

        # 构建技能内容
        result_content = [
            f"## {tool_t('skill.heading.skill')}: {skill.name}",
            "",
            f"### {tool_t('skill.heading.folder')}:",
            f"{sandbox_virtual_path}/skills/{skill.name}/",
            "",
            f"### {tool_t('skill.heading.files')}:",
            skill.file_list,
            "",
            f"### {tool_t('skill.heading.instructions')}:",
            skill.instructions,
        ]

        skill_content = "\n".join(result_content)

        # 更新 session_context 中的 active_skills
        if session_context:
            try:
                self._update_active_skills(session_context, skill.name, skill_content)
            except Exception as e:
                logger.error(
                    f"Failed to update active_skills for skill '{skill_name}': {e}"
                )

        # 返回简洁的成功消息
        active_skills = (
            session_context.system_context.get("active_skills", [])
            if session_context
            else []
        )
        unknown = tool_t("skill.unknown")
        skill_list = ", ".join([s.get("skill_name", unknown) for s in active_skills])
        return tool_t(
            "skill.success",
            params={
                "skill_name": skill.name,
                "active": skill_list,
                "total": len(active_skills),
            },
        )

    def _update_active_skills(
        self, session_context, skill_name: str, skill_content: str
    ):
        """
        更新 session_context 中的 active_skills 列表
        """
        from sagents.context.messages.message_manager import MessageManager

        # Initialize active_skills list if not exists
        if "active_skills" not in session_context.system_context:
            session_context.system_context["active_skills"] = []

        active_skills = session_context.system_context["active_skills"]

        # Check if skill already exists, remove old entry
        active_skills = [s for s in active_skills if s.get("skill_name") != skill_name]

        # Add new skill to the end (newest)
        active_skills.append({"skill_name": skill_name, "skill_content": skill_content})

        # Limit total tokens to 8000, remove oldest if exceeded
        MAX_SKILL_TOKENS = 18000
        total_tokens = 0

        for skill in active_skills:
            content = skill.get("skill_content", "")
            tokens = MessageManager.calculate_str_token_length(content)
            total_tokens += tokens

        # Remove oldest skills if total exceeds limit, but keep at least one
        while total_tokens > MAX_SKILL_TOKENS and len(active_skills) > 1:
            removed_skill = active_skills.pop(0)
            removed_content = removed_skill.get("skill_content", "")
            removed_tokens = MessageManager.calculate_str_token_length(removed_content)
            total_tokens -= removed_tokens
            logger.info(
                f"Removed skill '{removed_skill.get('skill_name')}' due to token limit. Total tokens: {total_tokens}"
            )

        session_context.system_context["active_skills"] = active_skills

        # Also update legacy field for backward compatibility
        all_instructions = "\n\n".join(
            [
                f"=== {s.get('skill_name', tool_t('skill.unknown'))} ===\n{s.get('skill_content', '')}"
                for s in active_skills
            ]
        )
        session_context.system_context["active_skill_instruction"] = all_instructions

        logger.debug(
            f"Updated active_skills in session_context. Active skills: {', '.join([s.get('skill_name', 'Unknown') for s in active_skills])}"
        )

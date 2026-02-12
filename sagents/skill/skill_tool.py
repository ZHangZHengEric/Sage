from typing import Dict, Any
from sagents.tool.tool_base import tool
from sagents.skill.skill_manager import get_skill_manager
from sagents.utils.logger import logger

from sagents.utils.sandbox.filesystem import SANDBOX_WORKSPACE_ROOT

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
        skill_manager = None
        
        if session_id:
            try:
                # Use local import to avoid circular dependency
                from sagents.context.session_context import get_session_context
                session_context = get_session_context(session_id)
                if session_context and session_context.skill_manager:
                    skill_manager = session_context.skill_manager
            except Exception as e:
                logger.warning(f"Failed to get skill manager from session context for {session_id}: {e}")
        
        # Fallback to default getter if not found in session
        if not skill_manager:
            logger.warning(f"Using default get_skill_manager() for skill loading. Session ID: {session_id}")
            skill_manager = get_skill_manager()

        if not skill_manager:
            return "Error: SkillManager not initialized."
            
        # 检查技能是否存在
        if skill_name not in skill_manager.skills:
            return f"Error: Skill '{skill_name}' not found. Available skills: {', '.join(skill_manager.list_skills())}"
            
        # 获取技能信息
        skill = skill_manager.skills[skill_name]
        
        # 构建返回信息
        # 这里返回的信息会被作为工具执行结果，最终可能会被添加到系统上下文中（取决于调用者的处理方式）
        # 但根据用户需求，这个工具的主要目的是"加载"，即返回内容给Agent看，Agent再根据内容决定如何行动
        # 或者系统自动将这些内容注入到 System Prompt 中？
        # 用户说："只返回成功加载skill，并添加到系统指令。" -> 这通常意味着我们需要某种机制来修改 System Prompt
        # 但在 Tool 执行上下文中，Tool 很难直接修改 System Prompt。
        # 通常的做法是 Tool 返回详细信息，这些信息作为 Tool Output 进入 History，Agent 就能看到了。
        # 用户提到的 "添加到系统指令" 可能是指在 Tool Output 中包含 "System Notification: Skill Loaded..." 
        # 或者是在 Agent 框架层面有机制去监听 Tool Call 并更新 System Prompt。
        # 鉴于 Agent 框架的通常实现，Tool Output 本身就是 Context 的一部分。
        # 所以我们把 SKILL.md 的内容和文件树作为 Tool Output 返回即可。
        
        result = [
            f"## Skill: {skill.name}",
            "",
            "### Skill Folder Path:",
            f"{SANDBOX_WORKSPACE_ROOT}/skills/{skill.name}/",
            "",
            "### File Structure:",
            skill.file_list,
            "",
            "### Instructions (SKILL.md):",
            skill.instructions
        ]
        
        return "\n".join(result)

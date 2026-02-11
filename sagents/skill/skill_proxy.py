from typing import Any, Dict, List, Optional, Union

from sagents.utils.logger import logger
from sagents.skill.skill_manager import SkillManager
from sagents.skill.skill_schema import SkillSchema

class SkillProxy:
    """
    SkillProxy (技能代理类)
    
    Acts as a secure proxy for SkillManager, exposing only a subset of available skills.
    作为 SkillManager 的安全代理，仅暴露可用的技能子集。
    
    Compatible with all skill-related interfaces of SkillManager.
    兼容 SkillManager 的所有技能相关接口。
    """

    def __init__(
        self,
        skill_manager: "SkillManager",
        available_skills: Optional[List[str]] = None,
    ):
        """
        Initialize the SkillProxy.
        初始化技能代理。

        Args:
            skill_manager: The global SkillManager instance. (全局技能管理器实例)
            available_skills: List of skill names allowed to be accessed. (允许访问的技能名称列表)
                              If None, all skills are available. (如果为 None，则所有技能可用)
        """
        self.skill_manager = skill_manager
        if available_skills is None:
            self._available_skills = set(self.skill_manager.list_skills())
        else:
            self._available_skills = set(available_skills)
            all_skills = set(self.skill_manager.list_skills())
            invalid_skills = self._available_skills - all_skills
            if invalid_skills:
                logger.warning(f"SkillProxy: The following skills do not exist (以下技能不存在): {invalid_skills}")
                self._available_skills -= invalid_skills

    def _check_skill_available(self, skill_name: str) -> None:
        """
        Verify if a skill is available in this proxy.
        验证技能是否在此代理中可用。
        """
        if skill_name not in self._available_skills:
            raise ValueError(f"Skill '{skill_name}' is not in the available skills list (技能 '{skill_name}' 不在可用技能列表中)")

    @property
    def skill_dirs(self) -> List[str]:
        return self.skill_manager.skill_dirs

    @property
    def skills(self) -> Dict[str, SkillSchema]:
        """
        Get a dictionary of available skills.
        获取可用技能的字典。
        """
        return {
            name: self.skill_manager.skills[name]
            for name in self.list_skills()
            if name in self.skill_manager.skills
        }

    def list_skills(self) -> List[str]:
        """
        List names of available skills.
        列出可用技能的名称。
        """
        return [name for name in self.skill_manager.list_skills() if name in self._available_skills]

    def list_skill_info(self) -> List[SkillSchema]:
        """
        List detailed information for available skills.
        列出可用技能的详细信息。
        """
        return [
            skill for skill in self.skill_manager.list_skill_info()
            if skill.name in self._available_skills
        ]

    def get_skill_description_lines(
        self,
    ) -> List[str]:
        """
        Get formatted description lines for available skills.
        获取可用技能的格式化描述行。
        """
        skill_names = self.list_skills()
        filtered = [name for name in skill_names if name in self._available_skills]
        return self.skill_manager.get_skill_description_lines(filtered)



    def get_skill_metadata(self, name: str) -> Optional[Dict[str, Any]]:
        self._check_skill_available(name)
        return self.skill_manager.get_skill_metadata(name)

    def get_skill_instructions(self, name: str) -> str:
        self._check_skill_available(name)
        return self.skill_manager.get_skill_instructions(name)

    def get_skill_resource_path(self, name: str, resource_name: str, agent_workspace: Optional[str] = None) -> Optional[str]:
        self._check_skill_available(name)
        return self.skill_manager.get_skill_resource_path(name, resource_name, agent_workspace)

    def prepare_skill_in_workspace(self, skill_name: str, agent_workspace: str) -> Optional[str]:
        self._check_skill_available(skill_name)
        return self.skill_manager.prepare_skill_in_workspace(skill_name, agent_workspace)

    def get_skill_file_list(self, name: str, agent_workspace: Optional[str] = None) -> List[str]:
        self._check_skill_available(name)
        return self.skill_manager.get_skill_file_list(name, agent_workspace)

    def prepare_skills_in_workspace(self, agent_workspace: str) -> None:
        """
        Copy all available skills to the agent's workspace.
        将所有可用的技能复制到智能体的工作区。
        """
        for skill_name in self.list_skills():
            self.prepare_skill_in_workspace(skill_name, agent_workspace)

    def list_skill_info(self) -> List[Dict[str, Any]]:
        """
        List detailed information for available skills.
        列出所有可用技能的详细信息。
        """
        return [
            self.skill_manager.skills[name] 
            for name in self.list_skills() 
            if name in self.skill_manager.skills
        ]

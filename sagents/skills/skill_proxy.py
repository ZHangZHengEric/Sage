from typing import Any, Dict, List, Optional, Union

from sagents.utils.logger import logger
from sagents.skills.skill_manager import SkillManager
from sagents.skills.schema import SkillSchema

class SkillProxy:
    """
    技能代理类

    作为 SkillManager 的代理，只暴露指定的技能子集。
    兼容 SkillManager 的所有技能相关接口。
    """

    def __init__(
        self,
        skill_manager: "SkillManager",
        available_skills: Optional[List[str]] = None,
    ):
        """
        初始化技能代理

        Args:
            skill_manager: 全局技能管理器实例
            available_skills: 可用技能名称列表
        """
        self.skill_manager = skill_manager
        if available_skills is None:
            self._available_skills = set(self.skill_manager.list_skills())
        else:
            self._available_skills = set(available_skills)
            all_skills = set(self.skill_manager.list_skills())
            invalid_skills = self._available_skills - all_skills
            if invalid_skills:
                logger.warning(f"SkillProxy: 以下技能不存在: {invalid_skills}")
                self._available_skills -= invalid_skills

    def _check_skill_available(self, skill_name: str) -> None:
        if skill_name not in self._available_skills:
            raise ValueError(f"技能 '{skill_name}' 不在可用技能列表中")

    @property
    def skill_dirs(self) -> List[str]:
        return self.skill_manager.skill_dirs

    @property
    def skills(self) -> Dict[str, SkillSchema]:
        return {
            name: self.skill_manager.skills[name]
            for name in self.list_skills()
            if name in self.skill_manager.skills
        }

    def list_skills(self) -> List[str]:
        return [name for name in self.skill_manager.list_skills() if name in self._available_skills]

    def get_skill_description_lines(
        self,
    ) -> List[str]:
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

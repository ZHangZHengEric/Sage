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
        skill_managers: Union["SkillManager", "SkillProxy", List[Union["SkillManager", "SkillProxy"]]],
        available_skills: Optional[List[str]] = None,
    ):
        """
        Initialize the SkillProxy.
        初始化技能代理。

        Args:
            skill_managers: The SkillManager or SkillProxy instance or a list of them.
                            If a list is provided, the first manager in the list has the highest priority.
                            (技能管理器/代理实例或列表。如果提供列表，列表中的第一个管理器具有最高优先级。)
            available_skills: List of skill names allowed to be accessed from the initial managers.
                              (允许访问的初始管理器中的技能名称列表。)
                              If None, all skills from initial managers are available.
                              (如果为 None，则初始管理器的所有技能可用。)
        """
        if isinstance(skill_managers, list):
            self.skill_managers = skill_managers
        else:
            self.skill_managers = [skill_managers]
            
        # Backward compatibility attribute (point to the highest priority one)
        self.skill_manager = self.skill_managers[0] if self.skill_managers else None

        if available_skills is None:
            self._available_skills = set()
            for sm in self.skill_managers:
                self._available_skills.update(sm.list_skills())
            self._is_all_skills_mode = True
        else:
            self._available_skills = set(available_skills)
            self._is_all_skills_mode = False
            
            # Validate against current managers
            all_skills = set()
            for sm in self.skill_managers:
                all_skills.update(sm.list_skills())
                
            invalid_skills = self._available_skills - all_skills
            if invalid_skills:
                logger.warning(f"SkillProxy: The following skills do not exist (以下技能不存在): {invalid_skills}")
                self._available_skills -= invalid_skills

    def add_skill_manager(self, skill_manager: Union["SkillManager", "SkillProxy"]) -> None:
        """
        Add a skill manager (or proxy) to the proxy with highest priority.
        All skills from this new manager will be automatically available.
        
        Args:
            skill_manager: The skill manager or proxy to add.
        """
        self.skill_managers.insert(0, skill_manager)
        self.skill_manager = self.skill_managers[0] # Update primary reference
        
        # Add all skills from the new manager to available skills
        new_skills = skill_manager.list_skills()
        self._available_skills.update(new_skills)
        logger.info(f"SkillProxy: Added new skill manager with skills: {new_skills}")

    def load_new_skills(self) -> None:
        """
        Load new skills from disk for all managers without reloading existing ones.
        """
        for sm in self.skill_managers:
            sm.load_new_skills()

        if self._is_all_skills_mode:
            # Re-fetch all skills from all managers
            self._available_skills = set()
            for sm in self.skill_managers:
                self._available_skills.update(sm.list_skills())

    def _check_skill_available(self, skill_name: str) -> None:
        """
        Verify if a skill is available in this proxy.
        验证技能是否在此代理中可用。
        """
        if skill_name not in self._available_skills:
            raise ValueError(f"Skill '{skill_name}' is not in the available skills list (技能 '{skill_name}' 不在可用技能列表中)")
        
        # Check if any manager actually has it (it might have been deleted)
        found = False
        for sm in self.skill_managers:
            if skill_name in sm.skills:
                found = True
                break
        if not found:
             # It might be in _available_skills but not in any manager (e.g. deleted file but no reload)
             # or logic error.
             # But let's trust _available_skills for permission check, 
             # and let actual retrieval fail if missing.
             pass

    @property
    def skill_dirs(self) -> List[str]:
        dirs = []
        for sm in self.skill_managers:
            dirs.extend(sm.skill_dirs)
        return list(set(dirs)) # dedup

    @property
    def skills(self) -> Dict[str, SkillSchema]:
        """
        Get a dictionary of available skills.
        获取可用技能的字典。
        """
        # Merge skills from all managers, higher priority overwrites lower
        merged_skills = {}
        # Iterate reversed so high priority (index 0) overwrites low priority
        for sm in reversed(self.skill_managers):
            for name, skill in sm.skills.items():
                if name in self._available_skills:
                    merged_skills[name] = skill
        return merged_skills

    def list_skills(self) -> List[str]:
        """
        List names of available skills.
        列出可用技能的名称。
        """
        return list(self.skills.keys())

    def list_skill_info(self) -> List[SkillSchema]:
        """
        List detailed information for available skills.
        列出可用技能的详细信息。
        """
        return list(self.skills.values())

    def get_skill_description_lines(
        self,
        skill_names: Optional[List[str]] = None 
    ) -> List[str]:
        """
        Get formatted description lines for available skills.
        获取可用技能的格式化描述行。
        """
        if skill_names is None:
            target_skills = self.skills.values()
        else:
            all_skills = self.skills
            target_skills = [all_skills[name] for name in skill_names if name in all_skills]
            
        lines = []
        for skill in target_skills:
            lines.append(f"- skill name: {skill.name}, description: {skill.description}")
        return lines

    def get_skill_metadata(self, name: str) -> Optional[Dict[str, Any]]:
        self._check_skill_available(name)
        for sm in self.skill_managers:
            if name in sm.skills:
                return sm.get_skill_metadata(name)
        return None

    def get_skill_instructions(self, name: str) -> str:
        self._check_skill_available(name)
        for sm in self.skill_managers:
            if name in sm.skills:
                return sm.get_skill_instructions(name)
        raise ValueError(f"Skill {name} not found in any manager")

    def get_skill_resource_path(self, name: str, resource_name: str, agent_workspace: Optional[str] = None) -> Optional[str]:
        self._check_skill_available(name)
        for sm in self.skill_managers:
            if name in sm.skills:
                return sm.get_skill_resource_path(name, resource_name, agent_workspace)
        return None

    def prepare_skill_in_workspace(self, skill_name: str, agent_workspace: str) -> Optional[str]:
        self._check_skill_available(skill_name)
        for sm in self.skill_managers:
            if skill_name in sm.skills:
                return sm.prepare_skill_in_workspace(skill_name, agent_workspace)
        return None

    def get_skill_file_list(self, name: str, agent_workspace: Optional[str] = None) -> List[str]:
        self._check_skill_available(name)
        for sm in self.skill_managers:
            if name in sm.skills:
                return sm.get_skill_file_list(name, agent_workspace)
        return []

    def prepare_skills_in_workspace(self, agent_workspace: str) -> None:
        """
        Copy all available skills to the agent's workspace.
        将所有可用的技能复制到智能体的工作区。
        """
        for skill_name in self.list_skills():
            self.prepare_skill_in_workspace(skill_name, agent_workspace)


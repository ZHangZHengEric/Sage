from typing import Any, Dict, List, Optional, Union
import os
import json
import yaml
import shutil

from sagents.utils.logger import logger
from sagents.skills.schema import SkillSchema

_GLOBAL_SKILL_MANAGER: Optional["SkillManager"] = None


def get_skill_manager() -> Optional["SkillManager"]:
    return _GLOBAL_SKILL_MANAGER


def set_skill_manager(tm: Optional["SkillManager"]) -> None:
    global _GLOBAL_SKILL_MANAGER
    _GLOBAL_SKILL_MANAGER = tm

class SkillManager:
    """
    Manages the discovery, registration, and loading of skills.
    """
    def __init__(self, skill_dirs: List[str] = None):
        self.skills: Dict[str, SkillSchema] = {}
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.skill_workspace = os.path.join(base_dir, "skill_workspace")
        self.skill_dirs = list(dict.fromkeys((skill_dirs or []) + [self.skill_workspace]))
        self._load_skills_from_workspace()

    @classmethod
    def get_instance(cls) -> "SkillManager":
        tm = get_skill_manager()
        if tm is None:
            tm = SkillManager()
            set_skill_manager(tm)
        return tm

    def list_skills(self) -> List[str]:
        return list(self.skills.keys())

    def get_skill_description_lines(self, skills: Optional[List[str]] = None) -> List[str]:
        if skills is None:
            skill_names = self.list_skills()
        elif isinstance(skills, list):
            skill_names = skills
        lines = []
        for name in skill_names:
            metadata = self.get_skill_metadata(name)
            if not metadata:
                continue
            lines.append(f"- {metadata['name']}: {metadata['description']}")
        return lines

    def _load_skills_from_workspace(self):
        self.skills.clear()
        if not os.path.exists(self.skill_workspace):
            return
        for item in os.listdir(self.skill_workspace):
            skill_path = os.path.join(self.skill_workspace, item)
            if os.path.isdir(skill_path):
                self._load_skill_from_dir(skill_path)

    def _generate_file_tree(self, path: str, root_path: Optional[str] = None, prefix: str = "") -> str:
        if root_path is None:
            root_path = path
            
        lines = []
        try:
            items = sorted(os.listdir(path))
        except OSError:
            return ""
            
        # Filter items
        items = [i for i in items if not i.startswith('.') and i != 'SKILL.md']
        
        for item in items:
            full_path = os.path.join(path, item)
            
            if os.path.isdir(full_path):
                lines.append(f"{prefix}- {item}/")
                lines.append(self._generate_file_tree(full_path, root_path, prefix + "  "))
            else:
                lines.append(f"{prefix}- {item}")
                
        return "\n".join(lines)

    def _validate_skill_metadata(self, metadata: Dict[str, Any], skill_path: str) -> bool:
        name = metadata.get("name")
        description = metadata.get("description")
        if not name or not description:
            logger.warning(f"SkillManager: {skill_path} SKILL.md 缺少必要的元数据 (name, description)")
            return False
        return True

    def _load_skill_from_dir(self, skill_path: str):
        """
        Load a skill from a directory.
        """
        skill_md_path = os.path.join(skill_path, "SKILL.md")
        if os.path.exists(skill_md_path):
            try:
                with open(skill_md_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Parse frontmatter
                metadata = {}
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        yaml_content = parts[1]
                        metadata = yaml.safe_load(yaml_content)
                
                # Validation for Claude Code Skills format
                # Must have name, description
                if not self._validate_skill_metadata(metadata, skill_path):
                    return
                name = metadata.get("name")
                description = metadata.get("description", "")
                
                if name:
                    file_list = self._generate_file_tree(skill_path)
                    schema = SkillSchema(
                        name=name,
                        description=description,
                        path=skill_path,
                        instructions=content,
                        file_list=file_list, 
                    )
                    self.skills[name] = schema
                    logger.info(f"SkillManager: 已加载技能: {name}")
                    logger.debug(f"SkillManager: 技能 {name} 元数据: {metadata}")
                    return
            except Exception as e:
                logger.error(f"SkillManager: 从 {skill_path} 加载 SKILL.md 失败: {e}")

    def get_skill_metadata(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Level 1: Get skill metadata (name, description, etc.)
        """
        skill = self.skills.get(name)
        if skill:
            return {
                "name": skill.name,
                "description": skill.description,
                "path": skill.path
            }
        return None

    def get_skill_instructions(self, name: str) -> str:
        """
        Level 2: Get skill instructions (SKILL.md content).
        """
        skill = self.skills.get(name)
        return skill.instructions or ""

    def prepare_skill_in_workspace(self, skill_name: str, agent_workspace: str) -> Optional[str]:
        """
        Copy skill to agent workspace for execution.
        Returns the new absolute path of the skill directory in the workspace.
        """
        skill = self.skills.get(skill_name)
        if not skill:
            return None
        
        # Target path: workspace/skills/<skill_name>
        target_dir = os.path.join(agent_workspace, "skills", skill_name)
        
        # Always copy to ensure fresh state or update if needed
        # Using dirs_exist_ok=True to allow overwriting/merging
        try:
            if not os.path.exists(target_dir):
                shutil.copytree(skill.path, target_dir, dirs_exist_ok=True, symlinks=False)
                logger.debug(f"Copied skill {skill_name} to workspace: {target_dir}")
            else:
                 pass
        except Exception as e:
            logger.error(f"Failed to copy skill {skill_name} to workspace: {e}")
            return None
            
        return target_dir

    def get_skill_resource_path(self, name: str, resource_name: str, agent_workspace: Optional[str] = None) -> Optional[str]:
        """
        Level 3: Get path to a skill resource (e.g., scripts/fill_form.py).
        If agent_workspace is provided, returns path relative to workspace copy.
        """
        skill = self.skills.get(name)
        if skill:
            base_path = skill.path
            
            if agent_workspace:
                # Ensure agent_workspace is absolute
                agent_workspace = os.path.abspath(agent_workspace)
                workspace_path = self.prepare_skill_in_workspace(name, agent_workspace)
                if workspace_path:
                    base_path = workspace_path

            normalized_resource_name = resource_name.replace("\\", "/")
            if normalized_resource_name.startswith("skills/"):
                normalized_resource_name = normalized_resource_name[len("skills/"):]
            if normalized_resource_name.startswith(f"{name}/"):
                normalized_resource_name = normalized_resource_name[len(f"{name}/"):]

            # If resource_name is already absolute, os.path.join will use it directly
            resource_path = os.path.join(base_path, normalized_resource_name)
            if os.path.exists(resource_path):
                return resource_path
        return None

from typing import Any, Dict, List, Optional, Union
import os
import json
import yaml
import shutil

from sagents.utils.logger import logger
from sagents.skill.skill_schema import SkillSchema

_GLOBAL_SKILL_MANAGER: Optional["SkillManager"] = None


def get_skill_manager() -> Optional["SkillManager"]:
    return _GLOBAL_SKILL_MANAGER


def set_skill_manager(tm: Optional["SkillManager"]) -> None:
    global _GLOBAL_SKILL_MANAGER
    _GLOBAL_SKILL_MANAGER = tm

class SkillManager:
    """
    SkillManager (技能管理器)
    Manages the discovery, registration, and loading of skills.
    负责技能的发现、注册和加载。

    Core Responsibilities (核心职责):
    1. Discovery (发现): Scans the 'skills' directory for valid skill packages. (扫描 'skills' 目录以查找有效的技能包)
    2. Registration (注册): Validates and registers skills into memory. (验证并将技能注册到内存中)
    3. Loading (加载): Loads skill metadata and instructions (SKILL.md). (加载技能元数据和说明)
    4. Workspace Preparation (工作区准备): Copies skill files to the agent's workspace for execution. (将技能文件复制到智能体的工作区以供执行)
    """
    def __init__(self, skill_dirs: List[str] = None):
        logger.info("Initializing SkillManager")
        self.skills: Dict[str, SkillSchema] = {}
        # Base directory resolution (基础目录解析)
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.skill_workspace = os.path.join(base_dir, "skills")
        # Combine custom directories with the default workspace (合并自定义目录和默认工作区)
        self.skill_dirs = list(dict.fromkeys((skill_dirs or []) + [self.skill_workspace]))
        self._load_skills_from_workspace()

    @classmethod
    def get_instance(cls) -> "SkillManager":
        """
        Get the global singleton instance of SkillManager.
        获取 SkillManager 的全局单例实例。
        """
        tm = get_skill_manager()
        if tm is None:
            tm = SkillManager()
            set_skill_manager(tm)
        return tm

    def list_skills(self) -> List[str]:
        """
        List all registered skill names.
        列出所有已注册的技能名称。
        """
        return list(self.skills.keys())

    def list_skill_info(self) -> List[SkillSchema]:
        """
        List detailed information for all skills.
        列出所有技能的详细信息。
        """
        return  list(self.skills.values())

    def get_skill_description_lines(self, skills: Optional[List[str]] = None) -> List[str]:
        """
        Get a list of formatted description lines for skills.
        获取技能的格式化描述行列表。
        
        Format: "- {name}: {description}"
        """
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

    def get_skill_metadata(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get metadata for a specific skill.
        获取指定技能的元数据。
        """
        if name in self.skills:
            skill = self.skills[name]
            return {
                "name": skill.name,
                "description": skill.description
            }
        return None

    def get_skill_instructions(self, name: str) -> str:
        """
        Get instructions for a specific skill.
        获取指定技能的说明。
        """
        if name in self.skills:
            return self.skills[name].instructions
        return ""

    def get_skill_resource_path(self, name: str, resource_name: str, agent_workspace: Optional[str] = None) -> Optional[str]:
        """
        Get the path to a resource file within a skill.
        获取技能中资源文件的路径。
        """
        if name not in self.skills:
            return None
            
        skill_path = self.skills[name].path
        resource_path = os.path.join(skill_path, resource_name)
        
        if os.path.exists(resource_path):
            return resource_path
        return None


    def _load_skills_from_workspace(self):
        """
        Internal method to scan and load skills from all configured skill directories.
        内部方法：扫描并加载所有配置的技能目录中的技能。
        """
        self.skills.clear()

        # Iterate over all configured skill directories
        for workspace in self.skill_dirs:
            if not os.path.exists(workspace):
                logger.warning(f"Skill workspace directory not found: {workspace}")
                continue

            logger.info(f"Scanning skill workspace: {workspace}")
            try:
                for item in os.listdir(workspace):
                    skill_path = os.path.join(workspace, item)
                    if os.path.isdir(skill_path):
                        # Avoid duplicates if multiple workspaces have same skill name?
                        # Current logic: Last loaded overwrites previous if names collide.
                        self._load_skill_from_dir(skill_path)
            except Exception as e:
                logger.error(f"Error scanning workspace {workspace}: {e}")

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

    def _load_skill_from_dir(self, skill_path: str) -> Optional[str]:
        """
        Load a skill from a directory.
        Returns skill name if successful, None otherwise.
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
                    return None
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
                    logger.info(f"Successfully registered new skill: {name}")
                    return name
            except Exception as e:
                logger.error(f"Failed to load skill from {skill_path}: {e}")
        return None

    def register_new_skill(self, skill_dir_name: str) -> Optional[str]:
        """
        Validate and register a new skill located in the skill workspace.
        If validation fails, the directory will be removed.
        
        Args:
            skill_dir_name: The directory name of the skill in the workspace
            
        Returns:
            Optional[str]: The skill name if successful, None otherwise
        """
        skill_path = os.path.join(self.skill_workspace, skill_dir_name)
        if not os.path.exists(skill_path):
            logger.error(f"Skill directory not found: {skill_path}")
            return None

        skill_name = self._load_skill_from_dir(skill_path)
        if skill_name:
            return skill_name
        else:
            # Validation failed, remove the directory
            try:
                shutil.rmtree(skill_path)
                logger.warning(f"Removed invalid skill directory: {skill_path}")
            except Exception as e:
                logger.error(f"Failed to remove invalid skill directory {skill_path}: {e}")
            return None

    def reload_skill(self, skill_path: str) -> bool:
        """
        Reload an existing skill from the workspace.
        Does NOT delete the directory if validation fails.
        
        Args:
            skill_dir_name: The directory name of the skill in the workspace
            
        Returns:
            bool: True if successful, False otherwise
        """

        skill_name = self._load_skill_from_dir(skill_path)
        return skill_name is not None

    def remove_skill(self, skill_name: str) -> None:
        """
        Remove a skill from the manager (memory only).
        """
        if skill_name in self.skills:
            del self.skills[skill_name]
            logger.info(f"Removed skill from manager: {skill_name}")

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

    def prepare_skills_in_workspace(self, agent_workspace: str) -> None:
        """
        Copy all registered skills to the agent's workspace.
        将所有已注册的技能复制到智能体的工作区。
        """
        for skill_name in self.skills:
            self.prepare_skill_in_workspace(skill_name, agent_workspace)

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

    def get_skill_file_list(self, name: str, agent_workspace: Optional[str] = None) -> List[str]:
        """
        Get a list of relative paths for all files in the skill.
        e.g., ["scripts/script.py", "data/config.json"]
        """
        skill = self.skills.get(name)
        if not skill:
            return []

        base_path = skill.path
        if agent_workspace:
            # Ensure agent_workspace is absolute
            agent_workspace = os.path.abspath(agent_workspace)
            workspace_path = self.prepare_skill_in_workspace(name, agent_workspace)
            if workspace_path:
                base_path = workspace_path

        file_list = []
        if os.path.exists(base_path):
            for root, _, files in os.walk(base_path):
                for file in files:
                    if file.startswith('.') or file == 'SKILL.md':
                        continue
                    abs_path = os.path.join(root, file)
                    rel_path = os.path.relpath(abs_path, base_path)
                    # Normalize to forward slashes
                    rel_path = rel_path.replace("\\", "/")
                    file_list.append(rel_path)
        return sorted(file_list)

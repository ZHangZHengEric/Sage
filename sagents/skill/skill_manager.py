from typing import Any, Dict, List, Optional, Union
import os
import json
import yaml
import shutil

from sagents.utils.logger import logger
from sagents.skill.skill_schema import SkillSchema


_GLOBAL_SKILL_MANAGER: Optional["SkillManager"] = None


def get_skill_manager() -> Optional["SkillManager"]:
    return SkillManager()


def set_skill_manager(tm: Optional["SkillManager"]) -> None:
    SkillManager._instance = tm


class SkillManager:
    """
    SkillManager (技能管理器)
    Manages the discovery, registration, and loading of skills on the HOST machine.
    负责在宿主机上管理技能的发现、注册和加载。

    Core Responsibilities (核心职责):
    1. Discovery (发现): Scans the 'skills' directory on host for valid skill packages.
                       (扫描宿主机上的 'skills' 目录以查找有效的技能包)
    2. Registration (注册): Validates and registers skills into memory.
                          (验证并将技能注册到内存中)
    3. Loading (加载): Loads skill metadata and instructions (SKILL.md).
                      (加载技能元数据和说明)

    Note: This class only manages skills on the HOST. Copying skills to sandbox
    is handled by SessionContext via the sandbox interface.
    (注意：此类只管理宿主机上的技能。将技能复制到沙箱由 SessionContext 通过沙箱接口处理。)
    """
    _instance = None

    def __new__(cls, skill_dirs: List[str] = None, isolated: bool = False):
        if isolated:
            return super(SkillManager, cls).__new__(cls)
        if cls._instance is None:
            cls._instance = super(SkillManager, cls).__new__(cls)
        return cls._instance

    def __init__(self, skill_dirs: List[str] = None, isolated: bool = False):
        if not isolated and getattr(self, '_initialized', False):
            return

        self._initialize(skill_dirs)
        self._initialized = True

    def add_skill_dir(self, path: str):
        """
        Add a new directory to scan for skills.
        添加一个新的技能扫描目录。
        """
        if path not in self.skill_dirs:
            self.skill_dirs.append(path)
            # Invalidate cache when adding new directory (添加新目录时使缓存失效)
            self._skills_cache_valid = False
            self.reload()

    def _initialize(self, skill_dirs: List[str] = None):
        logger.debug("Initializing SkillManager")
        self.skills: Dict[str, SkillSchema] = {}
        # Base directory resolution (基础目录解析)
        
        # Combine custom directories with the default workspace (合并自定义目录和默认工作区)
        dirs = skill_dirs or []
             
        self.skill_dirs = list(dict.fromkeys(dirs))
        # Flag to track if skills cache is valid (标志：跟踪技能缓存是否有效)
        self._skills_cache_valid = False
        self._load_skills_from_workspace()

    @classmethod
    def get_instance(cls) -> "SkillManager":
        """
        Get the global singleton instance of SkillManager.
        获取 SkillManager 的全局单例实例。
        """
        return cls()

    def reload(self):
        """
        Reload all skills from disk.
        从磁盘重新加载所有技能。
        """
        logger.debug("Reloading skills...")
        # Invalidate cache before reloading (重新加载前使缓存失效)
        self._skills_cache_valid = False
        self._load_skills_from_workspace()

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
            lines.append(f"- skill name: {metadata['name']}, description: {metadata['description']}")
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

    def get_skill_resource_path(self, name: str, resource_name: str) -> Optional[str]:
        """
        Get the path to a resource file within a skill on the HOST.
        获取宿主机上技能中资源文件的路径。

        Note: This returns the path on the HOST machine, not in sandbox.
        (注意：这返回宿主机上的路径，不是沙箱内的路径。)
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
        self.load_new_skills()

    def load_new_skills(self):
        """
        Load new skills from disk without reloading existing ones.
        If skills cache is valid, skip scanning and return immediately.
        """
        # Check if cache is valid, if so, skip scanning (检查缓存是否有效，如果有效则跳过扫描)
        # 除了要判断 _skills_cache_valid 是否有效，还得看一下目录中的文件夹数量与已加载 skill 数量是否一致
        if getattr(self, '_skills_cache_valid', False):
            # 快速统计所有 skill_dirs 下的文件夹总数
            total_dirs = 0
            for workspace in self.skill_dirs:
                if not os.path.exists(workspace):
                    continue
                try:
                    total_dirs += sum(
                        1 for item in os.listdir(workspace)
                        if os.path.isdir(os.path.join(workspace, item))
                    )
                except Exception:
                    pass
            # 如果文件夹总数与已加载技能数量不一致，则视为缓存失效
            if total_dirs != len(self.skills):
                logger.debug("Skills cache invalid: folder count != loaded skill count")
                self._skills_cache_valid = False
            else:
                logger.debug("Skills cache is valid, skipping load_new_skills scan")
                return
        
        count = 0
        
        # Build a set of existing skill paths for fast lookup
        existing_paths = {skill.path for skill in self.skills.values()}
        
        # Iterate over all configured skill directories
        for workspace in self.skill_dirs:
            if not os.path.exists(workspace):
                logger.warning(f"Skill workspace directory not found: {workspace}")
                continue

            logger.debug(f"Scanning skill workspace: {workspace}")
            try:
                for item in os.listdir(workspace):
                    skill_path = os.path.join(workspace, item)
                    if os.path.isdir(skill_path):
                        # Skip if path is already loaded
                        if skill_path in existing_paths:
                            continue
                            
                        # Avoid duplicates if multiple workspaces have same skill name?
                        # Current logic: Last loaded overwrites previous if names collide.
                        name = self._load_skill_from_dir(skill_path, skip_if_loaded=True)
                        if name:
                            count += 1
                
            except Exception as e:
                logger.error(f"Error scanning workspace {workspace}: {e}")
        logger.debug(f"Total skills loaded/checked: {count}")
        
        # Mark cache as valid after successful loading (加载成功后标记缓存为有效)
        self._skills_cache_valid = True


    def _generate_file_list(self, path: str, root_path: str, skill_name: str, indent: str = "") -> str:
        """
        Generate a compact tree representation of skill files using indentation.
        Similar to get_file_tree_compact in filesystem.py.

        Args:
            path: Current directory path being traversed
            root_path: Root path of the skill (for calculating relative paths)
            skill_name: Name of the skill (for display)
            indent: Current indentation level (2 spaces per level)

        Returns:
            String with indented file tree structure

        Example output:
        my_skill/
          README.md
          src/
            main.py
          config.json
        """
        lines = []
        try:
            items = sorted(os.listdir(path))
        except OSError:
            return ""

        # 需要过滤掉的缓存/临时文件夹和文件
        excluded_names = {
            '__pycache__', '.pytest_cache', '.mypy_cache', '.tox', '.egg-info',
            '.git', '.svn', '.hg', '.DS_Store', 'node_modules', 'dist', 'build',
            '.idea', '.vscode', '.vs', '*.pyc', '*.pyo', '*.pyd', '.coverage',
            '.nyc_output', '.cache', 'venv', '.venv', 'env', '.env'
        }

        # Filter items
        items = [i for i in items if not i.startswith('.') and i not in excluded_names]

        for item in items:
            full_path = os.path.join(path, item)

            if os.path.isdir(full_path):
                # Directory: add with / suffix and recurse
                lines.append(f"{indent}  {item}/")
                lines.append(self._generate_file_list(full_path, root_path, skill_name, indent + "  "))
            else:
                # File: add without suffix
                lines.append(f"{indent}  {item}")

        return "\n".join(filter(None, lines))

    def _validate_skill_metadata(self, metadata: Dict[str, Any], skill_path: str) -> bool:
        name = metadata.get("name")
        description = metadata.get("description")
        if not name or not description:
            logger.warning(f"SkillManager: {skill_path} SKILL.md 缺少必要的元数据 (name, description)")
            return False
        return True

    def _load_skill_from_dir(self, skill_path: str, skip_if_loaded: bool = False) -> Optional[str]:
        """
        Load a skill from a directory on the HOST.
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
                    if skip_if_loaded and name in self.skills:
                        return name

                    # Generate compact file tree with skill name as root
                    file_list = f"{name}/\n" + self._generate_file_list(skill_path, skill_path, name)
                    schema = SkillSchema(
                        name=name,
                        description=description,
                        path=skill_path,
                        instructions=content,
                        file_list=file_list, 
                    )
                    self.skills[name] = schema
                    logger.debug(f"Successfully registered new skill: {name}")
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
            # Invalidate cache when registering new skill (注册新技能时使缓存失效)
            self._skills_cache_valid = False
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
        # Invalidate cache when reloading skill (重新加载技能时使缓存失效)
        self._skills_cache_valid = False
        skill_name = self._load_skill_from_dir(skill_path)
        return skill_name is not None

    def remove_skill(self, skill_name: str) -> None:
        """
        Remove a skill from the manager (memory only).
        """
        if skill_name in self.skills:
            del self.skills[skill_name]
            # Invalidate cache when removing skill (移除技能时使缓存失效)
            self._skills_cache_valid = False
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

    def get_skill_file_list(self, name: str) -> List[str]:
        """
        Get a list of relative paths for all files in the skill.
        e.g., ["scripts/script.py", "data/config.json"]
        
        Returns relative paths from the skill root directory.
        To get the sandbox path, use: {sandbox.workspace_path}/skills/{skill_name}/{relative_path}
        
        (返回相对于技能根目录的相对路径。要获取沙箱路径，使用: {sandbox.workspace_path}/skills/{skill_name}/{relative_path})
        """
        skill = self.skills.get(name)
        if not skill:
            return []

        base_path = skill.path
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

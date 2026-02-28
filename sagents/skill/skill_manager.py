from typing import Any, Dict, List, Optional, Union
import os
import json
import yaml
import shutil

from sagents.utils.logger import logger
from sagents.skill.skill_schema import SkillSchema
from sagents.utils.sandbox.filesystem import SANDBOX_WORKSPACE_ROOT

_GLOBAL_SKILL_MANAGER: Optional["SkillManager"] = None


def get_skill_manager() -> Optional["SkillManager"]:
    return SkillManager()


def set_skill_manager(tm: Optional["SkillManager"]) -> None:
    SkillManager._instance = tm


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
    _instance = None

    def __new__(cls, skill_dirs: List[str] = None, isolated: bool = False, include_global_skills: bool = True):
        if isolated:
            return super(SkillManager, cls).__new__(cls)
        if cls._instance is None:
            cls._instance = super(SkillManager, cls).__new__(cls)
        return cls._instance

    def __init__(self, skill_dirs: List[str] = None, isolated: bool = False, include_global_skills: bool = True):
        if not isolated and getattr(self, '_initialized', False):
            return

        self._initialize(skill_dirs, include_global_skills)
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

    def _initialize(self, skill_dirs: List[str] = None, include_global_skills: bool = True):
        logger.debug("Initializing SkillManager")
        self.skills: Dict[str, SkillSchema] = {}
        # Base directory resolution (基础目录解析)
        self.skill_workspace = os.environ.get("SAGE_SKILL_WORKSPACE", "skills")
        
        # Combine custom directories with the default workspace (合并自定义目录和默认工作区)
        dirs = skill_dirs or []
        if include_global_skills:
             dirs.append(self.skill_workspace)
             
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
        logger.info("Reloading skills...")
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


    def _generate_file_list(self, path: str, root_path: str, skill_name: str) -> str:
        lines = []
        try:
            items = sorted(os.listdir(path))
        except OSError:
            return ""

        # Filter items
        items = [i for i in items if not i.startswith('.')]

        for item in items:
            full_path = os.path.join(path, item)
            rel_path = os.path.relpath(full_path, root_path)
            rel_path = rel_path.replace(os.sep, '/')
            
            # Construct workspace path
            # Use os.path.join for construction, then normalize to posix path
            # But SANDBOX_WORKSPACE_ROOT is usually unix-style. 
            # We assume SANDBOX_WORKSPACE_ROOT is like "/workspace"
            
            display_path = f"{SANDBOX_WORKSPACE_ROOT}/skills/{skill_name}/{rel_path}".replace('//', '/')

            if os.path.isdir(full_path):
                lines.append(f"{display_path}/")
                lines.append(self._generate_file_list(full_path, root_path, skill_name))
            else:
                lines.append(display_path)

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
                    if skip_if_loaded and name in self.skills:
                        return name

                    file_list = self._generate_file_list(skill_path, skill_path, name)
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
        except shutil.Error as e:
            # 处理部分复制成功但部分文件失败的情况
            errors = e.args[0] if e.args else []
            copied_files = []
            failed_files = []
            
            for src, dst, err in errors:
                if 'socket' in str(err).lower() or 'lock' in str(err).lower():
                    # 忽略 socket 和 lock 文件错误
                    logger.debug(f"Skipped socket/lock file: {src}")
                    continue
                failed_files.append((src, dst, err))
            
            # 如果有非 socket/lock 错误，重新抛出
            if failed_files:
                logger.warning(f"部分文件复制失败: {failed_files}")
                # 继续返回目标目录，部分文件应该已经复制成功
                
            logger.debug(f"Copied skill {skill_name} to workspace: {target_dir}")
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

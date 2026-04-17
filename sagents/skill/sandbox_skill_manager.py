"""
沙箱内技能管理器

通过沙箱接口管理沙箱内的技能，与宿主机的 SkillManager 分离。
运行时按宿主 SkillProxy / SkillManager 给出的技能名称，**优先**从沙箱内
``<sandbox_agent_workspace>/skills/<name>/`` 读取 SKILL.md；
仅当沙箱里这个技能目录缺失时，才把 host_skill.path 一次性拷过来再加载，
保证 Agent 工作区里手动改过的 SKILL.md 不会被无脑覆盖。
"""
import os
from typing import Any, Dict, List, Optional
import yaml

from sagents.utils.logger import logger
from sagents.skill.skill_schema import SkillSchema


class SandboxSkillManager:
    """
    沙箱内技能管理器
    
    管理沙箱内的技能，通过沙箱文件系统接口操作。
    与宿主机的 SkillManager 分离，支持在沙箱内修改技能。
    """
    
    def __init__(self, sandbox, skills_dir: str = "/sage-workspace/skills"):
        """
        初始化沙箱技能管理器
        
        Args:
            sandbox: ISandboxHandle 实例
            skills_dir: 沙箱内技能目录路径（虚拟路径）
        """
        self.sandbox = sandbox
        self.skills_dir = skills_dir
        self._skills_cache: Dict[str, SkillSchema] = {}
        self._cache_valid = False
    
    async def _read_file(self, path: str) -> str:
        """通过沙箱接口读取文件"""
        return await self.sandbox.read_file(path)
    
    async def _file_exists(self, path: str) -> bool:
        """通过沙箱接口检查文件是否存在"""
        return await self.sandbox.file_exists(path)
    
    async def _list_directory(self, path: str) -> List[Any]:
        """通过沙箱接口列出目录"""
        return await self.sandbox.list_directory(path)
    
    async def load_skills(self) -> None:
        """
        扫描沙箱 skills 目录下的全部子目录并加载（不筛选名称）。
        会话初始化请优先使用 sync_from_host，以便与宿主可用技能列表对齐。
        """
        self._skills_cache.clear()

        try:
            if not await self._file_exists(self.skills_dir):
                logger.debug(f"沙箱技能目录不存在: {self.skills_dir}")
                return

            entries = await self._list_directory(self.skills_dir)

            for entry in entries:
                if entry.is_dir:
                    skill_name = os.path.basename(entry.path)
                    skill = await self._load_skill_from_dir(entry.path)
                    if skill:
                        self._skills_cache[skill_name] = skill

            self._cache_valid = True
            logger.debug(f"从沙箱加载了 {len(self._skills_cache)} 个技能")

        except Exception as e:
            logger.error(f"从沙箱加载技能失败: {e}")
    
    async def _load_skill_from_dir(self, skill_path: str) -> Optional[SkillSchema]:
        """
        从沙箱内的目录加载技能
        
        Args:
            skill_path: 沙箱内的技能路径（虚拟路径）
        """
        skill_md_path = os.path.join(skill_path, "SKILL.md")
        
        try:
            if not await self._file_exists(skill_md_path):
                return None
            
            # 读取 SKILL.md
            content = await self._read_file(skill_md_path)
            
            # 解析 frontmatter
            metadata = {}
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    yaml_content = parts[1]
                    metadata = yaml.safe_load(yaml_content)
            
            # 验证必要字段
            name = metadata.get("name")
            description = metadata.get("description", "")
            
            if not name:
                logger.warning(f"沙箱技能缺少名称: {skill_path}")
                return None
            
            # 生成文件列表
            file_list = await self._generate_file_list(skill_path)
            
            return SkillSchema(
                name=name,
                description=description,
                path=skill_path,  # 沙箱内的虚拟路径
                instructions=content,
                file_list=file_list,
            )
            
        except Exception as e:
            logger.error(f"从沙箱加载技能失败 {skill_path}: {e}")
            return None
    
    async def _generate_file_list(self, path: str, indent: str = "") -> str:
        """生成文件树列表"""
        lines = []
        
        try:
            entries = await self._list_directory(path)
            # 过滤隐藏文件和缓存
            entries = [e for e in entries 
                      if not os.path.basename(e.path).startswith('.') 
                      and os.path.basename(e.path) not in ['__pycache__', 'node_modules']]
            
            # 排序：目录在前，文件在后
            entries.sort(key=lambda e: (not e.is_dir, os.path.basename(e.path)))
            
            for entry in entries:
                name = os.path.basename(entry.path)
                if entry.is_dir:
                    lines.append(f"{indent}  {name}/")
                    sub_list = await self._generate_file_list(entry.path, indent + "  ")
                    if sub_list:
                        lines.append(sub_list)
                else:
                    lines.append(f"{indent}  {name}")
                    
        except Exception as e:
            logger.debug(f"生成文件列表失败 {path}: {e}")
        
        return "\n".join(filter(None, lines))
    
    def list_skills(self) -> List[str]:
        """列出所有技能名称"""
        return list(self._skills_cache.keys())
    
    def get_skill(self, name: str) -> Optional[SkillSchema]:
        """获取技能"""
        return self._skills_cache.get(name)
    
    @property
    def skills(self) -> Dict[str, SkillSchema]:
        """获取所有技能字典"""
        return self._skills_cache.copy()

    def get_skill_metadata(self, name: str) -> Optional[Dict[str, Any]]:
        skill = self._skills_cache.get(name)
        if not skill:
            return None
        return {"name": skill.name, "description": skill.description, "path": skill.path}

    def get_skill_description_lines(
        self, skill_names: Optional[List[str]] = None
    ) -> List[str]:
        """与 SkillManager 相同格式，供任务分析等复用。"""
        names = skill_names if skill_names is not None else self.list_skills()
        lines: List[str] = []
        for name in names:
            meta = self.get_skill_metadata(name)
            if meta:
                lines.append(
                    f"- skill name: {meta['name']}, description: {meta['description']}"
                )
        return lines

    def list_skill_info(self) -> List[SkillSchema]:
        """与 SkillManager.list_skill_info 对齐，供 system prompt 等使用。"""
        return list(self._skills_cache.values())

    async def sync_from_host(self, host_skill_manager) -> None:
        """
        按宿主 SkillProxy / SkillManager 给出的技能名称对齐沙箱内技能：

        1. 沙箱 ``skills_dir/<name>/SKILL.md`` 已存在 → 直接以沙箱内容为准加载
           （保留用户在 Agent workspace 里的手改）。
        2. 沙箱里没有该技能目录，但宿主有对应 SkillSchema.path → 一次性
           ``copy_from_host`` 拷到沙箱后再加载（按需补齐，不覆盖已有）。
        3. 宿主也没有 → 记 warning 跳过。

        Args:
            host_skill_manager: 宿主侧 SkillManager / SkillProxy
        """
        self._skills_cache.clear()
        allowed_names = list(host_skill_manager.list_skills())
        if not allowed_names:
            logger.debug("沙箱技能：宿主未声明可用技能，跳过加载")
            return

        # 沙箱根目录不存在时主动建一次（首次会话场景）
        if not await self._file_exists(self.skills_dir):
            try:
                ensure_dir = getattr(self.sandbox, "ensure_directory", None)
                if callable(ensure_dir):
                    await ensure_dir(self.skills_dir)
                    logger.info(f"沙箱技能目录已创建: {self.skills_dir}")
                else:
                    logger.warning(
                        f"沙箱技能目录不存在且无法创建（缺少 ensure_directory）: {self.skills_dir}"
                    )
                    return
            except Exception as e:
                logger.warning(f"沙箱技能目录创建失败 {self.skills_dir}: {e}")
                return

        host_skills = getattr(host_skill_manager, "skills", {}) or {}

        for skill_name in allowed_names:
            skill_path = os.path.join(self.skills_dir, skill_name)
            skill_md_path = os.path.join(skill_path, "SKILL.md")

            # 1) 沙箱已存在 → 直接加载，不动手
            if await self._file_exists(skill_md_path):
                skill = await self._load_skill_from_dir(skill_path)
                if skill:
                    self._skills_cache[skill_name] = skill
                    continue
                # SKILL.md 存在但解析失败：不再覆盖，只记 warning
                logger.warning(
                    f"沙箱已存在 SKILL.md 但解析失败，保留现状: {skill_md_path}"
                )
                continue

            # 2) 沙箱缺失 → 尝试从宿主 SkillSchema.path 一次性拷贝
            host_skill = host_skills.get(skill_name)
            host_path = getattr(host_skill, "path", None) if host_skill else None
            if host_path and os.path.isdir(host_path):
                try:
                    # 各 provider 返回值不统一（local/remote 返回 bool，passthrough
                    # 不返回），用 SKILL.md 是否落地作为最终判定依据。
                    await self.sandbox.copy_from_host(host_path, skill_path)
                except Exception as e:
                    logger.warning(
                        f"沙箱补齐技能失败 {skill_name}: {host_path} -> {skill_path}: {e}"
                    )
                    continue
                if not await self._file_exists(skill_md_path):
                    logger.warning(
                        f"沙箱补齐后未发现 SKILL.md: {skill_md_path}"
                    )
                    continue
                logger.info(
                    f"沙箱技能补齐: {skill_name} ({host_path} -> {skill_path})"
                )
                skill = await self._load_skill_from_dir(skill_path)
                if skill:
                    self._skills_cache[skill_name] = skill
                else:
                    logger.warning(
                        f"沙箱技能补齐后仍无法加载 SKILL.md: {skill_path}"
                    )
                continue

            # 3) 宿主也没有该技能
            logger.warning(
                f"沙箱与宿主均未提供技能 '{skill_name}'，跳过"
            )

        logger.debug(
            f"沙箱技能已就绪: {list(self._skills_cache.keys())}"
        )

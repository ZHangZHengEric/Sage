"""
沙箱内技能管理器

通过沙箱接口管理沙箱内的技能，与宿主机的 SkillManager 分离。
运行时按宿主 SkillProxy / SkillManager 给出的技能名称，**优先**从沙箱内
``<sandbox_agent_workspace>/skills/<name>/`` 读取 SKILL.md；
仅当沙箱里这个技能目录缺失时，才把 host_skill.path 一次性拷过来再加载，
保证 Agent 工作区里手动改过的 SKILL.md 不会被无脑覆盖。
"""

import asyncio
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
        # 已落地：已拷进沙箱并从沙箱 SKILL.md 完整加载的技能（含沙箱路径/文件树）。
        self._skills_cache: Dict[str, SkillSchema] = {}
        # 已知：宿主声明可用、但尚未落地到沙箱的技能元数据（name/description，
        # path 为宿主源路径，供 load 时按需拷贝）。用于向模型广告全部技能，
        # 而不必在会话初始化时把每个技能都拷进（PVC 场景下很慢的）用户工作区。
        self._known_skills: Dict[str, SkillSchema] = {}
        # 每技能落地锁：串行化"同一技能"的按需拷贝，避免并行 load_skill 竞态。
        self._materialize_locks: Dict[str, asyncio.Lock] = {}
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
            entries = [
                e
                for e in entries
                if not os.path.basename(e.path).startswith(".")
                and os.path.basename(e.path) not in ["__pycache__", "node_modules"]
            ]

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

    def _merged_skills(self) -> Dict[str, SkillSchema]:
        """已知 ∪ 已落地，已落地（沙箱视图）优先。"""
        merged = dict(self._known_skills)
        merged.update(self._skills_cache)
        return merged

    def list_skills(self) -> List[str]:
        """列出所有技能名称（已落地 + 已知未落地）"""
        return sorted(set(self._known_skills) | set(self._skills_cache))

    def get_skill(self, name: str) -> Optional[SkillSchema]:
        """获取技能（已落地优先，否则返回已知元数据）"""
        return self._skills_cache.get(name) or self._known_skills.get(name)

    @property
    def skills(self) -> Dict[str, SkillSchema]:
        """获取所有技能字典（已知 ∪ 已落地）"""
        return self._merged_skills()

    def get_skill_metadata(self, name: str) -> Optional[Dict[str, Any]]:
        skill = self._skills_cache.get(name) or self._known_skills.get(name)
        if not skill:
            return None
        return {
            "name": skill.name,
            "description": skill.description,
            "path": skill.path,
        }

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
        """与 SkillManager.list_skill_info 对齐，供 system prompt 等使用。
        返回已知 ∪ 已落地（已落地优先），保证广告到全部可用技能。"""
        return list(self._merged_skills().values())

    async def sync_from_host(self, host_skill_manager) -> None:
        """
        按宿主 SkillProxy / SkillManager 给出的可用技能对齐沙箱技能视图（懒加载）。

        会话初始化时**不**再把技能文件逐个拷进沙箱，只做两件轻量的事：

        1. 登记全部"已知技能"元数据（name/description + 宿主源路径），供向模型
           广告可用技能；真正把技能拷进 ``<sandbox>/skills/<name>/`` 的动作推迟到
           ``ensure_materialized``（由 load_skill 在需要读取技能文件时触发）。
        2. 加载沙箱里**已存在**（用户在 Agent workspace 手动加/改过）的技能，
           使其优先生效、且手改不被覆盖。

        这样新用户（尤其挂载 PVC 的远端沙箱）不必在启动时逐个拷贝并索引全部
        系统技能——那是慢的根因；只有真正被 load 的技能才落地到工作区。

        Args:
            host_skill_manager: 宿主侧 SkillManager / SkillProxy
        """
        self._skills_cache.clear()
        self._known_skills.clear()
        allowed_names = list(host_skill_manager.list_skills())
        if not allowed_names:
            logger.debug("沙箱技能：宿主未声明可用技能，跳过加载")
            return

        host_skills = getattr(host_skill_manager, "skills", {}) or {}

        # 1) 登记"已知技能"元数据（不拷文件）
        for skill_name in allowed_names:
            host_skill = host_skills.get(skill_name)
            if host_skill is not None:
                self._known_skills[skill_name] = host_skill
            else:
                logger.warning(f"宿主未提供技能 '{skill_name}' 的元数据，跳过")

        # 2) 加载沙箱内已存在的技能（用户手改优先，不覆盖）
        if await self._file_exists(self.skills_dir):
            for skill_name in allowed_names:
                skill_path = os.path.join(self.skills_dir, skill_name)
                skill_md_path = os.path.join(skill_path, "SKILL.md")
                if await self._file_exists(skill_md_path):
                    skill = await self._load_skill_from_dir(skill_path)
                    if skill:
                        self._skills_cache[skill_name] = skill
                    else:
                        logger.warning(
                            f"沙箱已存在 SKILL.md 但解析失败，保留现状: {skill_md_path}"
                        )

        logger.debug(
            f"沙箱技能视图就绪：已知 {len(self._known_skills)} 个，"
            f"已落地 {list(self._skills_cache.keys())}"
        )

    async def ensure_materialized(self, skill_name: str) -> Optional[SkillSchema]:
        """确保技能已落地到沙箱，并返回其（沙箱内的）SkillSchema。

        懒加载的落地点，由 load_skill 在真正需要读取技能文件时调用：

        - 已落地 → 直接返回缓存；
        - 已知但未落地 → 现在从宿主源路径 ``copy_from_host`` 到
          ``<sandbox>/skills/<name>/``，再从沙箱加载、缓存后返回；
        - 未知 → 返回 None。
        """
        existing = self._skills_cache.get(skill_name)
        if existing is not None:
            return existing

        known = self._known_skills.get(skill_name)
        if known is None:
            return None

        host_path = getattr(known, "path", None)
        if not host_path or not os.path.isdir(host_path):
            logger.warning(
                f"技能 '{skill_name}' 无有效宿主源路径，无法落地: {host_path}"
            )
            return None

        # 串行化"同一技能"的落地：并行 load_skill 可能对同一目录并发拷贝
        # （local 的 copy 会先 rmtree 目标），必须避免竞态。dict.setdefault 在
        # 事件循环里不含 await，可原子地为每个技能创建一把锁。
        lock = self._materialize_locks.setdefault(skill_name, asyncio.Lock())
        async with lock:
            # 双检：等锁期间可能已被其它协程落地
            existing = self._skills_cache.get(skill_name)
            if existing is not None:
                return existing

            # 沙箱根目录按需建一次
            if not await self._file_exists(self.skills_dir):
                ensure_dir = getattr(self.sandbox, "ensure_directory", None)
                if callable(ensure_dir):
                    await ensure_dir(self.skills_dir)  # pyright: ignore[reportGeneralTypeIssues]
                else:
                    logger.warning(
                        f"沙箱技能目录不存在且无法创建（缺少 ensure_directory）: {self.skills_dir}"
                    )
                    return None

            skill_path = os.path.join(self.skills_dir, skill_name)
            skill_md_path = os.path.join(skill_path, "SKILL.md")
            try:
                # 各 provider 返回值不统一，用 SKILL.md 是否落地作为最终判定依据。
                await self.sandbox.copy_from_host(host_path, skill_path)
            except Exception as e:
                logger.warning(
                    f"技能按需落地失败 {skill_name}: {host_path} -> {skill_path}: {e}"
                )
                return None

            if not await self._file_exists(skill_md_path):
                logger.warning(f"技能落地后未发现 SKILL.md: {skill_md_path}")
                return None

            skill = await self._load_skill_from_dir(skill_path)
            if skill:
                self._skills_cache[skill_name] = skill
                logger.info(
                    f"技能按需落地: {skill_name} ({host_path} -> {skill_path})"
                )
            else:
                logger.warning(f"技能落地后仍无法加载 SKILL.md: {skill_path}")
            return skill

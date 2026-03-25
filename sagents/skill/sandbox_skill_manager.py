"""
沙箱内技能管理器

通过沙箱接口管理沙箱内的技能，与宿主机的 SkillManager 分离。
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
        从沙箱加载所有技能
        """
        self._skills_cache.clear()
        
        try:
            # 检查技能目录是否存在
            if not await self._file_exists(self.skills_dir):
                logger.debug(f"沙箱技能目录不存在: {self.skills_dir}")
                return
            
            # 列出技能目录下的所有子目录
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
    
    async def sync_from_host(self, host_skill_manager) -> None:
        """
        从宿主机同步技能到沙箱
        
        只同步沙箱中不存在的技能，不会覆盖沙箱中已有的技能。
        
        Args:
            host_skill_manager: 宿主机的 SkillManager 实例
        """
        # 先加载沙箱中现有的技能
        await self.load_skills()
        
        for skill_name in host_skill_manager.list_skills():
            if skill_name in self._skills_cache:
                # 沙箱中已存在，跳过
                logger.debug(f"技能 {skill_name} 已存在于沙箱中，跳过同步")
                continue
            
            # 从宿主机复制到沙箱
            host_skill = host_skill_manager.skills.get(skill_name)
            if not host_skill:
                continue
            
            source_path = host_skill.path
            target_path = os.path.join(self.skills_dir, skill_name)
            
            try:
                result = await self.sandbox.copy_from_host(
                    source_path,
                    target_path,
                    ignore_patterns=['.*', '__pycache__', '*.pyc', '.git', 'node_modules']
                )
                if result:
                    logger.debug(f"同步技能 {skill_name} 到沙箱成功")
                else:
                    logger.warning(f"同步技能 {skill_name} 到沙箱失败")
            except Exception as e:
                logger.error(f"同步技能 {skill_name} 失败: {e}")
        
        # 重新加载技能列表
        await self.load_skills()

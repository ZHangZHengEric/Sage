import asyncio
import os
import shutil
import tempfile
import zipfile
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiofiles
import httpx
import yaml
from fastapi import UploadFile
from loguru import logger
from sagents.skill.skill_manager import SkillManager, get_skill_manager

from common.core import config
from common.core.exceptions import SageHTTPException
from common.models.agent import AgentConfigDao
from common.services.agent_workspace import get_agent_skill_dir


def _calculate_skill_hash(skill_path: str) -> str:
    """
    计算技能文件夹的哈希值，用于检测技能是否发生变化。

    计算所有文件的哈希值（排除隐藏文件和缓存文件），
    返回一个包含所有文件哈希的复合哈希值。
    """
    try:
        if not os.path.exists(skill_path):
            return ""

        # 收集所有文件及其哈希值
        file_hashes = {}
        for root, dirs, files in os.walk(skill_path):
            # 排除隐藏文件和缓存文件
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['__pycache__', 'node_modules']]

            for file in sorted(files):
                if file.startswith('.'):
                    continue

                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, skill_path)

                try:
                    with open(file_path, "rb") as f:
                        file_hash = hashlib.md5(f.read()).hexdigest()
                    file_hashes[rel_path] = file_hash
                except Exception as e:
                    logger.warning(f"计算文件哈希失败 {file_path}: {e}")

        # 按文件路径排序后生成复合哈希
        sorted_items = sorted(file_hashes.items())
        composite = "|".join([f"{path}:{hash}" for path, hash in sorted_items])
        return hashlib.md5(composite.encode("utf-8")).hexdigest()
    except Exception as e:
        logger.warning(f"计算技能哈希失败 {skill_path}: {e}")
        return ""


def _is_skill_need_update(source_skill_path: str, agent_skill_path: str) -> bool:
    """
    判断Agent工作空间的技能是否需要更新。

    对比广场技能的所有文件与Agent本地技能的对应文件：
    - 如果广场的文件在Agent本地不存在 → 需要更新
    - 如果广场的文件内容与Agent本地不同 → 需要更新
    - 如果Agent本地有多余的文件 → 不需要更新（忽略）

    Args:
        source_skill_path: 广场技能路径
        agent_skill_path: Agent本地技能路径

    Returns:
        bool: 是否需要更新
    """
    try:
        logger.info(f"对比技能: 广场={source_skill_path}, Agent={agent_skill_path}")

        # 获取广场技能的所有文件
        source_files = {}
        for root, dirs, files in os.walk(source_skill_path):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['__pycache__', 'node_modules']]

            for file in sorted(files):
                if file.startswith('.'):
                    continue

                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, source_skill_path)

                try:
                    with open(file_path, "rb") as f:
                        source_files[rel_path] = hashlib.md5(f.read()).hexdigest()
                except Exception as e:
                    logger.warning(f"读取广场技能文件失败 {file_path}: {e}")

        logger.info(f"广场技能文件: {list(source_files.keys())}")

        # 对比Agent本地技能的对应文件
        for rel_path, source_hash in source_files.items():
            agent_file_path = os.path.join(agent_skill_path, rel_path)

            # 如果Agent本地不存在该文件 → 需要更新
            if not os.path.exists(agent_file_path):
                logger.info(f"技能需要更新: Agent缺少文件 {rel_path}")
                return True

            # 如果Agent本地文件内容不同 → 需要更新
            try:
                with open(agent_file_path, "rb") as f:
                    agent_hash = hashlib.md5(f.read()).hexdigest()
                if agent_hash != source_hash:
                    logger.info(f"技能需要更新: 文件 {rel_path} 内容不同")
                    return True
            except Exception as e:
                logger.warning(f"读取Agent技能文件失败 {agent_file_path}: {e}")
                return True

        # 所有广场文件都存在且内容相同 → 不需要更新
        logger.info(f"技能不需要更新")
        return False
    except Exception as e:
        logger.warning(f"判断技能是否需要更新失败: {e}")
        return False


def _get_cfg() -> config.StartupConfig:
    cfg = config.get_startup_config()
    if not cfg:
        raise RuntimeError("Startup config not initialized")
    return cfg


def _is_desktop_mode() -> bool:
    return _get_cfg().app_mode == "desktop"


def _desktop_user_skills_root(user_id: str) -> str:
    """Desktop 用户技能目录：与 server 的 user_dir/<id>/skills 一致。"""
    cfg = _get_cfg()
    return os.path.normpath(os.path.join(cfg.user_dir, user_id, "skills"))


def _desktop_skill_owner_user_id(skill_path: str, current_user_id: str) -> str:
    """根据磁盘路径判断是否为当前用户的技能（用于 list_skills）。"""
    if not current_user_id:
        return ""
    root = _desktop_user_skills_root(current_user_id)
    sp = os.path.normpath(skill_path)
    if sp == root or sp.startswith(root + os.sep):
        return current_user_id
    return ""


def _set_permissions_recursive(path: str, dir_mode: int = 0o755, file_mode: int = 0o644) -> None:
    try:
        if os.path.isdir(path):
            os.chmod(path, dir_mode)
        for root, dirs, files in os.walk(path):
            for d in dirs:
                os.chmod(os.path.join(root, d), dir_mode)
            for f in files:
                os.chmod(os.path.join(root, f), file_mode)
    except Exception as e:
        logger.warning(f"Failed to set permissions for {path}: {e}")


def _validate_skill_content(skill_name: str, content: str) -> None:
    try:
        metadata = {}
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                metadata = yaml.safe_load(parts[1]) or {}

        name = metadata.get("name")
        description = metadata.get("description")
        if not name or not description:
            raise ValueError("Missing name or description in YAML frontmatter")
        if name != skill_name:
            raise ValueError(
                f"Skill name cannot be changed. Expected '{skill_name}', got '{name}'"
            )
    except Exception as e:
        logger.warning(f"Skill validation failed before save: {e}")
        detail_msg = (
            str(e)
            if "Skill name cannot be changed" in str(e)
            else "技能格式验证失败，请检查 SKILL.md 格式 (需包含 name 和 description)。"
        )
        raise SageHTTPException(status_code=500 if _is_desktop_mode() else 400, detail=detail_msg)


def _skill_name_to_dir(name: str) -> str:
    """将 SKILL.md 的 name 字段规范化为合法目录名。

    只保留字母、数字、连字符、下划线，空格转连字符，去掉其他特殊字符。
    """
    import re
    name = name.strip().replace(" ", "-")
    name = re.sub(r"[^\w\-]", "", name)
    return name or "skill"


def _extract_skill_from_zip(
    temp_extract_dir: str,
    original_filename: str,
) -> Tuple[Optional[str], Optional[str]]:
    """从解压目录中找到技能结构，并以 SKILL.md 的 name 字段作为目录名返回。

    优先用 SKILL.md 中的 name 字段命名目录，避免 zip 文件名/内部子目录名与
    SKILL.md name 不一致导致后续路径查找失败。
    """
    def _dir_name_from_skill_md(skill_md_path: str, fallback: str) -> str:
        name = _read_skill_name_from_md(skill_md_path)
        if name:
            normalized = _skill_name_to_dir(name)
            if normalized:
                return normalized
        return fallback

    if os.path.exists(os.path.join(temp_extract_dir, "SKILL.md")):
        fallback = os.path.splitext(original_filename)[0]
        dir_name = _dir_name_from_skill_md(os.path.join(temp_extract_dir, "SKILL.md"), fallback)
        return dir_name, temp_extract_dir

    for item in os.listdir(temp_extract_dir):
        item_path = os.path.join(temp_extract_dir, item)
        if os.path.isdir(item_path) and os.path.exists(os.path.join(item_path, "SKILL.md")):
            dir_name = _dir_name_from_skill_md(os.path.join(item_path, "SKILL.md"), item)
            return dir_name, item_path

    return None, None


def _read_skill_name_from_md(skill_md_path: str) -> Optional[str]:
    if not os.path.exists(skill_md_path):
        return None
    try:
        with open(skill_md_path, "r", encoding="utf-8") as f:
            content = f.read()
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                metadata = yaml.safe_load(parts[1]) or {}
                return metadata.get("name")
    except Exception as e:
        logger.warning(f"Failed to read skill name from {skill_md_path}: {e}")
    return None


def _get_skill_info_safe(tm: Any, skill_name: str) -> Optional[Any]:
    for skill in tm.list_skill_info():
        if skill.name == skill_name:
            return skill
    return None


def _get_skill_dimension(skill_path: str) -> Dict[str, Any]:
    path = Path(skill_path)
    parts = path.parts

    if "agents" in parts:
        idx = parts.index("agents")
        tail = parts[idx + 1 :]
        if len(tail) >= 3 and tail[2] == "skills":
            return {
                "dimension": "agent",
                "owner_user_id": tail[0],
                "agent_id": tail[1],
            }
        if len(tail) >= 2 and tail[1] == "skills":
            return {
                "dimension": "agent",
                "owner_user_id": "",
                "agent_id": tail[0],
            }

    if "users" in parts:
        idx = parts.index("users")
        if len(parts) > idx + 2 and parts[idx + 2] == "skills":
            return {
                "dimension": "user",
                "owner_user_id": parts[idx + 1],
                "agent_id": None,
            }

    if "skills" in parts:
        idx = parts.index("skills")
        if len(parts) == idx + 2:
            return {
                "dimension": "system",
                "owner_user_id": None,
                "agent_id": None,
            }

    return {"dimension": "system", "owner_user_id": None, "agent_id": None}


def _check_skill_permission(
    dimension_info: Dict[str, Any],
    user_id: str,
    role: str,
    action: str = "access",
) -> None:
    if role == "admin":
        return

    if dimension_info["dimension"] == "system":
        if action in ("delete", "modify"):
            raise SageHTTPException(
                detail=f"Permission denied: Cannot {action} system skill"
            )
    elif dimension_info["owner_user_id"] != user_id:
        raise SageHTTPException(detail="Permission denied")


def _sync_desktop_agent_skills() -> None:
    try:
        sage_home = Path.home() / ".sage"
        agents_dir = sage_home / "agents"
        sage_skills_dir = sage_home / "skills"
        if not agents_dir.exists():
            return

        sage_skills_dir.mkdir(parents=True, exist_ok=True)
        for agent_dir in agents_dir.iterdir():
            if not agent_dir.is_dir():
                continue
            agent_skills_dir = agent_dir / "skills"
            if not agent_skills_dir.exists():
                continue
            for skill_path in agent_skills_dir.iterdir():
                if not skill_path.is_dir():
                    continue
                if not any(
                    f.name.lower() == "skill.md" for f in skill_path.iterdir() if f.is_file()
                ):
                    continue
                target_path = sage_skills_dir / skill_path.name
                if target_path.exists():
                    continue
                try:
                    shutil.copytree(skill_path, target_path)
                    logger.info(f"Synced agent skill: {skill_path.name} from {agent_dir.name}")
                except Exception as e:
                    logger.error(f"Failed to sync skill '{skill_path.name}': {e}")
    except Exception as e:
        logger.error(f"Error syncing agent skills: {e}")


def _collect_server_skills() -> List[Any]:
    cfg = _get_cfg()
    skill_dir = cfg.skill_dir
    user_dir = cfg.user_dir
    agents_dir = cfg.agents_dir
    all_skills: List[Any] = []

    if os.path.exists(skill_dir):
        try:
            all_skills.extend(list(SkillManager(skill_dirs=[skill_dir], isolated=True).list_skill_info()))
        except Exception as e:
            logger.warning(f"加载系统技能失败: {e}")

    if os.path.exists(user_dir):
        try:
            for user_folder in os.listdir(user_dir):
                user_skills_path = os.path.join(user_dir, user_folder, "skills")
                if os.path.isdir(user_skills_path):
                    try:
                        tm = SkillManager(skill_dirs=[user_skills_path], isolated=True)
                        all_skills.extend(list(tm.list_skill_info()))
                    except Exception as e:
                        logger.warning(f"加载用户 {user_folder} 技能失败: {e}")
        except Exception as e:
            logger.warning(f"扫描用户技能目录失败: {e}")

    if os.path.exists(agents_dir):
        try:
            for user_folder in os.listdir(agents_dir):
                user_agents_path = os.path.join(agents_dir, user_folder)
                if os.path.isdir(user_agents_path):
                    for agent_folder in os.listdir(user_agents_path):
                        agent_skills_path = os.path.join(
                            user_agents_path,
                            agent_folder,
                            "skills",
                        )
                        if os.path.isdir(agent_skills_path):
                            try:
                                tm = SkillManager(skill_dirs=[agent_skills_path], isolated=True)
                                all_skills.extend(list(tm.list_skill_info()))
                            except Exception as e:
                                logger.warning(
                                    f"加载 Agent {user_folder}/{agent_folder} 技能失败: {e}"
                                )
        except Exception as e:
            logger.warning(f"扫描Agent技能目录失败: {e}")

    return all_skills


def _list_desktop_skills_sync(current_user_id: str = "") -> List[Dict[str, Any]]:
    tm = get_skill_manager()
    if not tm:
        return []
    # Disabled temporarily: do not auto-sync agent workspace skills into ~/.sage/skills during desktop skill listing.
    # _sync_desktop_agent_skills()
    tm.reload()
    out: List[Dict[str, Any]] = []
    for skill in list(tm.list_skill_info()):
        uid = _desktop_skill_owner_user_id(skill.path, current_user_id)
        out.append(
            {
                "name": skill.name,
                "description": skill.description,
                "user_id": uid,
                "dimension": "user" if uid else "system",
                "owner_user_id": uid or None,
                "path": skill.path,
            }
        )
    return out


def _find_server_skill_by_name(skill_name: str) -> Optional[Any]:
    for skill in _collect_server_skills():
        if skill.name == skill_name:
            return skill
    return None


async def list_skills(
    current_user_id: str = "",
    role: str = "user",
    filter_agent_id: Optional[str] = None,
    dimension: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if _is_desktop_mode():
        return await asyncio.to_thread(_list_desktop_skills_sync, current_user_id)

    all_skills = await asyncio.to_thread(_collect_server_skills)
    allowed_skills = None
    if filter_agent_id:
        agent_dao = AgentConfigDao()
        agent = await agent_dao.get_by_id(filter_agent_id)
        if agent and agent.config:
            allowed_skills = agent.config.get("availableSkills") or agent.config.get("available_skills")

    agent_dao = AgentConfigDao()
    all_agents = await agent_dao.get_list()
    agent_name_map = {agent.agent_id: agent.name for agent in all_agents}

    skills: List[Dict[str, Any]] = []
    for skill in all_skills:
        name = skill.name
        if allowed_skills is not None and name not in allowed_skills:
            continue

        dimension_info = _get_skill_dimension(skill.path)
        skill_dimension = dimension_info["dimension"]
        if dimension and dimension != "all" and skill_dimension != dimension:
            continue

        if role != "admin" and skill_dimension in {"user", "agent"}:
            if dimension_info["owner_user_id"] != current_user_id:
                continue

        agent_id = dimension_info["agent_id"]
        skills.append(
            {
                "name": skill.name,
                "description": skill.description,
                "user_id": dimension_info["owner_user_id"] or "",
                "dimension": skill_dimension,
                "owner_user_id": dimension_info["owner_user_id"],
                "agent_id": agent_id,
                "agent_name": agent_name_map.get(agent_id, agent_id) if agent_id else None,
                "path": skill.path,
            }
        )
    return skills


async def list_skills_for_agent(agent_config: Dict[str, Any]) -> List[Dict[str, Any]]:
    allowed_names = agent_config.get("availableSkills") or agent_config.get("available_skills") or []
    allowed_set = {str(name).strip() for name in allowed_names if str(name).strip()}
    if not allowed_set:
        return []

    all_skills = await list_skills()
    return [skill for skill in all_skills if skill.get("name") in allowed_set]


def _get_agent_available_skills_sync(
    agent_id: str,
    agent_user_id: str,
    cfg: config.StartupConfig,
) -> List[Dict[str, Any]]:
    skill_dir = cfg.skill_dir
    user_dir = cfg.user_dir
    agents_dir = cfg.agents_dir

    source_skills: Dict[str, Dict[str, Any]] = {}

    logger.info(f"技能广场路径: skill_dir={skill_dir}, user_dir={user_dir}")

    if os.path.exists(skill_dir):
        try:
            tm = SkillManager(skill_dirs=[skill_dir], isolated=True)
            system_skills = list(tm.list_skill_info())
            logger.info(f"系统技能数量: {len(system_skills)}")
            for skill in system_skills:
                source_skills[skill.name] = {
                    "name": skill.name,
                    "description": skill.description,
                    "source_dimension": "system",
                    "path": skill.path,
                    "hash": _calculate_skill_hash(skill.path),
                }
        except Exception as e:
            logger.warning(f"加载系统技能失败: {e}")

    if os.path.exists(user_dir) and agent_user_id:
        user_skills_path = os.path.join(user_dir, agent_user_id, "skills")
        logger.info(f"用户技能路径: {user_skills_path}, 存在={os.path.isdir(user_skills_path)}")
        if os.path.isdir(user_skills_path):
            try:
                tm = SkillManager(skill_dirs=[user_skills_path], isolated=True)
                user_skills = list(tm.list_skill_info())
                logger.info(f"用户技能数量: {len(user_skills)}")
                for skill in user_skills:
                    source_skills[skill.name] = {
                        "name": skill.name,
                        "description": skill.description,
                        "source_dimension": "user",
                        "path": skill.path,
                        "hash": _calculate_skill_hash(skill.path),
                    }
            except Exception as e:
                logger.warning(f"加载用户技能失败: {e}")
    else:
        logger.info(
            "用户技能目录不存在或参数不全: "
            f"user_dir存在={os.path.exists(user_dir) if user_dir else False}, "
            f"agent_user_id={agent_user_id}"
        )

    agent_skills: Dict[str, Dict[str, Any]] = {}
    logger.info(
        "检查Agent工作空间: "
        f"agents_dir={agents_dir}, agent_user_id={agent_user_id}, "
        f"agent_id={agent_id}, app_mode={cfg.app_mode}"
    )

    try:
        agent_skills_path = str(
            get_agent_skill_dir(
                agent_id,
                user_id=agent_user_id,
                app_mode=cfg.app_mode,
                ensure_exists=False,
            )
        )
    except ValueError:
        agent_skills_path = ""

    if agent_id and os.path.isdir(agent_skills_path):
        logger.info(f"Agent技能路径: {agent_skills_path}, 存在={os.path.isdir(agent_skills_path)}")
        try:
            tm = SkillManager(skill_dirs=[agent_skills_path], isolated=True)
            agent_skill_list = list(tm.list_skill_info())
            logger.info(f"Agent工作空间技能数量: {len(agent_skill_list)}")
            for skill in agent_skill_list:
                agent_skills[skill.name] = {
                    "name": skill.name,
                    "description": skill.description,
                    "path": skill.path,
                    "hash": _calculate_skill_hash(skill.path),
                }
        except Exception as e:
            logger.warning(f"加载Agent技能失败: {e}")
    else:
        logger.info(f"Agent工作空间不存在: {agent_skills_path}")

    skills_list: List[Dict[str, Any]] = []
    logger.info(
        "get_agent_available_skills: "
        f"广场技能={list(source_skills.keys())}, Agent技能={list(agent_skills.keys())}"
    )

    for skill_name, source_skill in source_skills.items():
        skill_info = {
            "name": skill_name,
            "description": source_skill["description"],
            "source_dimension": source_skill["source_dimension"],
            "source_path": source_skill["path"],
        }

        if skill_name in agent_skills:
            agent_skill = agent_skills[skill_name]
            logger.info(f"检查技能 '{skill_name}': 广场={source_skill['path']}, Agent={agent_skill['path']}")
            need_update = _is_skill_need_update(source_skill["path"], agent_skill["path"])
            skill_info["need_update"] = need_update
            skill_info["agent_path"] = agent_skill["path"]
            logger.info(f"技能 '{skill_name}' need_update={need_update}")
        else:
            skill_info["need_update"] = False
            logger.info(f"技能 '{skill_name}' 不在Agent工作空间中")

        skills_list.append(skill_info)

    skills_list.sort(key=lambda x: x["name"])
    return skills_list


async def get_agent_available_skills(
    agent_id: str,
    current_user_id: str,
    role: str = "user",
) -> List[Dict[str, Any]]:
    """
    获取Agent可用的技能列表，包含是否需要更新状态。

    只检测技能广场（系统/用户技能）与Agent工作空间中技能的差异。
    如果Agent工作空间中的技能与广场不一致，则标记为需要更新。

    返回的技能列表中每个技能会包含以下字段：
    - name: 技能名称
    - description: 技能描述
    - source_dimension: 技能来源维度 (system, user)
    - need_update: 是否需要更新 (bool)
    - source_path: 源技能路径（用于更新）
    """
    cfg = _get_cfg()

    agent_dao = AgentConfigDao()
    agent = await agent_dao.get_by_id(agent_id)
    agent_user_id = agent.user_id if agent and agent.user_id else current_user_id

    return await asyncio.to_thread(
        _get_agent_available_skills_sync,
        agent_id,
        agent_user_id,
        cfg,
    )


def _find_source_skill_path(
    skill_name: str,
    agent_user_id: str,
    cfg: config.StartupConfig,
) -> Optional[str]:
    """在用户技能和系统技能中查找源技能路径（用户优先）。

    通过 SkillManager 按 SKILL.md name 查找，避免目录名与 name 不一致的问题。
    """
    if agent_user_id and os.path.exists(cfg.user_dir):
        user_skills_path = os.path.join(cfg.user_dir, agent_user_id, "skills")
        if os.path.isdir(user_skills_path):
            try:
                tm_user = SkillManager(skill_dirs=[user_skills_path], isolated=True)
                skill_info = _get_skill_info_safe(tm_user, skill_name)
                if skill_info:
                    return skill_info.path
            except Exception as e:
                logger.warning(f"_find_source_skill_path: SkillManager 查找用户技能失败: {e}")
        # Fallback: 直接路径匹配
        direct_path = os.path.join(cfg.user_dir, agent_user_id, "skills", skill_name)
        if os.path.isdir(direct_path):
            return direct_path

    if os.path.exists(cfg.skill_dir):
        try:
            tm_sys = SkillManager(skill_dirs=[cfg.skill_dir], isolated=True)
            skill_info = _get_skill_info_safe(tm_sys, skill_name)
            if skill_info:
                return skill_info.path
        except Exception as e:
            logger.warning(f"_find_source_skill_path: SkillManager 查找系统技能失败: {e}")
        # Fallback: 直接路径匹配
        system_skill_path = os.path.join(cfg.skill_dir, skill_name)
        if os.path.isdir(system_skill_path):
            return system_skill_path

    return None


def _resolve_agent_selected_skills(agent_config: Dict[str, Any]) -> List[str]:
    raw_skills = agent_config.get("availableSkills")
    if raw_skills is None:
        raw_skills = agent_config.get("available_skills") or []

    resolved_skills: List[str] = []
    seen: set[str] = set()
    for name in raw_skills:
        normalized = str(name).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        resolved_skills.append(normalized)
    return resolved_skills


def _list_existing_agent_workspaces(
    agent_id: str,
    cfg: config.StartupConfig,
) -> List[Dict[str, str]]:
    if cfg.app_mode == "desktop":
        return []

    agents_root = Path(cfg.agents_dir)
    if not agents_root.exists() or not agents_root.is_dir():
        return []

    workspaces: List[Dict[str, str]] = []
    for user_dir in sorted(agents_root.iterdir(), key=lambda item: item.name):
        if not user_dir.is_dir():
            continue
        workspace_path = user_dir / agent_id
        if not workspace_path.is_dir():
            continue
        workspaces.append(
            {
                "user_id": user_dir.name,
                "workspace_path": str(workspace_path),
            }
        )
    return workspaces


def _copy_skill_to_workspace(
    source_skill_path: str,
    workspace_path: str,
    skill_name: str,
) -> str:
    target_skill_path = Path(workspace_path) / "skills" / skill_name
    target_skill_path.parent.mkdir(parents=True, exist_ok=True)

    if target_skill_path.exists():
        shutil.rmtree(target_skill_path)

    shutil.copytree(source_skill_path, target_skill_path)
    _set_permissions_recursive(str(target_skill_path))
    return str(target_skill_path)


def _list_skill_dir_names_sync(agent_skills_dir: Path) -> set[str]:
    if not agent_skills_dir.exists():
        return set()
    return {p.name for p in agent_skills_dir.iterdir() if p.is_dir()}


def _is_target_skill_current_sync(source_path: str, target_path: str) -> bool:
    return os.path.isdir(target_path) and not _is_skill_need_update(source_path, target_path)


async def sync_skill_to_agent_workspaces(
    agent_id: str,
    skill_names: Optional[List[str]] = None,
    user_id: str = "",
    role: str = "user",
) -> Dict[str, Any]:
    cfg = _get_cfg()
    if cfg.app_mode == "desktop":
        raise SageHTTPException(status_code=500, detail="该接口仅支持 server 模式")

    agent_dao = AgentConfigDao()
    agent = await agent_dao.get_by_id(agent_id)
    if not agent:
        raise SageHTTPException(detail=f"Agent '{agent_id}' 不存在")

    agent_owner_user_id = agent.user_id or user_id
    if role != "admin" and agent_owner_user_id != user_id:
        raise SageHTTPException(detail="无权批量同步该Agent工作空间中的技能")

    if skill_names is not None:
        resolved_skill_names = _resolve_agent_selected_skills({"availableSkills": skill_names})
    else:
        resolved_skill_names = _resolve_agent_selected_skills(agent.config or {})
    workspaces = await asyncio.to_thread(_list_existing_agent_workspaces, agent_id, cfg)

    result: Dict[str, Any] = {
        "agent_id": agent_id,
        "resolved_skill_names": resolved_skill_names,
        "workspace_count": len(workspaces),
        "updated_workspace_count": 0,
        "failed_workspace_count": 0,
        "results": [],
    }

    if not resolved_skill_names:
        return result

    source_skill_paths: Dict[str, str] = {}
    missing_source_skills: List[str] = []
    for current_skill_name in resolved_skill_names:
        source_skill_path = await asyncio.to_thread(
            _find_source_skill_path,
            current_skill_name,
            agent_owner_user_id,
            cfg,
        )
        if source_skill_path:
            source_skill_paths[current_skill_name] = source_skill_path
            continue

        missing_source_skills.append(current_skill_name)
        logger.warning(
            "批量同步Agent工作空间技能时发现缺失源技能: "
            f"agent_id={agent_id}, skill={current_skill_name}"
        )

    if not workspaces:
        return result

    for workspace in workspaces:
        workspace_path = workspace["workspace_path"]
        updated_skills: List[str] = []
        failed_skills: List[str] = list(missing_source_skills)

        for current_skill_name, source_skill_path in source_skill_paths.items():
            try:
                await asyncio.to_thread(
                    _copy_skill_to_workspace,
                    source_skill_path,
                    workspace_path,
                    current_skill_name,
                )
                updated_skills.append(current_skill_name)
            except Exception as e:
                failed_skills.append(current_skill_name)
                logger.warning(
                    "批量同步Agent工作空间技能失败: "
                    f"agent_id={agent_id}, workspace={workspace_path}, "
                    f"skill={current_skill_name}, error={e}"
                )

        status = "success"
        if failed_skills and updated_skills:
            status = "partial_success"
        elif failed_skills:
            status = "failed"

        result["results"].append(
            {
                "user_id": workspace["user_id"],
                "workspace_path": workspace_path,
                "updated_skills": updated_skills,
                "failed_skills": failed_skills,
                "status": status,
            }
        )
        if updated_skills:
            result["updated_workspace_count"] += 1
        if failed_skills:
            result["failed_workspace_count"] += 1

    return result


async def sync_workspace_skills(
    user_id: str,
    agent_id: str,
    purge_extra: bool = False,
) -> Dict[str, List[str]]:
    """
    将 Agent 配置中的 skills 批量同步到 workspace 目录，
    返回 synced / removed / unchanged 三个列表。
    """
    agent_dao = AgentConfigDao()
    agent = await agent_dao.get_by_id(agent_id)
    if not agent:
        raise SageHTTPException(detail=f"Agent '{agent_id}' 不存在")

    agent_config = agent.config or {}
    selected_skills = [
        str(name).strip()
        for name in (
            agent_config.get("availableSkills")
            or agent_config.get("available_skills")
            or []
        )
        if str(name).strip()
    ]

    cfg = _get_cfg()
    agent_user_id = agent.user_id or user_id

    try:
        agent_skills_dir = get_agent_skill_dir(
            agent_id,
            user_id=agent_user_id,
            app_mode=cfg.app_mode,
            ensure_exists=True,
        )
    except ValueError:
        raise SageHTTPException(detail="sync_workspace_skills 失败: 缺少 user_id")

    existing_skills = await asyncio.to_thread(_list_skill_dir_names_sync, agent_skills_dir)

    synced: List[str] = []
    unchanged: List[str] = []
    removed: List[str] = []

    for skill_name in selected_skills:
        try:
            source_path = await asyncio.to_thread(_find_source_skill_path, skill_name, agent_user_id, cfg)
            if not source_path:
                logger.warning(f"sync_workspace_skills: 技能 '{skill_name}' 在技能广场中不存在，跳过")
                unchanged.append(skill_name)
                continue

            target_path = str(agent_skills_dir / skill_name)

            target_exists_and_current = await asyncio.to_thread(
                _is_target_skill_current_sync,
                source_path,
                target_path,
            )
            if target_exists_and_current:
                unchanged.append(skill_name)
                continue

            await asyncio.to_thread(_copy_skill_to_workspace, source_path, str(agent_skills_dir.parent), skill_name)
            synced.append(skill_name)
        except Exception as e:
            logger.warning(f"sync_workspace_skills: skill={skill_name}, error={e}")
            unchanged.append(skill_name)

    if purge_extra:
        selected_set = set(selected_skills)
        for name in existing_skills:
            if name not in selected_set:
                try:
                    await asyncio.to_thread(shutil.rmtree, str(agent_skills_dir / name))
                    removed.append(name)
                    logger.info(f"sync_workspace_skills: 删除多余 skill '{name}'")
                except Exception as e:
                    logger.warning(f"sync_workspace_skills: 删除 skill '{name}' 失败: {e}")

    logger.info(
        f"sync_workspace_skills 完成: agent_id={agent_id}, "
        f"synced={synced}, removed={removed}, unchanged={unchanged}"
    )
    return {"synced": synced, "removed": removed, "unchanged": unchanged}


async def sync_skill_to_agent(
    skill_name: str,
    agent_id: str,
    user_id: str = "",
    role: str = "user",
) -> Dict[str, Any]:
    """
    将技能同步到Agent工作空间。

    从技能广场（系统或用户技能）复制技能到Agent工作空间。
    如果Agent工作空间已存在该技能，则会覆盖更新。

    Args:
        skill_name: 技能名称
        agent_id: Agent ID
        user_id: 用户ID
        role: 用户角色

    Returns:
        Dict: 包含同步结果的信息
    """
    cfg = _get_cfg()

    # 获取Agent信息
    agent_dao = AgentConfigDao()
    agent = await agent_dao.get_by_id(agent_id)
    if not agent:
        raise SageHTTPException(detail=f"Agent '{agent_id}' 不存在")

    agent_user_id = agent.user_id if agent.user_id else user_id

    # 检查权限
    if role != "admin" and agent_user_id != user_id:
        raise SageHTTPException(detail="无权同步技能到该Agent")

    # 1. 查找源技能（优先从用户技能，然后是系统技能）
    source_skill_path = await asyncio.to_thread(
        _find_source_skill_path,
        skill_name,
        agent_user_id,
        cfg,
    )
    source_dimension = None
    if source_skill_path:
        dimension_info = await asyncio.to_thread(_get_skill_dimension, source_skill_path)
        source_dimension = dimension_info.get("dimension")
        logger.info(f"找到技能 '{skill_name}' 路径: {source_skill_path}")

    if source_skill_path is None:
        raise SageHTTPException(detail=f"技能 '{skill_name}' 在技能广场中不存在")

    # 2. 确保Agent工作空间技能目录存在
    agent_skills_dir = str(
        get_agent_skill_dir(
            agent_id,
            user_id=agent_user_id,
            app_mode=cfg.app_mode,
            ensure_exists=True,
        )
    )

    # 3. 复制技能到Agent工作空间
    target_skill_path = os.path.join(agent_skills_dir, skill_name)

    try:
        # 如果已存在，先删除
        await asyncio.to_thread(
            _copy_skill_to_workspace,
            source_skill_path,
            os.path.dirname(agent_skills_dir),
            skill_name,
        )

        logger.info(f"技能 '{skill_name}' 已同步到Agent '{agent_id}' 工作空间")

        return {
            "skill_name": skill_name,
            "agent_id": agent_id,
            "source_dimension": source_dimension,
            "source_path": source_skill_path,
            "target_path": target_skill_path,
            "sync_status": "synced",
        }
    except Exception as e:
        logger.error(f"同步技能失败: {e}")
        raise SageHTTPException(detail=f"同步技能失败: {str(e)}")


async def delete_skill(
    skill_name: str,
    user_id: str = "",
    role: str = "user",
    agent_id: Optional[str] = None,
) -> None:
    if _is_desktop_mode():
        tm = get_skill_manager()
        if not tm:
            raise SageHTTPException(status_code=500, detail="技能管理器未初始化")
        skill_info = _get_skill_info_safe(tm, skill_name)
        if not skill_info:
            raise SageHTTPException(status_code=500, detail=f"Skill '{skill_name}' not found")
        try:
            tm.remove_skill(skill_name)
            skill_path = skill_info.path
            if os.path.exists(skill_path):
                try:
                    await asyncio.to_thread(shutil.rmtree, skill_path)
                except (PermissionError, OSError) as e:
                    logger.warning(f"Could not delete skill files for '{skill_name}' (possibly mounted): {e}")
        except Exception as e:
            logger.error(f"Delete skill failed: {e}")
            raise SageHTTPException(status_code=500, detail=f"删除失败: {str(e)}")
        return

    cfg = _get_cfg()
    if agent_id:
        try:
            agent_skills_path = get_agent_skill_dir(
                agent_id,
                user_id=user_id,
                app_mode=cfg.app_mode,
                ensure_exists=False,
            ) / skill_name
        except ValueError:
            raise SageHTTPException(detail="删除Agent技能失败: 缺少 user_id")
        if not os.path.exists(agent_skills_path):
            raise SageHTTPException(detail=f"Skill '{skill_name}' not found in agent workspace")
        try:
            await asyncio.to_thread(shutil.rmtree, agent_skills_path)
            return
        except (PermissionError, OSError) as e:
            raise SageHTTPException(detail=f"删除技能文件失败: {e}")

    if user_id:
        user_skills_path = os.path.join(cfg.user_dir, user_id, "skills", skill_name)
        if os.path.exists(user_skills_path):
            try:
                await asyncio.to_thread(shutil.rmtree, user_skills_path)
                return
            except (PermissionError, OSError) as e:
                raise SageHTTPException(detail=f"删除技能文件失败: {e}")

    system_skills_path = os.path.join(cfg.skill_dir, skill_name)
    if os.path.exists(system_skills_path):
        if role != "admin":
            raise SageHTTPException(detail="无权删除系统技能", error_detail="forbidden")
        try:
            await asyncio.to_thread(shutil.rmtree, system_skills_path)
            skill_manager = get_skill_manager()
            if skill_manager:
                skill_manager.reload()
            return
        except (PermissionError, OSError) as e:
            raise SageHTTPException(detail=f"删除技能文件失败: {e}")


async def get_skill_content(skill_name: str, user_id: str = "", role: str = "user") -> str:
    if _is_desktop_mode():
        tm = get_skill_manager()
        if not tm:
            raise SageHTTPException(status_code=500, detail="技能管理器未初始化")
        skill_info = _get_skill_info_safe(tm, skill_name)
        if not skill_info:
            raise SageHTTPException(status_code=500, detail=f"Skill '{skill_name}' not found")
    else:
        skill_info = await asyncio.to_thread(_find_server_skill_by_name, skill_name)
        if not skill_info:
            raise SageHTTPException(detail=f"Skill '{skill_name}' not found")
        dimension_info = _get_skill_dimension(skill_info.path)
        _check_skill_permission(dimension_info, user_id, role, "access")

    skill_path = os.path.join(skill_info.path, "SKILL.md")
    if not os.path.exists(skill_path):
        raise SageHTTPException(status_code=500 if _is_desktop_mode() else 400, detail="SKILL.md not found")

    try:
        with open(skill_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        raise SageHTTPException(status_code=500 if _is_desktop_mode() else 400, detail=f"Failed to read skill content: {e}")


async def update_skill_content(
    skill_name: str,
    content: str,
    user_id: str = "",
    role: str = "user",
) -> str:
    if _is_desktop_mode():
        tm = get_skill_manager()
        if not tm:
            raise SageHTTPException(status_code=500, detail="技能管理器未初始化")
        skill_info = _get_skill_info_safe(tm, skill_name)
        if not skill_info:
            raise SageHTTPException(status_code=500, detail=f"Skill '{skill_name}' not found")
    else:
        skill_info = await asyncio.to_thread(_find_server_skill_by_name, skill_name)
        if not skill_info:
            raise SageHTTPException(detail=f"Skill '{skill_name}' not found")
        dimension_info = _get_skill_dimension(skill_info.path)
        _check_skill_permission(dimension_info, user_id, role, "modify")

    skill_path = os.path.join(skill_info.path, "SKILL.md")
    _validate_skill_content(skill_name, content)

    try:
        with open(skill_path, "r", encoding="utf-8") as f:
            original_content = f.read()
    except Exception as e:
        raise SageHTTPException(status_code=500 if _is_desktop_mode() else 400, detail=f"Failed to read original skill content: {e}")

    try:
        with open(skill_path, "w", encoding="utf-8") as f:
            f.write(content)
        if _is_desktop_mode():
            if tm.reload_skill(skill_info.path):
                return "技能更新成功"
            raise ValueError("Skill validation failed")
        return "技能更新成功"
    except Exception as e:
        logger.error(f"Update skill content failed: {e}")
        try:
            with open(skill_path, "w", encoding="utf-8") as f:
                f.write(original_content)
            if _is_desktop_mode():
                tm.reload_skill(skill_info.path)
        except Exception as rollback_error:
            logger.error(f"Rollback failed for skill '{skill_name}': {rollback_error}")

        if isinstance(e, ValueError) and str(e) == "Skill validation failed":
            raise SageHTTPException(status_code=500, detail="技能格式验证失败，已还原修改。请检查 SKILL.md 格式。")
        raise SageHTTPException(status_code=500 if _is_desktop_mode() else 400, detail=f"Failed to update skill content: {e}")


def _process_server_zip_to_dir_sync(
    zip_path: str,
    original_filename: str,
    target_dir: str,
) -> Tuple[bool, str]:
    temp_extract_dir = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(temp_extract_dir)

        skill_dir_name, source_dir = _extract_skill_from_zip(temp_extract_dir, original_filename)
        if not skill_dir_name or not source_dir:
            return False, "未找到有效的技能结构 (缺少 SKILL.md)"

        target_path = os.path.join(target_dir, skill_dir_name)
        if os.path.exists(target_path):
            try:
                shutil.rmtree(target_path)
            except Exception as e:
                return False, f"无法覆盖已存在的技能目录: {e}"

        shutil.copytree(source_dir, target_path, dirs_exist_ok=True)
        _set_permissions_recursive(target_path)
        skill_name = _read_skill_name_from_md(os.path.join(target_path, "SKILL.md"))
        if skill_name:
            return True, f"技能 '{skill_name}' 导入成功"
        return False, "技能验证失败，请检查 SKILL.md 格式"
    except zipfile.BadZipFile:
        return False, "无效的 ZIP 文件"
    except Exception as e:
        logger.error(f"Process zip failed: {e}")
        return False, f"处理技能文件失败: {str(e)}"
    finally:
        if os.path.exists(temp_extract_dir):
            shutil.rmtree(temp_extract_dir)


async def _process_server_zip_to_dir(
    zip_path: str,
    original_filename: str,
    target_dir: str,
) -> Tuple[bool, str]:
    return await asyncio.to_thread(
        _process_server_zip_to_dir_sync,
        zip_path,
        original_filename,
        target_dir,
    )


def _process_desktop_zip_and_register_sync(
    tm: Any, zip_path: str, original_filename: str, user_id: str
) -> Tuple[bool, str]:
    temp_extract_dir = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(temp_extract_dir)

        skill_dir_name, source_dir = _extract_skill_from_zip(temp_extract_dir, original_filename)
        if not skill_dir_name or not source_dir:
            return False, "未找到有效的技能结构 (缺少 SKILL.md)"

        if not user_id:
            return False, "桌面端导入技能需要有效的用户 ID"

        user_skills_root = _desktop_user_skills_root(user_id)
        os.makedirs(user_skills_root, exist_ok=True)
        target_path = os.path.join(user_skills_root, skill_dir_name)
        if os.path.exists(target_path):
            try:
                shutil.rmtree(target_path)
            except Exception as e:
                return False, f"无法覆盖已存在的技能目录: {e}"

        shutil.copytree(source_dir, target_path, dirs_exist_ok=True)
        _set_permissions_recursive(target_path)
        registered_name = tm.register_new_skill(skill_dir_name)
        if registered_name:
            return True, f"技能 '{registered_name}' 导入成功"
        return False, "技能验证失败，请检查 SKILL.md 格式"
    except zipfile.BadZipFile:
        return False, "无效的 ZIP 文件"
    except Exception as e:
        logger.error(f"Process zip failed: {e}")
        return False, f"处理技能文件失败: {str(e)}"
    finally:
        if os.path.exists(temp_extract_dir):
            shutil.rmtree(temp_extract_dir)


async def _process_desktop_zip_and_register(
    tm: Any, zip_path: str, original_filename: str, user_id: str
) -> Tuple[bool, str]:
    return await asyncio.to_thread(
        _process_desktop_zip_and_register_sync,
        tm,
        zip_path,
        original_filename,
        user_id,
    )


def _copy_upload_to_temp_zip_sync(file: UploadFile) -> str:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp_file:
        shutil.copyfileobj(file.file, tmp_file)
        return tmp_file.name


async def import_skill_by_file(
    file: UploadFile,
    user_id: str = "",
    role: str = "user",
    is_system: bool = False,
    is_agent: bool = False,
    agent_id: Optional[str] = None,
) -> str:
    if not file.filename.endswith(".zip"):
        raise SageHTTPException(status_code=500 if _is_desktop_mode() else 400, detail="仅支持 ZIP 文件")

    if not _is_desktop_mode() and is_system and role != "admin":
        raise SageHTTPException(detail="权限不足：只有管理员可以导入系统技能")

    tmp_file_path = ""
    try:
        tmp_file_path = await asyncio.to_thread(_copy_upload_to_temp_zip_sync, file)

        if _is_desktop_mode():
            tm = get_skill_manager()
            if not tm:
                raise SageHTTPException(status_code=500, detail="技能管理器未初始化")
            success, message = await _process_desktop_zip_and_register(
                tm, tmp_file_path, file.filename, user_id
            )
        else:
            cfg = _get_cfg()
            if is_agent and agent_id:
                target_dir = str(
                    get_agent_skill_dir(
                        agent_id,
                        user_id=user_id,
                        app_mode=cfg.app_mode,
                        ensure_exists=True,
                    )
                )
            elif is_system:
                target_dir = cfg.skill_dir
            else:
                target_dir = os.path.join(cfg.user_dir, user_id, "skills")
                await asyncio.to_thread(os.makedirs, target_dir, exist_ok=True)
            success, message = await _process_server_zip_to_dir(tmp_file_path, file.filename, target_dir)

        if not success:
            raise SageHTTPException(status_code=500 if _is_desktop_mode() else 400, detail=message)
        return message
    except Exception as e:
        if isinstance(e, SageHTTPException):
            raise
        raise SageHTTPException(status_code=500 if _is_desktop_mode() else 400, detail=f"导入失败: {str(e)}")
    finally:
        if tmp_file_path and os.path.exists(tmp_file_path):
            await asyncio.to_thread(os.unlink, tmp_file_path)


async def import_skill_by_url(
    url: str,
    user_id: str = "",
    role: str = "user",
    is_system: bool = False,
    is_agent: bool = False,
    agent_id: Optional[str] = None,
) -> str:
    if not _is_desktop_mode() and is_system and role != "admin":
        raise SageHTTPException(detail="权限不足：只有管理员可以导入系统技能")

    tmp_file_path = ""
    try:
        filename = url.split("/")[-1]
        if not filename.endswith(".zip"):
            filename = "downloaded_skill.zip"

        fd, tmp_file_path = tempfile.mkstemp(suffix=".zip")
        os.close(fd)
        timeout = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                async with aiofiles.open(tmp_file_path, "wb") as tmp_file:
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        if chunk:
                            await tmp_file.write(chunk)

        if _is_desktop_mode():
            tm = get_skill_manager()
            if not tm:
                raise SageHTTPException(status_code=500, detail="技能管理器未初始化")
            success, message = await _process_desktop_zip_and_register(
                tm, tmp_file_path, filename, user_id
            )
        else:
            cfg = _get_cfg()
            if is_agent and agent_id:
                target_dir = str(
                    get_agent_skill_dir(
                        agent_id,
                        user_id=user_id,
                        app_mode=cfg.app_mode,
                        ensure_exists=True,
                    )
                )
            elif is_system:
                target_dir = cfg.skill_dir
            else:
                target_dir = os.path.join(cfg.user_dir, user_id, "skills")
                await asyncio.to_thread(os.makedirs, target_dir, exist_ok=True)
            success, message = await _process_server_zip_to_dir(tmp_file_path, filename, target_dir)

        if not success:
            raise SageHTTPException(status_code=500 if _is_desktop_mode() else 400, detail=message)
        return message
    except Exception as e:
        if isinstance(e, SageHTTPException):
            raise
        raise SageHTTPException(status_code=500 if _is_desktop_mode() else 400, detail=f"导入失败: {str(e)}")
    finally:
        if tmp_file_path and os.path.exists(tmp_file_path):
            await asyncio.to_thread(os.unlink, tmp_file_path)

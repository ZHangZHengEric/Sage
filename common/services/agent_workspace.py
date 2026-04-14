from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from common.core import config


def _get_cfg() -> config.StartupConfig:
    cfg = config.get_startup_config()
    if not cfg:
        raise RuntimeError("Startup config not initialized")
    return cfg


def get_agent_workspace_root(
    agent_id: str,
    *,
    user_id: str = "",
    app_mode: Optional[str] = None,
    ensure_exists: bool = False,
) -> Path:
    cfg = _get_cfg()
    mode = app_mode or cfg.app_mode

    if mode == "desktop":
        agents_root = os.environ.get("SAGE_AGENTS_PATH")
        if agents_root:
            root = Path(agents_root) / agent_id
        else:
            root = Path.home() / ".sage" / "agents" / agent_id
    else:
        if not user_id:
            raise ValueError("user_id is required in server mode")
        root = Path(cfg.agents_dir) / user_id / agent_id

    if ensure_exists:
        root.mkdir(parents=True, exist_ok=True)
    return root


def get_agent_skill_dir(
    agent_id: str,
    *,
    user_id: str = "",
    app_mode: Optional[str] = None,
    ensure_exists: bool = False,
) -> Path:
    skill_dir = get_agent_workspace_root(
        agent_id,
        user_id=user_id,
        app_mode=app_mode,
        ensure_exists=ensure_exists,
    ) / "skills"
    if ensure_exists:
        skill_dir.mkdir(parents=True, exist_ok=True)
    return skill_dir


async def sync_selected_skills_to_workspace(
    agent_id: str,
    agent_config: Dict[str, Any],
    *,
    user_id: str = "",
    role: str = "user",
) -> List[str]:
    """
    将 Agent 配置里选中的 skills 同步到 Agent workspace。

    逻辑对 desktop / server 保持一致，只由 workspace 路径解析决定落点。
    """
    selected_skills = [
        str(name).strip()
        for name in (agent_config.get("availableSkills") or agent_config.get("available_skills") or [])
        if str(name).strip()
    ]
    if not selected_skills:
        return []

    from common.services.skill_service import sync_skill_to_agent

    synced_skills: List[str] = []
    for skill_name in selected_skills:
        try:
            await sync_skill_to_agent(
                skill_name=skill_name,
                agent_id=agent_id,
                user_id=user_id,
                role=role,
            )
            synced_skills.append(skill_name)
        except Exception as e:
            logger.warning(
                f"同步Agent skill到工作空间失败: agent_id={agent_id}, skill={skill_name}, error={e}"
            )

    if synced_skills:
        logger.bind(agent_id=agent_id).info(f"已同步Agent工作空间skills: {synced_skills}")
    return synced_skills


def cleanup_unselected_skills(
    agent_id: str,
    agent_config: Dict[str, Any],
    *,
    user_id: str = "",
    app_mode: Optional[str] = None,
) -> List[str]:
    """
    删除 Agent workspace 中不再被选中的 skills。
    """
    allowed_skills = set(
        str(name).strip()
        for name in (agent_config.get("availableSkills") or agent_config.get("available_skills") or [])
        if str(name).strip()
    )
    if not allowed_skills:
        allowed_skills = set()

    try:
        skill_dir = get_agent_skill_dir(
            agent_id,
            user_id=user_id,
            app_mode=app_mode,
            ensure_exists=False,
        )
    except ValueError:
        logger.warning(f"清理Agent工作空间skills失败: 缺少user_id, agent_id={agent_id}")
        return []

    if not skill_dir.exists() or not skill_dir.is_dir():
        return []

    removed_skills: List[str] = []
    for skill_path in skill_dir.iterdir():
        if not skill_path.is_dir():
            continue
        if skill_path.name in allowed_skills:
            continue
        try:
            import shutil

            shutil.rmtree(skill_path)
            removed_skills.append(skill_path.name)
            logger.info(f"已删除agent工作空间中的skill: {skill_path.name}")
        except Exception as e:
            logger.warning(f"删除skill失败 {skill_path.name}: {e}")

    if removed_skills:
        logger.bind(agent_id=agent_id).info(
            f"清理agent工作空间skills完成，删除: {removed_skills}"
        )
    return removed_skills

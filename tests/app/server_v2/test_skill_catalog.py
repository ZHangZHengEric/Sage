from pathlib import Path

import pytest

from app.server_v2.core.errors import ServerV2Error
from app.server_v2.domain.skills import resolve_artifact_path
from app.server_v2.repositories.skills import MemorySkillStore
from app.server_v2.services.skills import SkillCatalogService


def _service(tmp_path: Path) -> SkillCatalogService:
    return SkillCatalogService(MemorySkillStore(), tmp_path)


@pytest.mark.asyncio
async def test_publish_stores_relative_path_under_data_root(tmp_path: Path):
    service = _service(tmp_path)
    record = await service.publish_markdown(
        name="demo",
        content="---\nname: demo\ndescription: Demo skill\n---\n\n# Demo\n",
        user_id="user_1",
        role="user",
    )
    assert record.artifact_path.startswith("users/user_1/demo/")
    assert not record.artifact_path.startswith("/")
    absolute = resolve_artifact_path(tmp_path, record.artifact_path)
    assert absolute.is_relative_to((tmp_path / "skills").resolve())
    assert (absolute / "SKILL.md").is_file()
    assert absolute == record.absolute_path(tmp_path)


@pytest.mark.asyncio
async def test_user_skill_wins_over_system_and_disabled_source_does_not_fall_back(
    tmp_path: Path,
):
    service = _service(tmp_path)
    system = await service.publish_markdown(
        name="shared",
        content="---\nname: shared\ndescription: system\n---\n# System\n",
        user_id="admin",
        role="admin",
        dimension="system",
    )
    user = await service.publish_markdown(
        name="shared",
        content="---\nname: shared\ndescription: user\n---\n# User\n",
        user_id="user_1",
        role="user",
    )
    bound = await service.bind_agent_skills(
        owner_user_id="user_1", agent_id="main", names=["shared"]
    )
    assert [item.skill_id for item in bound] == [user.skill_id]

    await service.disable(system.skill_id, user_id="admin", role="admin")
    still = await service.bound_skills(owner_user_id="user_1", agent_id="main")
    assert [item.skill_id for item in still] == [user.skill_id]

    await service.disable(user.skill_id, user_id="user_1", role="user")
    later_system = await service.publish_markdown(
        name="shared",
        content="---\nname: shared\ndescription: later system\n---\n# Later\n",
        user_id="admin",
        role="admin",
        dimension="system",
    )
    empty = await service.bound_skills(owner_user_id="user_1", agent_id="main")
    assert empty == []
    assert later_system.skill_id != user.skill_id


@pytest.mark.asyncio
async def test_unknown_bind_name_is_rejected(tmp_path: Path):
    service = _service(tmp_path)
    with pytest.raises(ServerV2Error, match="unknown skill"):
        await service.bind_agent_skills(
            owner_user_id="user_1", agent_id="main", names=["missing"]
        )

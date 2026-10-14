from pathlib import Path

import pytest

from sagents.v2.contracts.errors import SageV2Error
from app.v2.server.skills.records import resolve_artifact_path
from app.v2.server.skills.repository import MemorySkillStore
from app.v2.server.skills.service import SkillCatalogService


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
async def test_same_name_skills_are_owner_scoped_and_disabled_binding_does_not_fall_back(
    tmp_path: Path,
):
    service = _service(tmp_path)
    admin_skill = await service.publish_markdown(
        name="shared",
        content="---\nname: shared\ndescription: admin\n---\n# Admin\n",
        user_id="admin",
        role="admin",
    )
    assert await service.list_visible(user_id="user_1", role="user") == []
    with pytest.raises(SageV2Error, match="unknown skill"):
        await service.bind_agent_skills(
            owner_user_id="user_1", agent_id="main", names=["shared"]
        )
    with pytest.raises(SageV2Error, match="not found"):
        await service.get(admin_skill.skill_id, user_id="user_1", role="user")
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

    await service.disable(admin_skill.skill_id, user_id="admin", role="admin")
    still = await service.bound_skills(owner_user_id="user_1", agent_id="main")
    assert [item.skill_id for item in still] == [user.skill_id]

    await service.disable(user.skill_id, user_id="user_1", role="user")
    later_admin = await service.publish_markdown(
        name="shared",
        content="---\nname: shared\ndescription: later admin\n---\n# Later\n",
        user_id="admin",
        role="admin",
    )
    empty = await service.bound_skills(owner_user_id="user_1", agent_id="main")
    assert empty == []
    assert later_admin.skill_id != user.skill_id


@pytest.mark.asyncio
async def test_unknown_bind_name_is_rejected(tmp_path: Path):
    service = _service(tmp_path)
    with pytest.raises(SageV2Error, match="unknown skill"):
        await service.bind_agent_skills(
            owner_user_id="user_1", agent_id="main", names=["missing"]
        )


@pytest.mark.asyncio
async def test_reimport_repairs_legacy_truncated_description(tmp_path):
    from dataclasses import replace

    service = _service(tmp_path)
    description = "long description " * 100
    content = f"---\nname: demo\ndescription: {description}\n---\n# Body\n"
    record = await service.publish_markdown(
        name="demo", content=content, user_id="user_1", role="user"
    )
    await service.store.publish(replace(record, description=description[:500]))
    repaired = await service.publish_markdown(
        name="demo", content=content, user_id="user_1", role="user"
    )
    assert repaired.description == description.rstrip()
    assert repaired.skill_id == record.skill_id
    again = await service.publish_markdown(
        name="demo", content=content, user_id="user_1", role="user"
    )
    assert again.version_id == repaired.version_id

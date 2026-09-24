"""DatabaseSkillStore visibility must be a SQL predicate, not an in-process filter."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.server_v2.database import Database, DatabaseSettings
from app.server_v2.database.schema import create_host_schema
from app.server_v2.skills.records import AgentSkillBinding, SkillDimension, SkillRecord
from app.server_v2.skills.repository import DatabaseSkillStore


def _record(name: str, *, dimension: SkillDimension, owner: str = "") -> SkillRecord:
    tag = owner or "system"
    return SkillRecord(
        skill_id=f"skill_{dimension}_{tag}_{name}",
        version_id=f"version_{dimension}_{tag}_{name}",
        revision=1,
        dimension=dimension,
        owner_user_id=owner,
        name=name,
        description=f"{name} description",
        artifact_path=f"skills/{dimension}/{tag}/{name}/v1",
        skill_md_sha256="sha256:" + "a" * 64,
        package_sha256="sha256:" + "b" * 64,
        file_count=1,
        total_bytes=10,
        status="active",
    )


@pytest.fixture
async def store(tmp_path):
    database = Database(DatabaseSettings(url=f"sqlite+aiosqlite:///{tmp_path}/host.db"))
    await database.start()
    try:
        await create_host_schema(database)
        yield DatabaseSkillStore(database)
    finally:
        await database.stop()


async def test_list_visible_returns_system_and_own_skills_only(store):
    await store.publish(_record("shared", dimension="system"))
    await store.publish(_record("mine", dimension="user", owner="user_1"))
    await store.publish(_record("theirs", dimension="user", owner="user_2"))

    visible = await store.list_visible(user_id="user_1", role="user")
    assert {item.name for item in visible} == {"shared", "mine"}

    admin = await store.list_visible(user_id="user_1", role="admin")
    assert {item.name for item in admin} == {"shared", "mine", "theirs"}


async def test_list_visible_filters_disabled_and_dimension(store):
    system = await store.publish(_record("shared", dimension="system"))
    await store.publish(_record("mine", dimension="user", owner="user_1"))

    only_user = await store.list_visible(user_id="user_1", role="user", dimension="user")
    assert [item.name for item in only_user] == ["mine"]

    await store.disable(system.skill_id)
    remaining = await store.list_visible(user_id="user_1", role="user")
    assert [item.name for item in remaining] == ["mine"]


async def test_list_visible_follows_the_current_version_after_republish(store):
    first = _record("mine", dimension="user", owner="user_1")
    await store.publish(first)
    await store.publish(
        replace(
            first,
            version_id="version_user_user_1_mine_2",
            revision=2,
            artifact_path="skills/user/user_1/mine/v2",
        )
    )

    visible = await store.list_visible(user_id="user_1", role="user")
    assert [(item.name, item.revision) for item in visible] == [("mine", 2)]


async def test_bindings_are_scoped_to_one_agent(store):
    await store.replace_bindings(
        owner_user_id="user_1",
        agent_id="main",
        bindings=[
            AgentSkillBinding(
                owner_user_id="user_1",
                agent_id="main",
                skill_name="mine",
                source_skill_id=None,
                position=1,
            )
        ],
    )

    bindings = await store.list_bindings(owner_user_id="user_1", agent_id="main")
    assert [item.skill_name for item in bindings] == ["mine"]
    assert await store.list_bindings(owner_user_id="user_1", agent_id="other") == []

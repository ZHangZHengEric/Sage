"""DatabaseSkillStore visibility must be a SQL predicate, not an in-process filter."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.v2.server.database import Database, DatabaseSettings
from app.v2.server.database.schema import create_host_schema
from app.v2.server.skills.records import AgentSkillBinding, SkillRecord
from app.v2.server.skills.repository import DatabaseSkillStore
from sagents.v2.contracts.errors import SageV2Error


def _record(name: str, *, owner: str = "user_1") -> SkillRecord:
    return SkillRecord(
        skill_id=f"skill_{owner}_{name}",
        version_id=f"version_{owner}_{name}",
        revision=1,
        owner_user_id=owner,
        name=name,
        description=f"{name} description",
        artifact_path=f"users/{owner}/{name}/v1",
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


async def test_list_visible_returns_own_skills_only(store):
    await store.publish(_record("shared", owner="admin"))
    await store.publish(_record("mine", owner="user_1"))
    await store.publish(_record("theirs", owner="user_2"))

    visible = await store.list_visible(user_id="user_1", role="user")
    assert {item.name for item in visible} == {"mine"}

    admin = await store.list_visible(user_id="user_1", role="admin")
    assert {item.name for item in admin} == {"shared", "mine", "theirs"}


async def test_list_visible_filters_disabled(store):
    first = await store.publish(_record("first"))
    await store.publish(_record("mine"))
    await store.disable(first.skill_id)
    remaining = await store.list_visible(user_id="user_1", role="user")
    assert [item.name for item in remaining] == ["mine"]


async def test_list_visible_follows_the_current_version_after_republish(store):
    first = _record("mine", owner="user_1")
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


async def test_import_publish_compares_version_before_switching(store):
    first = await store.publish(_record("one"), expected_version_id="")
    second = replace(first, version_id="one-v2", revision=2)
    with pytest.raises(SageV2Error):
        await store.publish(second, expected_version_id="stale")
    assert (await store.get(first.skill_id)).version_id == first.version_id
    await store.publish(second, expected_version_id=first.version_id)
    assert (await store.get(first.skill_id)).version_id == second.version_id
    with pytest.raises(SageV2Error):
        await store.publish(replace(second, version_id="one-v3"), expected_version_id=first.version_id)


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


async def test_long_description_survives_database_catalog_round_trip(store):
    description = "完整的技能描述" * 2000
    record = replace(_record("long"), description=description)
    await store.publish(record)
    visible = await store.list_visible(user_id="user_1", role="user")
    assert visible[0].description == description


async def test_same_name_is_unique_per_owner(store):
    mine = await store.publish(_record("demo", owner="user_1"))
    theirs = await store.publish(_record("demo", owner="user_2"))
    assert mine.skill_id != theirs.skill_id
    assert [
        item.skill_id
        for item in await store.list_visible(user_id="user_1", role="user")
    ] == [mine.skill_id]
    updated = await store.publish(
        replace(mine, skill_id="new_id", version_id="v2", revision=2)
    )
    assert updated.skill_id == mine.skill_id
    assert (await store.get(theirs.skill_id)).version_id == theirs.version_id

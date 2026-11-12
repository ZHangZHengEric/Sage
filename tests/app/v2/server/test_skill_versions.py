"""Skill history is immutable, owner scoped, and usable by pinned Agents."""
import pytest

from app.v2.server.database import Database, DatabaseSettings
from app.v2.server.database.schema import create_host_schema
from app.v2.server.skills.files import inspect_skill_directory
from app.v2.server.skills.repository import DatabaseSkillStore, MemorySkillStore
from app.v2.server.skills.service import SkillCatalogService
from app.v2.server.skills.versions import SkillVersionService
from sagents.v2.contracts.errors import SageV2Error


@pytest.fixture(params=["memory", "sql"])
async def catalog(request, tmp_path):
    database = Database(DatabaseSettings(url=f"sqlite+aiosqlite:///{tmp_path}/host.db"))
    await database.start()
    await create_host_schema(database)
    store = DatabaseSkillStore(database) if request.param == "sql" else MemorySkillStore()
    try:
        yield SkillCatalogService(store, tmp_path)
    finally:
        await database.stop()


async def publish(catalog, text, *, name="demo", user="alice"):
    return await catalog.publish_markdown(name=name,
        content=f"---\nname: {name}\ndescription: {text}\n---\n# {text}\n",
        user_id=user, role="user")


async def test_history_keeps_metadata_and_rollback_creates_new_revision(catalog):
    first = await publish(catalog, "First")
    second = await publish(catalog, "Second")
    versions = SkillVersionService(catalog)
    history = await versions.list(first.skill_id, user_id="alice", role="user", limit=1)
    assert [item.description for item in history] == ["Second"]
    older = await versions.list(first.skill_id, user_id="alice", role="user", before_revision=2)
    assert [(item.version_id, item.description) for item in older] == [(first.version_id, "First")]
    restored = await versions.rollback(first.skill_id, first.version_id,
        expected_version_id=second.version_id, user_id="alice", role="user")
    assert restored.skill_id == first.skill_id
    assert restored.version_id not in {first.version_id, second.version_id}
    assert restored.revision == 3 and restored.description == "First"
    assert (first.absolute_path(catalog.data_root) / "SKILL.md").read_text().endswith("# First\n")
    with pytest.raises(SageV2Error):
        await versions.rollback(first.skill_id, first.version_id,
            expected_version_id=second.version_id, user_id="alice", role="user")


async def test_history_cannot_read_another_owner_or_another_skills_version(catalog):
    mine = await publish(catalog, "Mine")
    theirs = await publish(catalog, "Secret", user="bob")
    versions = SkillVersionService(catalog)
    with pytest.raises(SageV2Error):
        await versions.list(theirs.skill_id, user_id="alice", role="user")
    with pytest.raises(SageV2Error):
        await versions.get(mine.skill_id, theirs.version_id, user_id="alice", role="user")
    assert (await versions.get(theirs.skill_id, theirs.version_id,
        user_id="admin", role="admin")).description == "Secret"


async def test_diff_covers_added_removed_text_and_binary_files(catalog, tmp_path):
    directory = tmp_path / "source"
    directory.mkdir()
    (directory / "SKILL.md").write_text("# First\n")
    (directory / "old.txt").write_text("removed\n")
    (directory / "image.bin").write_bytes(b"\x00old")
    first = await catalog.publish_package(inspect_skill_directory(directory), owner_user_id="alice")
    (directory / "SKILL.md").write_text("# Second\n")
    (directory / "old.txt").unlink()
    (directory / "new.txt").write_text("added\n")
    (directory / "large.txt").write_text("x" * 33000)
    (directory / "image.bin").write_bytes(b"\x00new")
    second = await catalog.publish_package(inspect_skill_directory(directory), owner_user_id="alice")
    result = await SkillVersionService(catalog).diff(first.skill_id, first.version_id, second.version_id,
        user_id="alice", role="user")
    changed = {item["path"]: item for item in result["files"]}
    assert changed["old.txt"]["status"] == "removed"
    assert changed["new.txt"]["status"] == "added"
    assert "-# First" in changed["SKILL.md"]["diff"]
    assert "+# Second" in changed["SKILL.md"]["diff"]
    assert changed["image.bin"]["binary"] is True
    assert changed["large.txt"]["truncated"] is True
    assert changed["large.txt"]["diff"] == ""


async def test_pinned_binding_survives_rebind_and_does_not_follow_updates(catalog):
    first = await publish(catalog, "First")
    versions = SkillVersionService(catalog)
    await catalog.bind_agent_skills(owner_user_id="alice", agent_id="agent", names=["demo"])
    await versions.bind_version("agent", first.skill_id, first.version_id, user_id="alice")
    second = await publish(catalog, "Second")
    await catalog.bind_agent_skills(owner_user_id="alice", agent_id="agent", names=["demo"])
    bound = await catalog.bound_skills(owner_user_id="alice", agent_id="agent")
    assert [(item.version_id, item.pinned) for item in bound] == [(first.version_id, True)]
    from app.v2.server.skills.runtime import CatalogSkillProvider
    provider = CatalogSkillProvider(tuple(bound), catalog.data_root,
        latest_record=lambda record: catalog.get(record.skill_id, user_id="alice", role="user"))
    assert (await provider.fetch_latest("demo", run_id="run")).descriptor.version == first.version_id
    bundled = CatalogSkillProvider(tuple(bound), catalog.data_root,
        package_files={"skills/demo/SKILL.md": "---\nname: demo\ndescription: Bundled\n---\n# Package\n"})
    assert (await bundled.fetch("demo", run_id="run")).descriptor.version == first.version_id
    await versions.bind_version("agent", first.skill_id, None, user_id="alice")
    assert (await catalog.bound_skills(owner_user_id="alice", agent_id="agent"))[0].version_id == second.version_id
    # A version from a different skill must never be accepted as a pin.
    other = await publish(catalog, "Other", name="other")
    with pytest.raises(SageV2Error):
        await versions.bind_version("agent", first.skill_id, other.version_id, user_id="alice")
    await catalog.disable(first.skill_id, user_id="alice", role="user")
    assert await catalog.bound_skills(owner_user_id="alice", agent_id="agent") == []


async def test_reimport_after_disable_keeps_revision_order(catalog):
    first = await publish(catalog, "First")
    await catalog.disable(first.skill_id, user_id="alice", role="user")
    second = await publish(catalog, "Second")
    assert second.skill_id == first.skill_id
    assert second.revision == 2
    assert len(await SkillVersionService(catalog).list(second.skill_id, user_id="alice", role="user")) == 2


async def test_legacy_skill_schema_upgrade_preserves_history_and_bindings(tmp_path):
    database = Database(DatabaseSettings(url=f"sqlite+aiosqlite:///{tmp_path}/legacy.db"))
    await database.start()
    try:
        async with database._engine.begin() as connection:
            await connection.exec_driver_sql("CREATE TABLE skill_versions (version_id VARCHAR(64) PRIMARY KEY, skill_id VARCHAR(64), revision INTEGER, artifact_path VARCHAR(512), skill_md_sha256 VARCHAR(64), package_sha256 VARCHAR(80), file_count INTEGER, total_bytes INTEGER, created_at VARCHAR(64))")
            await connection.exec_driver_sql("CREATE TABLE agent_skill_selections (owner_user_id VARCHAR(128), agent_id VARCHAR(191), skill_name VARCHAR(191), source_skill_id VARCHAR(64), position INTEGER, PRIMARY KEY (owner_user_id,agent_id,skill_name))")
            await connection.exec_driver_sql("INSERT INTO agent_skill_selections VALUES ('alice','agent','demo','skill_demo',0)")
            await connection.exec_driver_sql("INSERT INTO skill_versions VALUES ('v1','skill_demo',1,'users/alice/demo/v1','hash','hash',1,10,'2026-01-01')")
        await create_host_schema(database)
        await create_host_schema(database)
        store = DatabaseSkillStore(database)
        binding = (await store.list_bindings(owner_user_id="alice", agent_id="agent"))[0]
        assert binding.source_version_id is None
        async with database._engine.connect() as connection:
            result = await connection.exec_driver_sql("SELECT description FROM skill_versions WHERE version_id='v1'")
            assert result.one() == (None,)
    finally:
        await database.stop()


async def test_sql_pin_survives_catalog_edits_and_store_recreation(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from app.v2.server.skills.agent_guidance import _lock
    from app.v2.server.catalog.repository import DatabaseCatalogStore
    from app.v2.server.catalog.service import CatalogService
    from app.v2.server.identity.orm import UserRow
    database = Database(DatabaseSettings(url=f"sqlite+aiosqlite:///{tmp_path}/catalog.db"))
    await database.start()
    await create_host_schema(database)
    try:
        async with database.transaction() as session:
            session.add(UserRow(user_id="alice", username="alice", password_hash="test", role="user"))
        store = DatabaseCatalogStore(database)
        agent = (await store.get("alice")).agents[0]
        catalog = SkillCatalogService(DatabaseSkillStore(database), tmp_path)
        service = CatalogService(store, skills=catalog, mcp_plugins=SimpleNamespace(), a2a_plugins=SimpleNamespace())
        first = await publish(catalog, "First")
        await service.bind_agent_skills("alice", agent.id, ["demo"])
        # A concurrent ZIP/workspace sync must finish before changing its policy.
        async with _lock(catalog.guidance_locks, ("alice", agent.id)):
            pending = asyncio.create_task(service.bind_agent_skill_version("alice", agent.id, first.skill_id, first.version_id))
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(pending), timeout=0.05)
        await asyncio.wait_for(pending, timeout=2)
        second = await publish(catalog, "Second")
        other_catalog = SkillCatalogService(DatabaseSkillStore(database), tmp_path)
        other_service = CatalogService(store, skills=other_catalog, mcp_plugins=None, a2a_plugins=None)
        replace_bindings = catalog.store.replace_bindings

        async def interleave(**kwargs):
            await other_service.bind_agent_skill_version("alice", agent.id, second.skill_id, second.version_id)
            return await replace_bindings(**kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(catalog.store, "replace_bindings", interleave)
            await service.bind_agent_skills(
                "alice", agent.id, ["demo"], skill_visibility={"default_visible_skills": ["demo"]},
            )
        restored = SkillCatalogService(DatabaseSkillStore(database), tmp_path)
        assert (await restored.bound_skills(owner_user_id="alice", agent_id=agent.id))[0].version_id == second.version_id
        assert (await DatabaseCatalogStore(database).get_agent("alice", agent.id)).skills == ["demo"]
    finally:
        await database.stop()


async def test_sql_skill_bindings_and_visibility_roll_back_together(tmp_path, monkeypatch):
    from app.v2.server.catalog.repository import DatabaseCatalogStore
    from app.v2.server.catalog.service import CatalogService
    from app.v2.server.identity.orm import UserRow
    from app.v2.server.packages.repository import DatabasePackageStore

    database = Database(DatabaseSettings(url=f"sqlite+aiosqlite:///{tmp_path}/catalog.db"))
    await database.start()
    await create_host_schema(database)
    try:
        async with database.transaction() as session:
            session.add(UserRow(user_id="alice", username="alice", password_hash="test", role="user"))
        store = DatabaseCatalogStore(database)
        agent = (await store.get("alice")).agents[0]
        catalog = SkillCatalogService(DatabaseSkillStore(database), tmp_path)
        service = CatalogService(store, skills=catalog, mcp_plugins=None, a2a_plugins=None)
        await publish(catalog, "First")
        await service.bind_agent_skills(
            "alice", agent.id, ["demo"],
            skill_visibility={"default_visible_skills": ["demo"], "default_visible_skills_limit": 30},
        )
        before = await store.get_agent("alice", agent.id)
        assert before.package_bundle.manifest.agents[agent.id].default_visible_skills_limit == 30

        async def fail_save(self, session, owner, bundle):
            await session.flush()
            raise RuntimeError("injected package write failure")

        with monkeypatch.context() as patch:
            patch.setattr(DatabasePackageStore, "save_in_transaction", fail_save)
            with pytest.raises(RuntimeError, match="injected package write failure"):
                await service.bind_agent_skills(
                    "alice", agent.id, [], skill_visibility={"default_visible_skills": []},
                )

        after = await store.get_agent("alice", agent.id)
        assert after.package_bundle.content_hash == before.package_bundle.content_hash
        assert [item.name for item in await catalog.bound_skills(owner_user_id="alice", agent_id=agent.id)] == ["demo"]
    finally:
        await database.stop()



async def test_sql_combined_editor_save_is_atomic(tmp_path, monkeypatch):
    from app.v2.server.catalog.repository import DatabaseCatalogStore
    from app.v2.server.catalog.service import CatalogService
    from app.v2.server.identity.orm import UserRow
    from app.v2.server.packages.repository import DatabasePackageStore

    database = Database(DatabaseSettings(url=f"sqlite+aiosqlite:///{tmp_path}/editor.db"))
    await database.start()
    await create_host_schema(database)
    try:
        async with database.transaction() as session:
            session.add(UserRow(user_id="alice", username="alice", password_hash="test", role="user"))
        store = DatabaseCatalogStore(database)
        catalog = SkillCatalogService(DatabaseSkillStore(database), tmp_path)
        service = CatalogService(store, skills=catalog, mcp_plugins=None, a2a_plugins=None)
        await publish(catalog, "Guide")
        agent = await service.create_agent("alice", {
            "name": "Before", "skill_bindings": {"names": ["demo"], "default_visible_skills": ["demo"]},
        })

        async def fail_save(self, session, owner, bundle):
            await session.flush()
            raise RuntimeError("package write failed")

        change = {"name": "After", "skill_bindings": {"names": [], "default_visible_skills": []}}
        with monkeypatch.context() as patch:
            patch.setattr(DatabasePackageStore, "save_in_transaction", fail_save)
            with pytest.raises(RuntimeError, match="package write failed"):
                await service.update_agent("alice", agent.id, change)

        assert (await store.get_agent("alice", agent.id)).package_bundle.content_hash == agent.package_bundle.content_hash
        assert [item.name for item in await catalog.bound_skills(owner_user_id="alice", agent_id=agent.id)] == ["demo"]
        other = CatalogService(
            DatabaseCatalogStore(database), skills=catalog, mcp_plugins=None, a2a_plugins=None,
        )
        update_agent = store.update_agent

        async def save_after_skill_change(user_id, record, **kwargs):
            await other.update_agent(user_id, record.id, change)
            await update_agent(user_id, record, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(store, "update_agent", save_after_skill_change)
            with pytest.raises(SageV2Error) as caught:
                await service.update_agent("alice", agent.id, {"name": "Stale"})
            assert caught.value.info.code == "server.catalog.package_conflict"

        saved = await store.get_agent("alice", agent.id)
        assert saved.name == "After" and saved.skills == []
        assert await catalog.bound_skills(owner_user_id="alice", agent_id=agent.id) == []

        manifest = saved.package_bundle.manifest
        embedded = saved.package_bundle.model_copy(update={
            "manifest": manifest.model_copy(update={
                "metadata": manifest.metadata.model_copy(update={"version": "embedded-test"}),
            }),
            "files": {"skills/local/SKILL.md": "---\nname: local\ndescription: Local guide\n---\nGuide"},
        })
        await service.apply_rsi_package("alice", agent.id, embedded, saved.package_bundle.content_hash)
        updated = await service.update_agent("alice", agent.id, {
            "name": "Embedded",
            "skill_bindings": {"names": ["local"], "default_visible_skills": ["local"]},
        })
        assert updated.skills == ["local"]
        assert await catalog.bound_skills(owner_user_id="alice", agent_id=agent.id) == []
        await service.bind_agent_skills(
            "alice", agent.id, ["local"], skill_visibility={"default_visible_skills_limit": 1},
        )
        detail = await service.get_agent("alice", agent.id)
        assert detail["default_visible_skills"] == ("local",)
        assert detail["default_visible_skills_limit"] == 1
    finally:
        await database.stop()

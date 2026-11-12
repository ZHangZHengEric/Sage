from pathlib import Path

import pytest
from sagents.v2.skill import (
    AvailableSkillsContextProvider,
)
from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.errors import SageV2Error

from app.v2.server.skills.records import workspace_skill_path
from app.v2.server.skills.repository import MemorySkillStore
from app.v2.server.skills.runtime import CatalogSkillProvider
from app.v2.server.skills.service import SkillCatalogService


def _command() -> StartRun:
    return StartRun(
        agent_id="main",
        input=(InputItem(role="user", content=(TextBlock(text="hello"),)),),
        resolved_spec_hash="sha256:test",
        idempotency_key="start_1",
    )


async def _bound_provider(tmp_path: Path):
    catalog = SkillCatalogService(MemorySkillStore(), tmp_path)
    record = await catalog.publish_markdown(
        name="demo",
        content="---\nname: demo\ndescription: Demo skill\n---\n\n# Demo\n",
        user_id="user_1",
        role="user",
    )
    await catalog.bind_agent_skills(
        owner_user_id="user_1", agent_id="main", names=["demo"]
    )
    records = tuple(await catalog.bound_skills(owner_user_id="user_1", agent_id="main"))
    provider = CatalogSkillProvider(records, tmp_path)
    return catalog, record, provider


@pytest.mark.asyncio
async def test_listing_available_skills_does_not_copy_to_workspace(tmp_path: Path):
    _, record, provider = await _bound_provider(tmp_path)
    listed = await provider.list_skills(run_id="run_1")
    segments = await AvailableSkillsContextProvider(provider).segments(
        _command(), run_id="run_1"
    )

    assert [item.name for item in listed] == ["demo"]
    assert "Demo skill" in segments[0].content
    workspace = workspace_skill_path(tmp_path, "user_1", "agent_1", "demo")
    assert not workspace.exists()
    assert record.artifact_path.startswith("users/user_1/demo/")


@pytest.mark.asyncio
async def test_catalog_fetch_returns_the_admitted_immutable_bundle(
    tmp_path: Path,
):
    _, record, provider = await _bound_provider(tmp_path)
    bundle = await provider.fetch("demo", run_id="run_1")
    workspace = workspace_skill_path(tmp_path, "user_1", "agent_1", "demo")

    assert not workspace.exists()
    assert bundle.content_hash == record.package_sha256
    assert bundle.files["SKILL.md"] == (record.absolute_path(tmp_path) / "SKILL.md").read_bytes()


@pytest.mark.asyncio
async def test_workspace_edit_is_copy_on_write(tmp_path: Path):
    catalog, record, _ = await _bound_provider(tmp_path)
    path = await catalog.write_workspace_skill(
        user_id="user_1", agent_id="agent_1",
        name="demo",
        content="---\nname: demo\ndescription: edited\n---\n\n# Edited\n",
    )
    workspace = workspace_skill_path(tmp_path, "user_1", "agent_1", "demo")
    assert path == workspace
    assert workspace.is_dir()
    assert record.absolute_path(tmp_path).is_dir()
    assert "Edited" not in (record.absolute_path(tmp_path) / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert await catalog.workspace_status(user_id="user_1", agent_id="agent_1", name="demo") == "modified"


@pytest.mark.asyncio
async def test_auto_sync_can_fetch_current_version_without_expanding_admitted_identity(
    tmp_path,
):
    catalog, first, _ = await _bound_provider(tmp_path)

    async def latest(record):
        return await catalog.get(record.skill_id, user_id="user_1", role="user")

    provider = CatalogSkillProvider((first,), tmp_path, latest_record=latest)
    updated = await catalog.publish_markdown(
        name="demo",
        content="---\nname: demo\ndescription: Demo\n---\n\nUpdated",
        user_id="user_1",
        role="user",
    )
    assert updated.skill_id == first.skill_id
    assert (
        await provider.fetch("demo", run_id="same")
    ).content_hash == first.package_sha256
    assert (
        await provider.fetch_latest("demo", run_id="same")
    ).content_hash == updated.package_sha256
    with pytest.raises(SageV2Error):
        await provider.fetch_latest("unadmitted", run_id="same")


@pytest.mark.asyncio
async def test_search_uses_only_frozen_catalog_and_package_markdown(tmp_path, monkeypatch):
    _, record, provider = await _bound_provider(tmp_path)

    async def reject_fetch(*args, **kwargs):
        pytest.fail("search fetched a complete Skill bundle")

    monkeypatch.setattr(provider, "fetch", reject_fetch)
    allowed = frozenset({"demo", "unknown"})
    matches = await provider.search_skills("Demo", run_id="run_1", allowed_names=allowed, limit=5)
    assert [(item.name, item.version) for item in matches] == [("demo", record.version_id)]
    assert not await provider.search_skills(
        "Demo", run_id="other", allowed_names=frozenset({"unknown"}), limit=5
    )
    package_provider = CatalogSkillProvider((record,), tmp_path, package_files={
        "skills/demo/SKILL.md": "---\nname: demo\ndescription: Package demo\n---\nchromatography",
        "skills/demo/references/data.md": "neverindexthis",
    })
    matches = await package_provider.search_skills(
        "chromatography", run_id="run_1", allowed_names=allowed, limit=5
    )
    assert [(item.name, item.source_id) for item in matches] == [("demo", "agent-package")]
    assert not await package_provider.search_skills(
        "neverindexthis", run_id="run_1", allowed_names=allowed, limit=5
    )


@pytest.mark.asyncio
async def test_search_rejects_body_that_differs_from_the_frozen_artifact(tmp_path):
    _, record, provider = await _bound_provider(tmp_path)
    path = record.absolute_path(tmp_path) / "SKILL.md"
    original = path.read_text(encoding="utf-8")
    path.write_text(original.replace("# Demo", "# Fake"), encoding="utf-8")
    with pytest.raises(SageV2Error) as caught:
        await provider.search_skills(
            "fake", run_id="frozen", allowed_names=frozenset({"demo"}), limit=1,
        )
    assert caught.value.info.code == "skill.artifact_changed"
    path.write_text(original, encoding="utf-8")
    results = await provider.search_skills(
        "demo", run_id="frozen", allowed_names=frozenset({"demo"}), limit=1,
    )
    assert [item.version for item in results] == [record.version_id]


@pytest.mark.asyncio
async def test_server_can_restore_a_loaded_version_newer_than_the_admitted_snapshot(tmp_path):
    catalog, first, _ = await _bound_provider(tmp_path)

    async def publish(text):
        return await catalog.publish_markdown(
            name="demo", content=f"---\nname: demo\ndescription: Guide\n---\n{text}",
            user_id="user_1", role="user",
        )

    async def latest(record):
        return await catalog.get(record.skill_id, user_id="user_1", role="user")

    async def version_record(version):
        return next(iter(await catalog.store.get_versions([version])), None)

    source = CatalogSkillProvider(
        (first,), tmp_path, latest_record=latest, version_record=version_record,
    )
    second = await publish("loaded version")
    loaded = await source.fetch_latest("demo", run_id="old")
    assert loaded.descriptor.version == second.version_id
    await publish("new head")
    restored = await source.fetch_for_restore("demo", run_id="old", version=loaded.descriptor.version)
    assert restored.content_hash == loaded.content_hash
    assert restored.descriptor.version == loaded.descriptor.version

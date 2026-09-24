from pathlib import Path

import pytest
from sagents.v2.skill import (
    AvailableSkillsContextProvider,
    InMemorySkillActivationRepository,
    SkillLoader,
)
from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import TextBlock

from app.server_v2.skills.records import workspace_skill_path
from app.server_v2.skills.repository import MemorySkillStore
from app.server_v2.skills.runtime import (
    CatalogSkillProvider,
    ReadThroughSkillWorkspace,
)
from app.server_v2.skills.service import SkillCatalogService


def _command() -> StartRun:
    return StartRun(
        agent_id="main",
        input=(InputItem(role="user", content=(TextBlock(text="hello"),)),),
        resolved_spec_hash="sha256:test",
        idempotency_key="start_1",
    )


async def _bound_loader(tmp_path: Path):
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
    workspace = ReadThroughSkillWorkspace(tmp_path, "user_1", records)
    loader = SkillLoader(
        catalog=provider,
        source=provider,
        workspace=workspace,
        activations=InMemorySkillActivationRepository(),
    )
    return catalog, record, provider, loader


@pytest.mark.asyncio
async def test_listing_available_skills_does_not_copy_to_workspace(tmp_path: Path):
    _, record, provider, loader = await _bound_loader(tmp_path)
    listed = await provider.list_skills(run_id="run_1")
    segments = await AvailableSkillsContextProvider(provider).segments(
        _command(), run_id="run_1"
    )

    assert [item.name for item in listed] == ["demo"]
    assert "Demo skill" in segments[0].content
    workspace = workspace_skill_path(tmp_path, "user_1", "demo")
    assert not workspace.exists()
    assert await loader.loaded(run_id="run_1") == ()
    assert record.artifact_path.startswith("users/user_1/demo/")


@pytest.mark.asyncio
async def test_load_skill_materializes_content_addressed_workspace_bundle(
    tmp_path: Path,
):
    _, record, _, loader = await _bound_loader(tmp_path)
    loaded = await loader.load("demo", run_id="run_1")
    workspace = workspace_skill_path(tmp_path, "user_1", "demo")

    assert loaded.workspace_path.startswith("/workspace/skills/.catalog/demo/")
    assert not workspace.exists()
    relative = loaded.workspace_path.removeprefix("/workspace/")
    materialized = tmp_path / "tenants" / "user_1" / "workspace" / relative
    assert materialized.is_dir()
    assert (materialized / "SKILL.md").is_file()
    assert materialized != record.absolute_path(tmp_path)
    assert "# Demo" in loaded.instructions


@pytest.mark.asyncio
async def test_workspace_edit_is_copy_on_write(tmp_path: Path):
    catalog, record, provider, loader = await _bound_loader(tmp_path)
    path = await catalog.write_workspace_skill(
        user_id="user_1",
        name="demo",
        content="---\nname: demo\ndescription: edited\n---\n\n# Edited\n",
    )
    workspace = workspace_skill_path(tmp_path, "user_1", "demo")
    assert path == workspace
    assert workspace.is_dir()
    assert record.absolute_path(tmp_path).is_dir()
    assert "Edited" not in (record.absolute_path(tmp_path) / "SKILL.md").read_text(
        encoding="utf-8"
    )

    loaded = await loader.load("demo", run_id="run_1")
    assert loaded.workspace_path == "/workspace/skills/demo"
    assert await catalog.workspace_status(user_id="user_1", name="demo") == "modified"


@pytest.mark.asyncio
async def test_workspace_rejects_bundle_without_an_admitted_record(tmp_path: Path):
    _, _, provider, _ = await _bound_loader(tmp_path)
    bundle = await provider.fetch("demo", run_id="run_1")
    workspace = ReadThroughSkillWorkspace(tmp_path, "user_1", ())

    with pytest.raises(SageV2Error) as caught:
        await workspace.materialize(
            bundle,
            run_id="run_1",
            destination="/workspace/skills/demo",
        )

    assert caught.value.info.code == "skill.not_found"

from __future__ import annotations

import asyncio
import hashlib

import pytest

from sagents.v2.skill import (
    ActiveSkillsContextProvider,
    AvailableSkillsContextProvider,
    FilteredSkillCatalog,
    InMemorySkillActivationRepository,
    InMemorySkillProvider,
    InMemorySkillWorkspace,
    InvocationGrantSkillCatalog,
    SkillBundle,
    SkillDescriptor,
    SkillLoader,
)
from sagents.v2.skill.plugins.filesystem import FilesystemSkillProvider
from sagents.v2.tool.plugins.skill import SkillToolPlugin
from sagents.v2.contracts.commands import InputItem, RunConfig, StartRun
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import (
    ActorRef,
    PrincipalType,
    RequestContext,
)
from sagents.v2.tool import ToolCall


CONTEXT = RequestContext(
    actor=ActorRef(principal_id="agent_1", principal_type=PrincipalType.AGENT)
)


def bundle(name: str, body: str) -> SkillBundle:
    files = {
        "SKILL.md": body.encode(),
        "references/example.md": b"example",
    }
    digest = hashlib.sha256()
    for path, content in sorted(files.items()):
        digest.update(path.encode())
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return SkillBundle(
        descriptor=SkillDescriptor(
            name=name,
            description=f"{name} description",
            source_id="test",
        ),
        files=files,
        content_hash=f"sha256:{digest.hexdigest()}",
    )


def command() -> StartRun:
    return StartRun(
        agent_id="agent_1",
        input=(InputItem(role="user", content=(TextBlock(text="hello"),)),),
        resolved_spec_hash="sha256:test",
        idempotency_key="start_1",
    )


def loader_for(*bundles):
    provider = InMemorySkillProvider(tuple(bundles))
    workspace = InMemorySkillWorkspace()
    activations = InMemorySkillActivationRepository()
    loader = SkillLoader(
        catalog=provider,
        source=provider,
        workspace=workspace,
        activations=activations,
    )
    return provider, workspace, activations, loader


@pytest.mark.asyncio
async def test_discovery_and_context_metadata_never_copy_skill_to_workspace():
    provider, workspace, _, loader = loader_for(
        bundle("alpha", "# Alpha"), bundle("beta", "# Beta")
    )

    listed = await provider.list_skills(run_id="run_1")
    segments = await AvailableSkillsContextProvider(provider).segments(
        command(), run_id="run_1"
    )

    assert [value.name for value in listed] == ["alpha", "beta"]
    assert "alpha description" in segments[0].content
    assert provider.fetches == []
    assert workspace.materializations == []
    assert await loader.loaded(run_id="run_1") == ()


@pytest.mark.asyncio
async def test_only_explicit_load_fetches_and_copies_the_selected_skill_once():
    provider, workspace, _, loader = loader_for(
        bundle("alpha", "# Alpha"), bundle("beta", "# Beta")
    )

    loaded = await loader.load("beta", run_id="run_1")
    repeated = await loader.load("beta", run_id="run_1")

    assert loaded == repeated
    assert loaded.workspace_path == "/workspace/skills/beta"
    assert provider.fetches == [("run_1", "beta")]
    assert workspace.materializations == [("run_1", "beta", "/workspace/skills/beta")]
    assert "/workspace/skills/alpha" not in workspace.files
    active = await ActiveSkillsContextProvider(loader).segments(
        command(), run_id="run_1"
    )
    assert len(active) == 1
    assert "# Beta" in active[0].content


@pytest.mark.asyncio
async def test_concurrent_duplicate_load_is_single_copy_and_single_fetch():
    provider, workspace, _, loader = loader_for(bundle("alpha", "# Alpha"))

    values = await asyncio.gather(
        *(loader.load("alpha", run_id="run_1") for _ in range(20))
    )

    assert all(value == values[0] for value in values)
    assert provider.fetches == [("run_1", "alpha")]
    assert workspace.materializations == [("run_1", "alpha", "/workspace/skills/alpha")]


@pytest.mark.asyncio
async def test_active_skill_budget_evicts_oldest_but_keeps_at_least_one():
    provider = InMemorySkillProvider(
        (bundle("alpha", "A" * 100), bundle("beta", "B" * 100))
    )
    workspace = InMemorySkillWorkspace()
    activations = InMemorySkillActivationRepository()
    loader = SkillLoader(
        catalog=provider,
        source=provider,
        workspace=workspace,
        activations=activations,
        max_active_tokens=150,
        token_estimator=len,
    )

    await loader.load("alpha", run_id="run_1")
    await loader.load("beta", run_id="run_1")

    assert [value.descriptor.name for value in await loader.loaded(run_id="run_1")] == [
        "beta"
    ]


@pytest.mark.asyncio
async def test_filtered_catalog_prevents_loading_outside_manifest_ceiling():
    provider, workspace, activations, _ = loader_for(
        bundle("alpha", "# Alpha"), bundle("beta", "# Beta")
    )
    loader = SkillLoader(
        catalog=FilteredSkillCatalog(provider, ("alpha",)),
        source=provider,
        workspace=workspace,
        activations=activations,
    )

    with pytest.raises(SageV2Error) as denied:
        await loader.load("beta", run_id="run_1")

    assert denied.value.info.code == "skill.not_enabled"
    assert provider.fetches == []
    assert workspace.materializations == []


@pytest.mark.asyncio
async def test_durable_run_skill_grant_blocks_unselected_skill_materialization():
    provider, workspace, activations, _ = loader_for(
        bundle("alpha", "# Alpha"), bundle("beta", "# Beta")
    )

    async def command_reader(run_id):
        del run_id
        return command().model_copy(
            update={"config": RunConfig(enabled_skills=("alpha",))}
        )

    loader = SkillLoader(
        catalog=InvocationGrantSkillCatalog(provider, command_reader),
        source=provider,
        workspace=workspace,
        activations=activations,
    )

    assert [
        value.name for value in await loader.catalog.list_skills(run_id="run_1")
    ] == ["alpha"]
    with pytest.raises(SageV2Error) as denied:
        await loader.load("beta", run_id="run_1")

    assert denied.value.info.code == "skill.not_enabled"
    assert provider.fetches == []
    assert workspace.materializations == []


@pytest.mark.asyncio
async def test_load_skill_exposes_a_strict_native_v2_schema_and_loads_lazily():
    provider, workspace, _, loader = loader_for(bundle("alpha", "# Alpha"))
    plugin = SkillToolPlugin(loader, language="en")
    tool = plugin.executor
    definition = plugin.definitions[0]

    assert definition.name == "load_skill"
    assert definition.strict is True
    assert definition.input_schema == {
        "type": "object",
        "properties": {
            "skill_name": {
                "type": "string",
                "minLength": 1,
                "description": "Exact name of the enabled skill to load.",
            }
        },
        "required": ["skill_name"],
        "additionalProperties": False,
    }

    result = await tool.execute(
        ToolCall(
            tool_call_id="call_1",
            tool_name="load_skill",
            arguments={"skill_name": "alpha"},
            operation_id="operation_1",
            idempotency_key="key_1",
            owner_run_id="run_1",
        ),
        CONTEXT,
    )

    assert "alpha" in result.content[0].text
    assert provider.fetches == [("run_1", "alpha")]
    assert workspace.materializations[0][1] == "alpha"


def test_skill_bundle_rejects_path_traversal():
    with pytest.raises(ValueError):
        SkillBundle(
            descriptor=SkillDescriptor(
                name="unsafe", description="unsafe", source_id="test"
            ),
            files={"SKILL.md": b"ok", "../secret": b"bad"},
            content_hash="sha256:test",
        )


def test_skill_name_preserves_legacy_spaces_but_rejects_path_separators():
    descriptor = SkillDescriptor(
        name="Excel Analysis",
        description="Analyze workbooks",
        source_id="legacy",
    )

    assert descriptor.name == "Excel Analysis"
    with pytest.raises(ValueError):
        SkillDescriptor(
            name="../unsafe",
            description="unsafe",
            source_id="legacy",
        )


@pytest.mark.asyncio
async def test_filesystem_skill_rejects_oversized_file_before_reading_past_limit(
    tmp_path,
):
    skill_root = tmp_path / "skills" / "large"
    skill_root.mkdir(parents=True)
    (skill_root / "SKILL.md").write_bytes(b"x" * 33)
    provider = FilesystemSkillProvider(
        (tmp_path / "skills",), max_files=2, max_total_bytes=32
    )

    with pytest.raises(SageV2Error) as caught:
        await provider.fetch("large", run_id="run_1")

    assert caught.value.info.code == "skill.bundle_too_large"


@pytest.mark.asyncio
async def test_filesystem_skill_rejects_symlinked_bundle_files(tmp_path):
    skill_root = tmp_path / "skills" / "unsafe"
    skill_root.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text("# Unsafe", encoding="utf-8")
    secret = tmp_path / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    (skill_root / "secret.txt").symlink_to(secret)
    provider = FilesystemSkillProvider((tmp_path / "skills",))

    with pytest.raises(SageV2Error) as caught:
        await provider.fetch("unsafe", run_id="run_1")

    assert caught.value.info.code == "skill.symlink_denied"

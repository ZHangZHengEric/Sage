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
async def test_available_skills_catalog_keeps_full_description():
    long_description = (
        "Built-in default production strategy when no selected personalized "
        "Skill covers the full video. Use for a confirmed total duration "
        "longer than 30 seconds."
    )
    assert len(long_description) > 50
    provider = InMemorySkillProvider(
        (
            SkillBundle(
                descriptor=SkillDescriptor(
                    name="long-video",
                    description=long_description,
                    source_id="test",
                ),
                files={"SKILL.md": b"# Long"},
                content_hash="sha256:" + "a" * 64,
            ),
        )
    )

    segments = await AvailableSkillsContextProvider(provider).segments(
        command(), run_id="run_1"
    )

    assert f"<skill_description>{long_description}</skill_description>" in (
        segments[0].content
    )
    assert "..." not in segments[0].content


@pytest.mark.asyncio
async def test_catalog_keeps_all_skills_beyond_old_size_and_count_limits():
    from xml.etree import ElementTree

    skills = [bundle(f"skill-{index:03}", "# Skill") for index in range(130)]
    description = "Long <description> & selection guidance. " * 400
    skills[0] = skills[0].model_copy(
        update={
            "descriptor": skills[0].descriptor.model_copy(
                update={"description": description}
            )
        }
    )
    provider = InMemorySkillProvider(tuple(reversed(skills)))
    segments = await AvailableSkillsContextProvider(provider).segments(
        command(), run_id="run_1"
    )
    document = ElementTree.fromstring(f"<root>{segments[0].content}</root>")
    entries = document.findall("available_skills/skill")
    assert [entry.findtext("skill_name") for entry in entries] == [
        skill.descriptor.name for skill in skills
    ]
    assert entries[0].findtext("skill_description") == description
    assert provider.fetches == []


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
async def test_active_skill_budget_evicts_oldest_within_hard_budget():
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
        max_active_tokens=300,
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


@pytest.mark.asyncio
async def test_filesystem_skill_duplicate_roots_use_one_consistent_precedence(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    for root, title in ((first, "First"), (second, "Second")):
        skill_root = root / "duplicate"
        skill_root.mkdir(parents=True)
        (skill_root / "SKILL.md").write_text(
            f"---\ndescription: {title}\n---\n# {title}", encoding="utf-8"
        )
    provider = FilesystemSkillProvider((first, second))

    descriptor = await provider.get_skill("duplicate", run_id="run_1")
    bundle = await provider.fetch("duplicate", run_id="run_1")

    assert descriptor.description == "First"
    assert bundle.descriptor == descriptor
    assert b"# First" in bundle.files["SKILL.md"]


@pytest.mark.asyncio
async def test_single_oversized_skill_is_rejected_before_copy_or_activation():
    provider, workspace, activations, _ = loader_for(bundle("huge", "<" * 2000))
    loader = SkillLoader(
        catalog=provider,
        source=provider,
        workspace=workspace,
        activations=activations,
        max_active_tokens=100,
    )
    with pytest.raises(SageV2Error) as caught:
        await loader.load("huge", run_id="run_1")
    assert caught.value.info.code == "skill.active_budget_exceeded"
    assert caught.value.info.metadata["side_effect_state"] == "not_applied"
    assert "limit 100" in caught.value.info.message
    assert workspace.materializations == []
    assert await loader.loaded(run_id="run_1") == ()


@pytest.mark.asyncio
async def test_skill_lookup_does_not_scan_unrelated_directories(tmp_path, monkeypatch):
    from sagents.v2.skill.plugins.filesystem import FilesystemSkillProvider

    (tmp_path / "alpha").mkdir()
    (tmp_path / "alpha" / "SKILL.md").write_text("# Alpha", encoding="utf-8")
    provider = FilesystemSkillProvider((tmp_path,))

    def fail():
        raise AssertionError("a single lookup must not scan the full catalog")

    monkeypatch.setattr(provider, "descriptors", fail)
    assert (await provider.get_skill("alpha", run_id="run_1")).description == "Alpha"
    assert (await provider.fetch("alpha", run_id="run_1")).files[
        "SKILL.md"
    ] == b"# Alpha"


@pytest.mark.asyncio
async def test_skill_metadata_reads_are_cached_and_run_off_the_event_loop(
    tmp_path, monkeypatch
):
    import threading
    from sagents.v2.skill.plugins.filesystem import FilesystemSkillProvider

    (tmp_path / "alpha").mkdir()
    skill = tmp_path / "alpha" / "SKILL.md"
    skill.write_text("# Alpha", encoding="utf-8")
    provider = FilesystemSkillProvider((tmp_path,))
    original = provider._description
    threads = []

    def read(path):
        threads.append(threading.get_ident())
        return original(path)

    monkeypatch.setattr(provider, "_description", read)
    await provider.list_skills(run_id="run_1")
    await provider.list_skills(run_id="run_2")
    assert len(threads) == 1
    assert threads[0] != threading.get_ident()
    skill.write_text("# Changed description", encoding="utf-8")
    assert (
        await provider.get_skill("alpha", run_id="run_3")
    ).description == "Changed description"
    assert len(threads) == 2


@pytest.mark.asyncio
async def test_session_skill_history_loads_recent_unique_skills_within_window():
    provider, workspace, activations, loader = loader_for(
        bundle("old", "# Old"), bundle("recent", "# Recent"), bundle("new", "# New")
    )

    async def history(run_id):
        assert run_id == "next_run"
        return ("new", "recent", "new", "old")

    loader.inherited_skills = history
    loader.token_estimator = lambda text: 10
    loader.max_active_tokens = 20
    loaded = await loader.loaded(run_id="next_run")
    assert [v.descriptor.name for v in loaded] == ["recent", "new"]
    assert [entry[1] for entry in workspace.materializations] == ["new", "recent"]
    assert await loader.loaded(run_id="next_run") == loaded
    await loader.load("recent", run_id="next_run")
    await loader.load("old", run_id="next_run")
    assert [v.descriptor.name for v in await loader.loaded(run_id="next_run")] == [
        "recent",
        "old",
    ]


@pytest.mark.asyncio
async def test_inherited_skills_obey_current_grant_and_materialize_for_new_run():
    provider, workspace, activations, loader = loader_for(
        bundle("alpha", "# Alpha"), bundle("beta", "# Beta")
    )
    await loader.load("alpha", run_id="previous")

    async def history(run_id):
        return ("beta", "alpha")

    loader.inherited_skills = history
    loader.catalog = FilteredSkillCatalog(provider, ("alpha",))
    loaded = await loader.loaded(run_id="next")
    assert [v.descriptor.name for v in loaded] == ["alpha"]
    assert loaded[0].run_id == "next"
    assert ("next", "alpha") in provider.fetches
    assert not any(name == "beta" for _, name in provider.fetches)
    loader.catalog = FilteredSkillCatalog(provider, ())
    assert await loader.loaded(run_id="next") == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("budget", [20, 30, 40])
async def test_history_restores_around_defaults_and_skips_oversized_candidates(budget):
    provider, workspace, activations, loader = loader_for(
        *(
            bundle(name, name)
            for name in ("a", "b", "large", "recent", "old", "revoked")
        )
    )
    loader.token_estimator = lambda text: (
        25 if "<skill_name>large</skill_name>" in text else 10
    )
    loader.max_active_tokens = budget
    defaults = tuple([await loader.load(name, run_id="next") for name in ("a", "b")])
    history_reads = []

    async def history(run_id):
        history_reads.append(run_id)
        return ("a", "large", "revoked", "deleted", "recent", "recent", "old", "b")

    loader.inherited_skills = history
    loader.catalog = FilteredSkillCatalog(
        provider, ("a", "b", "large", "recent", "old")
    )
    results = await asyncio.gather(*(loader.loaded(run_id="next") for _ in range(3)))
    loaded = results[0]
    expected = {20: [], 30: ["recent"], 40: ["old", "recent"]}[budget] + ["a", "b"]
    assert [value.descriptor.name for value in loaded] == expected
    assert loaded[-2:] == defaults
    assert (
        sum(loader.token_estimator(loader._context_content(value)) for value in loaded)
        <= budget
    )
    assert all(result == loaded for result in results)
    assert history_reads == ([] if budget == 20 else ["next"])
    assert len(provider.fetches) == len(set(provider.fetches))
    assert {name for _, name, _ in workspace.materializations} == set(expected)
    assert await activations.list_loaded(run_id="next") == loaded


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["skill.not_found", "skill.not_enabled"])
async def test_history_skips_candidates_removed_after_catalog_listing(
    monkeypatch, code
):
    provider, _, _, loader = loader_for(
        bundle("default", "Default"), bundle("stale", "Stale"), bundle("valid", "Valid")
    )
    await loader.load("default", run_id="next")

    async def history(run_id):
        return ("stale", "valid")

    original = provider.get_skill

    async def lookup(name, *, run_id):
        if name == "stale":
            raise loader._error(code, "Skill is no longer available")
        return await original(name, run_id=run_id)

    monkeypatch.setattr(provider, "get_skill", lookup)
    loader.inherited_skills = history
    segments = await ActiveSkillsContextProvider(loader).segments(
        command(), run_id="next"
    )
    content = "\n".join(segment.content for segment in segments)
    assert "<skill_name>valid</skill_name>" in content
    assert "<skill_name>default</skill_name>" in content
    assert "<skill_name>stale</skill_name>" not in content
    assert provider.fetches == [("next", "default"), ("next", "valid")]


@pytest.mark.asyncio
async def test_factory_history_requires_successful_load_result(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from sagents.v2.agent.factory import AgentCompositionFactory
    from sagents.v2.context.session_history import SessionHistoryLedgerBuilder
    from sagents.v2.model import ModelMessage, ModelToolCall

    messages = []
    # Reused provider call IDs must not match success from a different Run.
    for run, name, success in (
        ("first", "good", True),
        ("second", "failed", False),
        ("third", "unfinished", None),
    ):
        messages.append(
            ModelMessage(
                role="assistant",
                metadata={"source_run_id": run},
                tool_calls=(
                    ModelToolCall(
                        tool_call_id="load",
                        name="load_skill",
                        arguments={"skill_name": name},
                    ),
                ),
            )
        )
        if success is not None:
            messages.append(
                ModelMessage(
                    role="tool",
                    tool_call_id="load",
                    content=(TextBlock(text="loaded" if success else "failed"),),
                    metadata={
                        "source_run_id": run,
                        **(
                            {"skill_name": name, "content_hash": "hash"}
                            if success
                            else {}
                        ),
                    },
                )
            )
    monkeypatch.setattr(
        SessionHistoryLedgerBuilder, "build", AsyncMock(return_value=tuple(messages))
    )
    provider, workspace, activations, _ = loader_for(
        *(bundle(name, name) for name in ("good", "failed", "unfinished"))
    )
    names = ("good", "failed", "unfinished")
    factory = AgentCompositionFactory(
        SimpleNamespace(
            session_store=SimpleNamespace(
                get_start_command=AsyncMock(return_value=command()),
            )
        )
    )
    loader = factory.create_skill_loader(
        SimpleNamespace(
            agents={"agent": SimpleNamespace(skills=names)},
            policy_ceilings={"agent": SimpleNamespace(allowed_skills=set(names))},
        ),
        "agent",
        catalog=provider,
        source=provider,
        workspace=workspace,
        activations=activations,
        skill_loading=SimpleNamespace(create_loader=SkillLoader),
    )
    assert [value.descriptor.name for value in await loader.loaded(run_id="next")] == [
        "good"
    ]
    assert provider.fetches == [("next", "good")]


@pytest.mark.asyncio
@pytest.mark.parametrize("style", ["plain", "folded", "literal"])
async def test_filesystem_catalog_preserves_complete_yaml_description(tmp_path, style):
    root = tmp_path / "long-skill"
    root.mkdir()
    first = "selection condition " * 4000
    second = "Keep the final routing condition."
    if style == "plain":
        header = f'description: "{first}{second}"\n'
        expected = first + second
    else:
        indicator = ">-" if style == "folded" else "|-"
        header = f"description: {indicator}\n  {first}\n  {second}\n"
        expected = first + (" " if style == "folded" else "\n") + second
    (root / "SKILL.md").write_text(f"---\n{header}---\n# Body\n", encoding="utf-8")
    provider = FilesystemSkillProvider((tmp_path,))
    listed = await provider.list_skills(run_id="run_1")
    assert listed[0].description == expected
    assert (
        await provider.get_skill("long-skill", run_id="run_1")
    ).description == expected


@pytest.mark.asyncio
async def test_skill_preflight_failure_is_known_but_materialization_failure_is_not():
    provider, workspace, activations, loader = loader_for(bundle("alpha", "# Alpha"))
    with pytest.raises(SageV2Error) as missing:
        await loader.load("missing", run_id="run_1")
    assert missing.value.info.metadata["side_effect_state"] == "not_applied"
    assert "missing" in missing.value.info.message

    class InterruptedWorkspace:
        async def materialize(self, *args, **kwargs):
            raise RuntimeError("response lost after copying files")

    loader = SkillLoader(
        catalog=provider,
        source=provider,
        workspace=InterruptedWorkspace(),
        activations=activations,
    )
    with pytest.raises(RuntimeError, match="response lost"):
        await loader.load("alpha", run_id="run_1")

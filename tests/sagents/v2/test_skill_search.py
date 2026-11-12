"""Search, visibility and loading through the standard v2 Skill paths."""

from types import SimpleNamespace

import pytest

from sagents.v2.contracts.commands import RunConfig, StartRun
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import JsonBlock
from sagents.v2.skill import FilteredSkillCatalog, InMemorySkillProvider, InvocationGrantSkillCatalog
from sagents.v2.skill.context import AvailableSkillsContextProvider
from sagents.v2.skill.plugins.filesystem import FilesystemSkillProvider
from sagents.v2.skill.plugins.repository import MemorySkillRepository, SqliteSkillRepository
from tests.sagents.v2.test_runtime_team_skills import ATTACHMENT, open_app, prompt, run
from tests.sagents.v2.test_builder_nested_teams import package
from tests.sagents.v2.test_skill_provider_matrix import bundle


def names(matches):
    return [item.name for item in matches]


@pytest.mark.asyncio
async def test_ten_thousand_searchable_skills_are_filtered_before_limit():
    provider = InMemorySkillProvider(tuple(
        bundle(f"skill-{i:05}", "共同查询词 needle") for i in range(10_000)
    ))
    grant = frozenset(f"skill-{i:05}" for i in range(10_000))
    assert names(await provider.search_skills(
        "查询词 needle", run_id="all", allowed_names=grant, limit=3
    )) == ["skill-00000", "skill-00001", "skill-00002"]
    assert names(await provider.search_skills(
        "needle", run_id="limited", allowed_names=frozenset({"skill-09999"}), limit=1
    )) == ["skill-09999"]
    assert names(await provider.search_skills(
        "skill-09999", run_id="all", allowed_names=grant, limit=1
    )) == ["skill-09999"]
    assert not await provider.search_skills("?!", run_id="all", allowed_names=grant, limit=3)
    context = AvailableSkillsContextProvider(provider, default_visible_skills=("skill-09999",))
    (segment,) = await context.segments(command(RunConfig()))
    assert segment.content.count("<skill_name>") == 1
    assert "<skill_name>skill-09999</skill_name>" in segment.content
    assert provider.fetches == []


@pytest.mark.asyncio
@pytest.mark.parametrize("persistent", [False, True])
async def test_repository_backfill_publish_and_pin(tmp_path, persistent):
    path = tmp_path / "skills.db"
    repository = SqliteSkillRepository(path) if persistent else MemorySkillRepository()
    allowed = frozenset({"demo"})

    async def search(query, run_id):
        return await repository.search_skills(query, run_id=run_id, allowed_names=allowed, limit=5)

    try:
        first = await repository.publish(bundle("demo", "unicorn"))
        await repository.get_skill("demo", run_id="old")
        if persistent:
            await repository.close()
            repository = SqliteSkillRepository(path)
        assert names(await search("unicorn", "old")) == ["demo"]
        second = await repository.publish(bundle("demo", "phoenix"), expected_version=first.version)
        assert not await search("phoenix", "old")
        assert (await search("unicorn", "old"))[0].version == first.version
        assert (await search("phoenix", "new"))[0].version == second.version
        assert (await repository.fetch_latest("demo", run_id="old")).descriptor.version == second.version
        with pytest.raises(SageV2Error, match="base version"):
            await repository.publish(bundle("demo", "rollbackword"), expected_version=first.version)
        assert not await search("rollbackword", "later")
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_filesystem_search_refreshes_changes_and_uses_source_precedence(tmp_path):
    first = tmp_path / "first" / "demo"
    second = tmp_path / "second" / "demo"
    for root in (first, second):
        root.mkdir(parents=True)
    first_file = first / "SKILL.md"
    first_file.write_text("---\nname: demo\ndescription: microscopy\n---\ncrystal\n")
    (second / "SKILL.md").write_text("astronomy")
    provider = FilesystemSkillProvider((first.parent, second.parent))

    async def search(query):
        return names(await provider.search_skills(
            query, run_id="run", allowed_names=frozenset({"demo"}), limit=5,
        ))

    assert await search("demo") == ["demo"]
    assert await search("microscopy") == ["demo"]
    assert await search("crystal") == ["demo"]
    assert await search("astronomy") == []
    first_file.write_text("spectrometer")
    assert await search("crystal") == []
    assert await search("spectrometer") == ["demo"]
    first_file.unlink()
    assert await search("astronomy") == ["demo"]
    (second / "SKILL.md").unlink()
    assert await search("astronomy") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("attachment", [False, True])
async def test_package_search_loads_only_authorized_skill(tmp_path, attachment):
    visible = bundle("visible-guide", "General help")
    hidden = bundle("hidden-guide", "Local handbook")
    target = ATTACHMENT.descriptor.name if attachment else hidden.descriptor.name
    query = "UNIQUE RUNTIME INSTRUCTIONS" if attachment else "handbook"

    def load_from_search(request):
        result = next(
            block.value for message in request.messages if message.role == "tool"
            for block in message.content if isinstance(block, JsonBlock)
        )
        assert names_from_tool(result) == [target]
        return "load_skill", {"skill_name": result[0]["name"]}

    app, bindings, models = await open_app(
        tmp_path, {"root": (("search_skills", {"query": query}), load_from_search)},
        existing=(visible, hidden, bundle("denied-guide", query)),
    )
    manifest = package("root")
    data = manifest.model_dump(mode="json")
    data["agents"]["assistant"].update({
        "skills": ["visible-guide", "hidden-guide"],
        "preload_skills": [],
        "default_visible_skills": ["visible-guide"],
        "tools": ["search_skills"],
    })
    try:
        agent = await app.load_agent(type(manifest).model_validate(data))
        result, events = await run(app, agent, attachments=(ATTACHMENT,) if attachment else ())
        assert result.state.value == "completed", [
            (event.type, event.data) for event in events if "failed" in event.type
        ]
        requests = [request for _, request in models.seen]
        first_prompt = prompt(requests[0])
        assert "<skill_name>visible-guide</skill_name>" in first_prompt
        assert f"<skill_name>{target}</skill_name>" not in first_prompt
        assert "search_skills" in {tool.name for tool in requests[0].tools}
        assert f"<skill_name>{target}</skill_name>" in prompt(requests[-1])
        assert "<active_skill>" in prompt(requests[-1])
    finally:
        await app.close()
        await bindings.close()


def names_from_tool(result):
    assert all(set(item) == {"name", "description"} for item in result)
    return [item["name"] for item in result]


def test_default_visibility_is_optional_and_validated():
    manifest = package("root")
    assert "default_visible_skills" not in manifest.model_dump()["agents"]["assistant"]
    assert "default_visible_skills_limit" not in manifest.model_dump()["agents"]["assistant"]
    data = manifest.model_dump(mode="json")
    data["agents"]["assistant"]["default_visible_skills"] = ["outside"]
    with pytest.raises(ValueError, match="subset"):
        type(manifest).model_validate(data)


def test_package_can_raise_default_visibility_limit():
    manifest = package("root")
    data = manifest.model_dump(mode="json")
    definition = data["agents"]["assistant"]
    skills = [f"skill-{index}" for index in range(25)]
    definition.update(skills=skills, preload_skills=[], default_visible_skills=skills)
    with pytest.raises(ValueError, match="at most 20"):
        type(manifest).model_validate(data)
    definition["default_visible_skills_limit"] = 25
    configured = type(manifest).model_validate(data)
    assert configured.agents["assistant"].default_visible_skills == tuple(skills)
    assert configured.agents["assistant"].default_visible_skills_limit == 25
    definition["default_visible_skills"] = []
    assert type(manifest).model_validate(data).model_dump(mode="json")["agents"]["assistant"]["default_visible_skills"] == []


def command(config):
    return StartRun(agent_id="test", resolved_spec_hash="test", input=(), config=config, idempotency_key="test")


@pytest.mark.asyncio
async def test_run_grant_narrows_search_and_legacy_provider_still_lists():
    provider = InMemorySkillProvider((
        bundle("visible", "handbook"),
        bundle("other", "handbook"),
    ))
    configured = command(RunConfig(enabled_skills=("other",), enabled_tools=()))

    async def read_command(_):
        return configured

    wrapped = InvocationGrantSkillCatalog(FilteredSkillCatalog(provider, ("visible", "other")), read_command)
    assert names(await wrapped.search_skills("handbook", run_id="test", limit=5)) == ["other"]
    legacy = SimpleNamespace(list_skills=wrapped.list_skills, get_skill=wrapped.get_skill)
    old = AvailableSkillsContextProvider(legacy)
    fallback = AvailableSkillsContextProvider(legacy, search_enabled=True)
    assert await old.segments(configured) == await fallback.segments(configured)
    assert "<skill_name>other</skill_name>" in (await old.segments(configured))[0].content
    explicit = AvailableSkillsContextProvider(legacy, default_visible_skills=("visible",))
    (segment,) = await explicit.segments(configured)
    assert "<skill_name>" not in segment.content
    assert "search_skills" not in segment.content
    configured = command(RunConfig(enabled_skills=("other",), enabled_tools=("search_skills",)))
    (segment,) = await fallback.segments(configured)
    assert "<skill_name>" not in segment.content
    assert "search_skills" in segment.content



@pytest.mark.asyncio
async def test_team_members_use_their_own_package_visibility(tmp_path):
    from tests.sagents.v2.test_builder_nested_teams import delegate

    app, bindings, models = await open_app(
        tmp_path, {"root": (delegate("maker"),), "maker": ()},
        existing=(bundle("root-visible", "Root"), bundle("maker-visible", "Member")),
    )

    def with_search(role, children=()):
        manifest = package(role, children)
        data = manifest.model_dump(mode="json")
        definition = data["agents"]["assistant"]
        definition.update({
            "tools": [*definition["tools"], "search_skills"],
            "skills": ["root-visible", "maker-visible"],
            "default_visible_skills": [f"{role}-visible"],
            "preload_skills": [],
        })
        return type(manifest).model_validate(data)

    try:
        maker = await app.load_agent(with_search("maker"))
        root = await app.load_agent(with_search("root", ("maker",)), subagents={"maker": maker})
        result, events = await run(app, root, attachments=())
        assert result.state.value == "completed", [
            (event.type, event.data) for event in events if "failed" in event.type
        ]
        first_requests = {}
        for role, request in models.seen:
            first_requests.setdefault(role, request)
        assert first_requests.keys() == {"root", "maker"}
        for role, request in first_requests.items():
            content = prompt(request)
            assert content.count("<skill_name>") == 1
            assert f"<skill_name>{role}-visible</skill_name>" in content
            assert "search_skills" in {tool.name for tool in request.tools}
    finally:
        await app.close()
        await bindings.close()


@pytest.mark.asyncio
async def test_search_indexes_body_budget_after_frontmatter(tmp_path):
    header = "---\nname: demo\ndescription: Guide\nextra: " + "p" * 65_536 + " header-only\n---\n"
    body = "indexed-body " + " " * 65_536 + "outside-budget"
    content = header + body
    directory = tmp_path / "demo"
    directory.mkdir()
    (directory / "SKILL.md").write_text(content, encoding="utf-8")

    for provider in (
        InMemorySkillProvider((bundle("demo", content),)),
        FilesystemSkillProvider((tmp_path,)),
    ):
        async def search(query):
            return names(await provider.search_skills(
                query, run_id="run", allowed_names=frozenset({"demo"}), limit=5,
            ))

        assert await search("indexed") == ["demo"]
        assert await search("header-only") == []
        assert await search("outside-budget") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("persistent", [False, True])
async def test_bm25_statistics_ignore_skills_outside_the_run_grant(tmp_path, persistent):
    bundles = (
        bundle("alpha", "scarlet"),
        bundle("beta", "cobalt"),
        *(bundle(f"other-{i}", "scarlet") for i in range(10)),
    )
    allowed = frozenset({"alpha", "beta"})
    others = frozenset(item.descriptor.name for item in bundles[2:])
    provider = InMemorySkillProvider(bundles)
    repository = None
    try:
        if persistent:
            repository = SqliteSkillRepository(tmp_path / "skills.db")
            for item in bundles:
                await repository.publish(item)
            provider = repository

        async def search(scope, run_id):
            return names(await provider.search_skills(
                "scarlet cobalt", run_id=run_id, allowed_names=scope, limit=1,
            ))

        assert await search(allowed, "authorized") == ["alpha"]
        assert await search(others, "other") == ["other-0"]
        assert await search(allowed, "authorized") == ["alpha"]
    finally:
        if repository is not None:
            await repository.close()


@pytest.mark.asyncio
async def test_legacy_provider_runs_when_search_is_removed_from_the_run(tmp_path, monkeypatch):
    from tests.sagents.v2.test_runtime_team_skills import CONTEXT, no_skills

    monkeypatch.setattr(InMemorySkillProvider, "search_skills", None)
    app, bindings, models = await open_app(
        tmp_path, {"root": ()}, existing=(bundle("legacy-guide", "Legacy"),),
    )
    try:
        manifest = no_skills("root")
        definition = manifest.agents["assistant"].model_copy(
            update={"tools": ("search_skills",), "skills": ("legacy-guide",)},
        )
        agent = await app.load_agent(manifest.model_copy(update={"agents": {"assistant": definition}}))
        stream = await app.entrypoint().run_stream(StartRun(
            agent_id=agent.id, resolved_spec_hash=agent.composition_hash, input=(),
            config=RunConfig(enabled_tools=()), idempotency_key="removed-search",
        ), CONTEXT, agent=agent)
        async for _ in stream.events:
            pass
        assert (await stream.wait()).state.value == "completed"
        request = models.seen[0][1]
        assert "search_skills" not in {tool.name for tool in request.tools}
        assert "<skill_name>legacy-guide</skill_name>" in prompt(request)
    finally:
        await app.close()
        await bindings.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong_lookup", [False, True])
async def test_load_refuses_wrong_provider_identity_before_materialization(wrong_lookup):
    from sagents.v2.skill import InMemorySkillActivationRepository, InMemorySkillWorkspace
    from sagents.v2.skill.provider import SkillLoader

    class WrongRowProvider:
        async def get_skill(self, name, *, run_id):
            return bundle("hidden-guide" if wrong_lookup else name, "Guide").descriptor

        async def fetch(self, name, *, run_id):
            return bundle("hidden-guide", "Guide")

    provider = WrongRowProvider()
    workspace = InMemorySkillWorkspace()
    loader = SkillLoader(
        catalog=FilteredSkillCatalog(provider, ("allowed-guide",)), source=provider,
        workspace=workspace, activations=InMemorySkillActivationRepository(),
    )
    with pytest.raises(SageV2Error) as caught:
        await loader.load("allowed-guide", run_id="probe")
    assert caught.value.info.code == "skill.identity_mismatch"
    assert workspace.materializations == []


def test_alternating_authorized_projections_reuse_their_indexes():
    from sagents.v2.skill.search import SkillSearchIndex

    index = SkillSearchIndex()
    docs = {}
    for name in ("alpha", "beta", "gamma"):
        skill = bundle(name, "needle")
        docs[name] = lambda value=skill: (value.descriptor, value.files["SKILL.md"])
    try:
        index.search("needle", docs, 5)
        statements = []
        index._db.set_trace_callback(statements.append)
        scopes = [{"alpha": docs["alpha"]}, {"beta": docs["beta"]}]
        for scope in (*scopes, *scopes):
            assert names(index.search("needle", scope, 5)) == list(scope)
        assert sum("INSERT INTO temp.authorized_skill_search_fts" in sql for sql in statements) == 2
        assert names(index.search("needle", {"gamma": docs["gamma"]}, 5)) == ["gamma"]
        assert names(index.search("needle", scopes[0], 5)) == ["alpha"]
        assert len(index._ranker._projections) == 2
    finally:
        index.close()

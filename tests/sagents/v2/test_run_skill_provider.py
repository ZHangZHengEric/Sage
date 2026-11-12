"""A Run-scoped Skill provider through the standard Sage tools."""

import pytest

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.items import JsonBlock
from sagents.v2.skill import (
    InMemorySkillActivationRepository,
    InMemorySkillProvider,
    InMemorySkillWorkspace,
    SkillLoader,
    SkillReference,
)
from tests.sagents.v2.test_runtime_team_skills import no_skills, open_app, prompt, run
from tests.sagents.v2.test_skill_provider_matrix import bundle


class RunProvider(InMemorySkillProvider):
    def __init__(self):
        super().__init__(())
        self.versions = {}
        for version in ("v1", "v2"):
            reference = SkillReference(skill_id="report", version_id=version)
            value = bundle("weekly-report", f"AUTHORIZED REPORT {version}")
            self.versions[version] = value.model_copy(update={"descriptor": value.descriptor.model_copy(
                update={"reference": reference},
            )})
        self.current = "v1"
        self.revoked = False

    async def search_skills(self, query, *, run_id, limit):
        return (self.versions[self.current].descriptor,) if not self.revoked else ()

    async def fetch_reference(self, reference, *, run_id):
        if self.revoked:
            raise SageV2Error(RuntimeErrorInfo(
                code="skill.not_enabled", category=ErrorCategory.POLICY_DENIED,
                message="Skill access was revoked",
            ))
        return self.versions[reference.version_id]


async def test_run_provider_search_and_load_without_package_skills(tmp_path):
    provider = RunProvider()

    def load_search_result(request):
        result = next(
            block.value for message in request.messages if message.role == "tool"
            for block in message.content if isinstance(block, JsonBlock)
        )
        assert result == [{"name": "weekly-report", "description": "weekly-report description",
                           "skill_id": "report", "version_id": "v1"}]
        provider.current = "v2"
        return "load_skill", {"skill_id": "report", "version_id": "v1"}

    app, bindings, models = await open_app(tmp_path, {
        "root": (("search_skills", {"query": "weekly report"}), load_search_result),
    }, skill_provider=provider)
    manifest = no_skills("root").model_dump(mode="json")
    manifest["agents"]["assistant"]["tools"] = ["search_skills"]
    try:
        agent = await app.load_agent(manifest)
        result, events = await run(app, agent, attachments=())
        assert result.state.value == "completed", [event.data for event in events if "failed" in event.type]
        state = [event.data.state for event in events if event.type == "skill.state"][-1]
        assert state["selected_references"] == [{"skill_id": "report", "version_id": "v1"}]
        assert "AUTHORIZED REPORT" not in str(state)
        assert "AUTHORIZED REPORT v1" in prompt(models.seen[-1][1])
        assert "AUTHORIZED REPORT v2" not in prompt(models.seen[-1][1])
    finally:
        await app.close()
        await bindings.close()


async def test_reference_load_and_restore_require_the_run_candidate_and_current_access():
    provider = RunProvider()
    workspace = InMemorySkillWorkspace()

    def loader():
        return SkillLoader(catalog=provider, source=provider, run_provider=provider,
                           workspace=workspace, activations=InMemorySkillActivationRepository())

    original = loader()
    reference = (await original.search_skills("weekly report", run_id="run-1", limit=5))[0].reference
    with pytest.raises(SageV2Error, match="search result"):
        await original.load_reference(reference, run_id="run-2")
    loaded = await original.load_reference(reference, run_id="run-1")
    assert loaded.descriptor.reference == reference
    snapshot = await original.snapshot_run("run-1")
    assert "AUTHORIZED REPORT" not in str(snapshot)

    provider.current = "v2"
    restored = loader()
    await restored.restore_run("run-1", snapshot)
    assert (await restored.loaded(run_id="run-1"))[0].instructions == "AUTHORIZED REPORT v1"
    replacement = (await restored.search_skills("weekly report", run_id="run-1", limit=5))[0].reference
    with pytest.raises(SageV2Error, match="already selected"):
        await restored.load_reference(replacement, run_id="run-1")
    provider.revoked = True
    with pytest.raises(SageV2Error, match="revoked"):
        await loader().restore_run("run-1", snapshot)


async def test_explicit_empty_skill_grant_never_searches_run_provider(tmp_path):
    class UnsearchableProvider(RunProvider):
        async def search_skills(self, query, *, run_id, limit):
            pytest.fail("an explicitly disabled Run reached the provider")

    app, bindings, models = await open_app(tmp_path, {
        "root": (("search_skills", {"query": "weekly report"}),),
    }, skill_provider=UnsearchableProvider())
    manifest = no_skills("root").model_dump(mode="json")
    manifest["agents"]["assistant"]["tools"] = ["search_skills"]
    try:
        agent = await app.load_agent(manifest)
        result, events = await run(app, agent, attachments=(), enabled_skills=())
        assert result.state.value == "completed", [event.data for event in events if "failed" in event.type]
        assert any(block.value == [] for message in models.seen[-1][1].messages
                   if message.role == "tool" for block in message.content if isinstance(block, JsonBlock))
    finally:
        await app.close()
        await bindings.close()

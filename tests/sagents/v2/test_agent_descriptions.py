"""Agent descriptions survive package resolution, delegation and recovery."""

import pytest

from sagents.v2.package.manifest.loader import SageManifestLoader
from sagents.v2.package.manifest.resolver import (
    CompositionResolver,
    ResolvedSageManifest,
)
from sagents.v2.model.catalog import model_catalog_input
from tests.sagents.v2.test_manifest_matrix import MODELS, VALID
from tests.sagents.v2.test_builder_nested_teams import (
    Models,
    delegate,
    open_app,
    package,
    run,
)
from tests.sagents.v2.test_local_workspace_sandbox_matrix import CONTEXT


@pytest.mark.parametrize("description", [None, "", "查询个人工作进度。\n检索已授权知识。"])
def test_manifest_resolution_preserves_agent_description(description):
    manifest = SageManifestLoader().loads(VALID)
    manifest = manifest.model_copy(update={
        "agents": {"main": manifest.agents["main"].model_copy(
            update={"description": description}
        )}
    })
    resolved = CompositionResolver(models=model_catalog_input(config_text=MODELS)).resolve(manifest)
    assert resolved.agents["main"].description == (description or "")
    restored = ResolvedSageManifest.model_validate_json(resolved.model_dump_json())
    assert restored.agents["main"].description == (description or "")


def test_legacy_resolved_snapshot_without_description_keeps_its_shape():
    resolved = CompositionResolver(models=model_catalog_input(config_text=MODELS)).resolve(
        SageManifestLoader().loads(VALID)
    )
    legacy = resolved.model_dump(mode="json")
    for agent in legacy["agents"].values():
        agent.pop("description", None)
    restored = ResolvedSageManifest.model_validate(legacy)
    assert restored.agents["main"].description == ""
    assert restored.model_dump(mode="json") == legacy


def described_package(role, children=(), *, description):
    value = package(role, children)
    return value.model_copy(update={
        "agents": {"assistant": value.agents["assistant"].model_copy(
            update={"name": role, "description": description}
        )}
    })


async def load_described_tree(app, *, mode, revision):
    maker = await app.load_agent(described_package(
        "maker", description=f"检索个人工作进度 {revision}。\n返回有依据的结果。"
    ))
    director = await app.load_agent(
        described_package("director", ("maker",), description=f"协调成员任务 {revision}"),
        subagents={"maker": maker},
    )
    outsider = await app.load_agent(package("outsider"))
    root_package = described_package(
        "root", ("director", "outsider"), description=f"负责团队交付 {revision}"
    )
    root_package = root_package.model_copy(update={
        "agents": {"assistant": root_package.agents["assistant"].model_copy(
            update={"mode": mode}
        )}
    })
    return await app.load_agent(
        root_package, subagents={"director": director, "outsider": outsider}
    )


def roster(request):
    return next(
        block.text.split("<multi_agent_mode>\n", 1)[1].split("</multi_agent_mode>", 1)[0]
        for message in request.messages
        for block in message.content
        if "<multi_agent_mode>\n" in getattr(block, "text", "")
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,tool", [("team", "sys_team_delegate_task"), ("fibre", "sys_delegate_task")])
async def test_nested_member_descriptions_reach_models_and_survive_restart(tmp_path, mode, tool):
    plans = {"root": ((tool, delegate("director")[1]),), "director": (delegate("maker"),)}
    models = Models(plans)
    app, bindings, _ = await open_app(tmp_path, models)
    try:
        root = await load_described_tree(app, mode=mode, revision="original")
        result, events = await run(app, root)
        assert result.state.value == "completed", events
        requests = dict(models.seen)
        assert "director: director — 协调成员任务 original" in roster(requests["root"])
        assert "outsider: General Assistant — no description" in roster(requests["root"])
        assert "maker: maker — 检索个人工作进度 original。\n返回有依据的结果。" in roster(requests["director"])
        assert "outsider" not in roster(requests["director"])
        run_id, original_hash = result.run_id, root.composition_hash
    finally:
        await app.close()
        await bindings.close()

    app, bindings, _ = await open_app(tmp_path, Models(plans))
    try:
        latest = await load_described_tree(app, mode=mode, revision="changed")
        restored = await app.agent_for_run(run_id, CONTEXT)
        assert restored.composition_hash == original_hash != latest.composition_hash
        assert restored._resolved.agents["assistant"].description == "负责团队交付 original"
        assert restored._resolved.agents["director"].description == "协调成员任务 original"
        assert restored._resolved.agents["director.maker"].description == "检索个人工作进度 original。\n返回有依据的结果。"
    finally:
        await app.close()
        await bindings.close()

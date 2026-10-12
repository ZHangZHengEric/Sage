import asyncio
import json

import pytest
from pydantic import ValidationError

from app.v2.desktop.backend.rsi import RsiApply, RsiStart, RsiStore, fingerprint
from app.v2.desktop.backend.service import DesktopV2Service
from app.v2.desktop.backend.schemas import (
    AgentCreate,
    AgentSettingsPatch,
    ModelProviderCreate,
)
from app.v2.desktop.backend.sidecar_lifecycle import SidecarClientLeases
from sagents.v2.optimization import (
    OptimizationCase,
    OptimizationFinalSuite,
    OptimizationSuite,
)
from sagents.v2.testing.plugins.scripted_model import ScriptedModelProvider
from sagents.v2.model.contracts import (
    ModelEventKind,
    ModelResponse,
    ModelStreamEvent,
    ModelToolCall,
)


class RsiModel(ScriptedModelProvider):
    def __init__(self, entered=None, release=None, reject=False, load_skill=False):
        super().__init__(())
        self.entered, self.release = entered, release
        self.reject = reject
        self.load_skill = load_skill

    async def _stream(self, request):
        self.requests.append(request)
        if self.entered:
            self.entered.set()
            await self.release.wait()
        messages = [m for m in request.messages if m.role == "user"]
        raw = "".join(
            block.text for block in messages[-1].content if hasattr(block, "text")
        )
        try:
            properties = (
                json.loads(raw).get("response_schema", {}).get("properties", {})
            )
        except json.JSONDecodeError:
            properties = {}
        if "memorization_detected" in properties:
            answer = dict(
                approved=not self.reject,
                memorization_detected=self.reject,
                goal_drift_detected=False,
                permission_drift_detected=False,
                rationale="Reusable method",
                findings=[],
            )
        elif "issues" in properties:
            answer = dict(
                approved=True, rationale="Goal and suites are consistent", issues=[]
            )
        elif "instruction_guidance" in properties:
            answer = dict(
                rationale="Reusable arithmetic verification",
                instruction_guidance="Verify calculations before answering.",
            )
        elif "score" in properties:
            answer = dict(
                score=1, passed=True, rationale="Correct response matches rubric"
            )
        else:
            if self.load_skill and not any(
                m.role == "tool" and m.tool_call_id == "load-arithmetic"
                for m in request.messages
            ):
                yield ModelStreamEvent(
                    kind=ModelEventKind.COMPLETED,
                    response=ModelResponse(
                        response_id="load",
                        tool_calls=(
                            ModelToolCall(
                                tool_call_id="load-arithmetic",
                                name="load_skill",
                                arguments={"skill_name": "arithmetic"},
                            ),
                        ),
                        finish_reason="tool_calls",
                    ),
                )
                return
            answer = "42"
        yield ModelStreamEvent(
            kind=ModelEventKind.COMPLETED,
            response=ModelResponse(
                response_id="answer",
                text=json.dumps(answer) if isinstance(answer, dict) else answer,
                finish_reason="stop",
            ),
        )


async def setup_service(tmp_path, monkeypatch, model):
    service = DesktopV2Service(tmp_path)
    provider = await service.create_model_provider(
        ModelProviderCreate(
            name="Test model",
            model="test",
            base_url="http://test.invalid/v1",
            api_keys=["secret-test-key"],
        ),
        "alice",
    )
    config = await service.create_agent(
        AgentCreate(
            name="Calculator",
            settings=AgentSettingsPatch(
                llm_provider_id=provider["id"],
                available_tools=[],
                available_skills=[],
                system_prefix="Answer arithmetic questions.",
                runtime_variables={"department": "math"},
            ),
        ),
        "alice",
    )

    async def bind(*args, **kwargs):
        return model

    monkeypatch.setattr(service, "_model_provider", bind)
    return service, config["id"]


def start_request(request_id="request-1"):
    return RsiStart(
        goal="Improve arithmetic reliability",
        rounds=3,
        request_id=request_id,
        optimization_scope=("instructions",),
        suite=OptimizationSuite(
            cases=(
                OptimizationCase(id="training", input="6 times 7?", rubric="42"),
                OptimizationCase(
                    id="validation", input="40 plus 2?", rubric="42", split="validation"
                ),
            )
        ),
        final_suite=OptimizationFinalSuite(
            cases=(
                OptimizationCase(
                    id="final", input="84 divided by 2?", rubric="42", split="final"
                ),
            )
        ),
    )


@pytest.mark.asyncio
@pytest.mark.timeout(20)
async def test_native_background_rounds_versions_confirmation_cas_and_restart(
    tmp_path, monkeypatch
):
    model = RsiModel()
    service, agent_id = await setup_service(tmp_path, monkeypatch, model)
    try:
        original = await service._agent(agent_id, "alice")
        started = await service.start_rsi(agent_id, start_request(), "alice")
        await service._rsi_tasks[started["id"]]
        run = await service.rsi_run(agent_id, started["id"], "alice")
        assert run["status"] == "completed", run
        assert len(run["result"]["iterations"]) == 4
        assert len(run["iterations"]) == 4
        assert run["iteration"] == 3
        assert (await service.cancel_rsi(agent_id, started["id"], "alice"))[
            "status"
        ] == "completed"
        targets = [
            r
            for r in model.requests
            if any(
                m.role == "user"
                and any(
                    "6 times 7?" in getattr(b, "text", "")
                    and "response_schema" not in getattr(b, "text", "")
                    for b in m.content
                )
                for m in r.messages
            )
        ]
        assert targets and all("department" in r.model_dump_json() for r in targets)
        assert run["result"]["report"]["final_verification"]["passed"]
        assert (await service._agent(agent_id, "alice")).config == original.config
        history = await service.rsi_history(agent_id, "alice")
        candidates = [v for v in history["versions"] if v["source"] == "rsi"]
        assert len(candidates) == 4
        assert all(
            "package" not in v and "config" not in v for v in history["versions"]
        )
        with pytest.raises(ValidationError):
            RsiApply(confirmed=False, expected_fingerprint=fingerprint(original))
        with pytest.raises(ValueError, match="not configured"):
            await service.rsi_version(agent_id, candidates[0]["id"], "bob")
        chosen = next(v for v in candidates if v["iteration"] == 1)
        version = await service.rsi_version(agent_id, chosen["id"], "alice")
        assert version["review"]["approved"]
        assert (
            "Verify calculations"
            in version["package"]["manifest"]["agents"][agent_id]["instructions"][
                "inline"
            ]
        )
        assert "secret-test-key" not in json.dumps(run)
        await service.patch_agent_settings(
            agent_id, AgentSettingsPatch(description="New user edit"), "alice"
        )
        with pytest.raises(ValueError, match="changed"):
            await service.apply_rsi_version(
                agent_id,
                chosen["id"],
                RsiApply(confirmed=True, expected_fingerprint=fingerprint(original)),
                "alice",
            )
        current = await service._agent(agent_id, "alice")
        await service.apply_rsi_version(
            agent_id,
            chosen["id"],
            RsiApply(confirmed=True, expected_fingerprint=fingerprint(current)),
            "alice",
        )
        updated = await service._agent(agent_id, "alice")
        assert "Verify calculations" in updated.config["systemPrefix"]
        assert any(
            v["source"] == "activation"
            for v in (await service.rsi_history(agent_id, "alice"))["versions"]
        )
    finally:
        await service.close()
    restored = DesktopV2Service(tmp_path)
    try:
        history = await restored.rsi_history(agent_id, "alice")
        assert history["runs"][0]["status"] == "completed"
        assert len([v for v in history["versions"] if v["source"] == "rsi"]) == 4
        assert (await restored._agent(agent_id, "alice")).config[
            "systemPrefix"
        ] == updated.config["systemPrefix"]
    finally:
        await restored.close()


@pytest.mark.asyncio
async def test_background_idempotency_keepalive_cancel_and_no_replay(
    tmp_path, monkeypatch
):
    entered, release = asyncio.Event(), asyncio.Event()
    service, agent_id = await setup_service(
        tmp_path, monkeypatch, RsiModel(entered, release)
    )
    try:
        request = start_request()
        run = await service.start_rsi(agent_id, request, "alice")
        await asyncio.wait_for(entered.wait(), 5)
        assert service.rsi_active
        assert (await service.start_rsi(agent_id, request, "alice"))["id"] == run["id"]
        with pytest.raises(ValueError, match="different"):
            await service.start_rsi(
                agent_id, request.model_copy(update={"rounds": 2}), "alice"
            )
        with pytest.raises(ValueError, match="active"):
            await service.start_rsi(agent_id, start_request("second"), "alice")
        assert (
            next(v for v in await service.list_agents("alice") if v["id"] == agent_id)[
                "rsi_status"
            ]
            == "running"
        )
        leases = SidecarClientLeases(keep_alive=lambda: service.rsi_active)
        await leases.attach("a" * 16)
        assert not (await leases.detach("a" * 16)).shutdown_requested
        with pytest.raises(ValueError, match="Cancel RSI"):
            await service.delete_agent(agent_id, "alice")
        assert (await service.cancel_rsi(agent_id, run["id"], "alice"))[
            "status"
        ] == "cancelled"
        assert not service.rsi_active
        assert (await leases.expire()).shutdown_requested
        journal = (await service.rsi_run(agent_id, run["id"], "alice"))["events"]
        assert any(
            e["event"] in {"target_call_started", "agent_call_started"} for e in journal
        )
        assert not any(e["event"] == "target_call_completed" for e in journal)
    finally:
        await service.close()
    store = RsiStore(tmp_path / "runtime/rsi.sqlite3")
    assert store.get(run["id"], "alice", agent_id, "run")["status"] == "cancelled"
    pending = dict(run, id="interrupted-test", status="running")
    store.put(pending, "alice", agent_id, "run")
    reopened = RsiStore(tmp_path / "runtime/rsi.sqlite3")
    assert (
        reopened.get(pending["id"], "alice", agent_id, "run")["status"] == "interrupted"
    )


@pytest.mark.asyncio
async def test_version_skill_overlay_is_agent_local_and_restores_old_bytes(
    tmp_path, monkeypatch
):
    service, agent_id = await setup_service(tmp_path, monkeypatch, RsiModel())
    try:
        root = service.skill_root / "arithmetic"
        root.mkdir(parents=True)
        (root / "SKILL.md").write_text("Reusable arithmetic methods.")
        (root / "diagram.png").write_bytes(b"\x89PNG\xff")
        await service.patch_agent_settings(
            agent_id, AgentSettingsPatch(available_skills=["arithmetic"]), "alice"
        )
        history = await service.rsi_history(agent_id, "alice")
        original_version = history["versions"][0]
        (root / "SKILL.md").write_text("A subsequent shared edit.")
        (root / "diagram.png").write_bytes(b"new-image")
        current = await service._agent(agent_id, "alice")
        await service.apply_rsi_version(
            agent_id,
            original_version["id"],
            RsiApply(confirmed=True, expected_fingerprint=fingerprint(current)),
            "alice",
        )
        agent = await service._agent(agent_id, "alice")
        assert (
            await service._skill_provider(agent).fetch("arithmetic", run_id="test")
        ).files["SKILL.md"] == b"Reusable arithmetic methods."
        assert (root / "SKILL.md").read_text() == "A subsequent shared edit."
        restored = await service._skill_provider(agent).fetch(
            "arithmetic", run_id="test"
        )
        assert restored.files["diagram.png"] == b"\x89PNG\xff"
        assert (root / "diagram.png").read_bytes() == b"new-image"
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_repeated_configuration_is_retained_as_a_new_version(
    tmp_path, monkeypatch
):
    service, agent_id = await setup_service(tmp_path, monkeypatch, RsiModel())
    try:
        original = await service._agent(agent_id, "alice")
        await service.patch_agent_settings(
            agent_id, AgentSettingsPatch(system_prefix="B"), "alice"
        )
        await service.patch_agent_settings(
            agent_id,
            AgentSettingsPatch(system_prefix=original.config["systemPrefix"]),
            "alice",
        )
        history = await service.rsi_history(agent_id, "alice")
        versions = history["versions"]
        assert len(versions) == 3
        assert versions[0]["package_hash"] == versions[-1]["package_hash"]
        assert versions[0]["id"] != versions[-1]["id"]
        assert len((await service.rsi_history(agent_id, "alice"))["versions"]) == 3
    finally:
        await service.close()


@pytest.mark.asyncio
@pytest.mark.timeout(20)
async def test_default_tools_can_load_enabled_skill_in_isolated_rsi(
    tmp_path, monkeypatch
):
    model = RsiModel()
    service, agent_id = await setup_service(tmp_path, monkeypatch, model)
    try:
        root = service.skill_root / "arithmetic"
        root.mkdir(parents=True)
        (root / "SKILL.md").write_text(
            "---\nname: arithmetic\ndescription: Verify arithmetic\n---\nCheck arithmetic independently."
        )
        from sagents.v2.tool.plugins.official import official_tool_definitions

        tools = [d.name for d in official_tool_definitions()] + ["load_skill"]
        await service.patch_agent_settings(
            agent_id, AgentSettingsPatch(available_tools=tools), "alice"
        )
        empty = await service.start_rsi(
            agent_id,
            start_request("empty-skills").model_copy(update={"rounds": 1}),
            "alice",
        )
        await service._rsi_tasks[empty["id"]]
        assert (await service.rsi_run(agent_id, empty["id"], "alice"))[
            "status"
        ] == "completed"
        assert any(t.name == "load_skill" for r in model.requests for t in r.tools)
        model.load_skill = True
        model.requests.clear()
        await service.patch_agent_settings(
            agent_id,
            AgentSettingsPatch(
                available_tools=tools,
                available_skills=["arithmetic"],
            ),
            "alice",
        )
        run = await service.start_rsi(
            agent_id, start_request().model_copy(update={"rounds": 1}), "alice"
        )
        await service._rsi_tasks[run["id"]]
        result = await service.rsi_run(agent_id, run["id"], "alice")
        assert result["status"] == "completed", result
        tool_messages = [
            m for r in model.requests for m in r.messages if m.role == "tool"
        ]
        assert tool_messages
        rendered = "\n".join(m.model_dump_json() for m in tool_messages)
        assert "Skill arithmetic loaded" in rendered, rendered
        assert any(
            "Check arithmetic independently" in r.model_dump_json()
            for r in model.requests
        )
    finally:
        await service.close()


@pytest.mark.asyncio
@pytest.mark.timeout(20)
async def test_rejected_candidates_retained_but_cannot_be_applied(
    tmp_path, monkeypatch
):
    service, agent_id = await setup_service(
        tmp_path, monkeypatch, RsiModel(reject=True)
    )
    try:
        agent = await service._agent(agent_id, "alice")
        run = await service.start_rsi(agent_id, start_request(), "alice")
        await service._rsi_tasks[run["id"]]
        record = await service.rsi_run(agent_id, run["id"], "alice")
        assert record["status"] == "completed"
        rejected = record["result"]["iterations"][1:]
        assert len(rejected) == 3 and all(
            item["review"]["approved"] is False for item in rejected
        )
        assert all(item["evaluation"] is None for item in rejected)
        with pytest.raises(ValueError, match="rejected"):
            await service.apply_rsi_version(
                agent_id,
                f"{run['id']}.1",
                RsiApply(confirmed=True, expected_fingerprint=fingerprint(agent)),
                "alice",
            )
        assert fingerprint(await service._agent(agent_id, "alice")) == fingerprint(
            agent
        )
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_rsi_http_routes_auth_and_explicit_confirmation(tmp_path):
    import httpx
    from app.v2.desktop.backend.app import create_app

    service = DesktopV2Service(tmp_path)
    try:
        agent = await service.create_agent(AgentCreate(name="Sage"), "default_user")
        app = create_app(service=service, auth_token="rsi-test-token")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://desktop"
        ) as client:
            path = f"/api/v2/agents/{agent['id']}/rsi"
            assert (await client.get(path)).status_code == 401
            client.headers["Authorization"] = "Bearer rsi-test-token"
            history = (await client.get(path)).json()["data"]
            version = history["versions"][0]
            assert (await client.get(f"{path}/versions/{version['id']}")).json()[
                "data"
            ]["package"]
            apply_path = f"{path}/versions/{version['id']}/apply"
            body = {"expected_fingerprint": history["current_fingerprint"]}
            assert (await client.post(apply_path, json=body)).status_code == 422
            assert (
                await client.post(apply_path, json={**body, "confirmed": False})
            ).status_code == 422
            assert (
                await client.post(apply_path, json={**body, "confirmed": True})
            ).status_code == 200
            assert (await client.get(f"{path}/runs/missing")).status_code == 400
    finally:
        await service.close()


@pytest.mark.asyncio
@pytest.mark.timeout(20)
async def test_legacy_operation_names_do_not_break_history_or_rsi(
    tmp_path, monkeypatch
):
    model = RsiModel()
    service, agent_id = await setup_service(tmp_path, monkeypatch, model)
    stale_names = [
        "code.search",
        "plan.update",
        "process.run",
        "workspace.create_file",
        "workspace.delete_file",
        "workspace.list_files",
        "workspace.read_file",
        "workspace.write_file",
    ]
    try:
        agent = await service._agent(agent_id, "alice")
        tools = ["file_read", "grep", *stale_names]
        config = {**agent.config, "availableTools": tools}
        await service.catalog.save_agent(agent.model_copy(update={"config": config}))
        history = await service.rsi_history(agent_id, "alice")
        latest = next(v for v in history["versions"] if v["source"] == "settings")
        version = await service.rsi_version(agent_id, latest["id"], "alice")
        assert version["config"]["availableTools"] == tools
        assert version["package"]["manifest"]["agents"][agent_id]["tools"] == [
            "file_read",
            "grep",
        ]
        run = await service.start_rsi(
            agent_id, start_request().model_copy(update={"rounds": 1}), "alice"
        )
        await service._rsi_tasks[run["id"]]
        result = await service.rsi_run(agent_id, run["id"], "alice")
        assert result["status"] == "completed", result
        assert (await service._agent(agent_id, "alice")).config == config
        # A confirmed restore preserves the original configuration, and its next
        # history read must still work despite retained legacy names.
        await service.apply_rsi_version(
            agent_id,
            version["id"],
            RsiApply(
                confirmed=True, expected_fingerprint=history["current_fingerprint"]
            ),
            "alice",
        )
        assert (await service.rsi_history(agent_id, "alice"))["versions"]
        assert (await service._agent(agent_id, "alice")).config[
            "availableTools"
        ] == tools
    finally:
        await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("selection", [None, []])
async def test_snapshot_matches_default_and_explicit_empty_tool_selection(
    tmp_path, monkeypatch, selection
):
    service, agent_id = await setup_service(tmp_path, monkeypatch, RsiModel())
    try:
        agent = await service._agent(agent_id, "alice")
        config = {**agent.config, "availableTools": selection}
        agent = agent.model_copy(update={"config": config})
        package = await service._agent_bundle(agent)
        expected = (
            tuple(d.name for d in service._native_tool_definitions())
            if selection is None
            else ()
        )
        assert package.manifest.agents[agent_id].tools == expected
        assert agent.config == config
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_snapshot_preserves_external_tools_for_rsi_binding_rejection(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    service, agent_id = await setup_service(tmp_path, monkeypatch, RsiModel())

    class ExternalTools:
        async def list_tools(self, **kwargs):
            return (SimpleNamespace(name="external_lookup"),)

    async def external_plugin(*args):
        return ExternalTools()

    monkeypatch.setattr(service, "_mcp_plugin", external_plugin)
    try:
        agent = await service._agent(agent_id, "alice")
        agent = agent.model_copy(
            update={"config": {**agent.config, "availableTools": None}}
        )
        await service.catalog.save_agent(agent)
        package = await service._agent_bundle(agent)
        assert "external_lookup" in package.manifest.agents[agent_id].tools
        assert (await service.rsi_history(agent_id, "alice"))["versions"]
        with pytest.raises(ValueError, match="external MCP tools"):
            await service.start_rsi(agent_id, start_request(), "alice")
        assert not service._rsi_tasks
    finally:
        await service.close()

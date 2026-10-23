
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Any, Literal

from sagents.v2.agent.management import AgentPackageBundle
from sagents.v2.contracts.items import TextBlock

import asyncio
import json

import pytest
from pydantic import ValidationError

from app.v2.desktop.backend.rsi import RsiApply, RsiStart, RsiStore, fingerprint
from app.v2.desktop.backend.service import DesktopV2Service
from app.v2.desktop.backend.schemas import (
    AgentCreate,
    DesktopRunRequest,
    RunMessage,
    AgentSettingsPatch,
    ModelProviderCreate,
)
from app.v2.desktop.backend.sidecar_lifecycle import SidecarClientLeases
from sagents.v2.optimization import (
    OptimizationCase,
    OptimizationSuite,
)
from sagents.v2.testing.plugins.scripted_model import ScriptedModelProvider
from sagents.v2.model.contracts import (
    ModelEventKind,
    ModelResponse,
    ModelStreamEvent,
    ModelToolCall,
)


def authored_response(request, payload, changes):
    """Scripted model authors real package files through the runtime file tools."""
    if any(m.role == "tool" and str(m.tool_call_id).startswith("author-") for m in request.messages):
        return ModelResponse(response_id="authored", text=json.dumps({"rationale": changes["rationale"]}), finish_reason="stop")
    data = payload["data"]
    manifest = data["package"]["manifest"]
    identity = data["agent_id"]
    files = {}
    if changes.get("system_prompt"):
        files[data["candidate_workspace"]["system_prompt"]] = changes["system_prompt"]
    for name, spec in changes.get("tool_definitions", {}).items():
        files[f"package/files/tools/rsi/{name}.json"] = json.dumps(spec)
    for key in ("tools", "skills"):
        if key in changes:
            manifest["agents"][identity][key] = changes[key]
    if changes.get("tool_definitions") or changes.get("skills"):
        # Keep the prompt's staged resource reference in the authored manifest.
        manifest["agents"][identity]["instructions"] = {"path": data["candidate_workspace"]["system_prompt"].removeprefix("package/files/")}
        files["package/manifest.json"] = json.dumps(manifest)
    return ModelResponse(response_id="author", finish_reason="tool_calls", tool_calls=tuple(
        ModelToolCall(tool_call_id=f"author-{i}", name="file_write", arguments={"file_path": name, "content": content})
        for i, (name, content) in enumerate(files.items())
    ))


def authored_evaluation_response(request, payload, answer):
    if payload.get('data', {}).get('protocol') != 'sage.rsi.evaluation-files/v1':
        return None
    completed = {m.tool_call_id for m in request.messages if m.role == 'tool'}
    ranges = [(document['path'], first, last) for document in payload['data']['files']
              for first, last in document['read_ranges']]
    if not all(f'read-evaluation-{i}' in completed for i in range(len(ranges))):
        return ModelResponse(response_id='read-evaluation', finish_reason='tool_calls', tool_calls=tuple(
            ModelToolCall(tool_call_id=f'read-evaluation-{i}', name='file_read', arguments={
                'file_path': name, 'start_line': first, 'end_line': last, 'include_line_numbers': False})
            for i, (name, first, last) in enumerate(ranges)))
    if 'write-evaluation' not in completed:
        return ModelResponse(response_id='write-evaluation', finish_reason='tool_calls', tool_calls=(
            ModelToolCall(tool_call_id='write-evaluation', name='file_write', arguments={
                'file_path': 'assessment.json', 'content': json.dumps(answer)}),))
    return ModelResponse(response_id='assessment-saved', text='Assessment file saved', finish_reason='stop')


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
            await cast('Any', self.release).wait()
        messages = [m for m in request.messages if m.role == "user"]
        raw = "".join(
            cast(TextBlock, block).text for block in messages[-1].content if hasattr(block, "text")
        )
        # Runtime context wraps the latest user request. Judge/tuner payloads
        # remain JSON inside that envelope, rather than being the entire text.
        if "<user_request>" in raw:
            raw = (
                raw.split("<user_request>", 1)[1]
                .rsplit("</user_request>", 1)[0]
                .strip()
            )
        try:
            properties = (
                json.loads(raw).get("response_schema", {}).get("properties", {})
            )
        except json.JSONDecodeError:
            properties = {}
        if "goal_drift_detected" in properties:
            answer = dict(
                approved=not self.reject,
                memorization_detected=False,
                goal_drift_detected=self.reject,
                permission_drift_detected=False,
                rationale="Reusable method",
                findings=[],
            )
        elif "cases" in properties:
            data = json.loads(raw)["data"]
            offset = len(data["excluded_cases"])
            answer = {
                "cases": [
                    {
                        "id": f"challenge-{offset}",
                        "input": f"Calculate {offset}+42-{offset}",
                        "rubric": "42",
                        "split": "training",
                    }
                ]
            }
        elif "issues" in properties:
            answer = dict(
                approved=True, rationale="Goal and suites are consistent", issues=[]
            )
        elif "instruction_guidance" in properties or set(properties) == {"rationale", "experience_notes"}:
            answer = dict(
                rationale="Reusable arithmetic verification",
                system_prompt="Answer accurately. Verify calculations before answering.",
            )
        elif "priorities" in properties:
            answer = {"summary": "Preserve verified arithmetic behavior", "priorities": [], "uncertainties": []}
        elif "score" in properties:
            answer = dict(
                score=0.9,
                passed=True,
                rationale="Correct response with room for improvement",
                diagnosis={"summary": "Recorded arithmetic answer was checked", "findings": [],
                    "strengths": ["Answer agrees with the fixed arithmetic rubric"],
                    "uncertainties": [], "coverage": "Complete provided conversation"},
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
        if set(properties) == {"rationale", "experience_notes"}:
            yield ModelStreamEvent(kind=ModelEventKind.COMPLETED,
                response=authored_response(request, json.loads(raw), answer))
            return
        evaluation = authored_evaluation_response(request, json.loads(raw), answer) if properties else None
        if evaluation is not None:
            yield ModelStreamEvent(kind=ModelEventKind.COMPLETED, response=evaluation)
            return
        yield ModelStreamEvent(
            kind=ModelEventKind.COMPLETED,
            response=ModelResponse(
                response_id="answer",
                text=json.dumps(answer) if isinstance(answer, dict) else answer,
                finish_reason="stop",
            ),
        )


@pytest.mark.asyncio
async def test_desktop_tuner_reads_training_evidence_without_granting_target_file_access(tmp_path, monkeypatch):
    class EvidenceReader(RsiModel):
        reads = 0
        async def _stream(self, request):
            if any(t.name == 'file_update' for t in request.tools):
                assert {t.name for t in request.tools} == {'file_read', 'file_write', 'file_update'}
                responses = [m for m in request.messages if m.role == 'tool']
                if not responses:
                    self.requests.append(request)
                    self.reads += 1
                    yield ModelStreamEvent(kind=ModelEventKind.COMPLETED, response=ModelResponse(
                        response_id='read-evidence', finish_reason='tool_calls', tool_calls=(
                            ModelToolCall(tool_call_id='read-evidence', name='file_read',
                                arguments={'file_path': 'evidence/training-evidence/index.json', 'include_line_numbers': False}),)))
                    return
                rendered = '\n'.join(m.model_dump_json() for m in responses)
                assert 'reading_order' in rendered and 'rejected_attempts' in rendered, rendered
                assert '40 plus 2?' not in rendered
            async for event in super()._stream(request):
                yield event
    model = EvidenceReader()
    service, agent_id = await setup_service(tmp_path, monkeypatch, model)
    try:
        before = await service._agent(agent_id, 'alice')
        started = await service.start_rsi(agent_id, start_request().model_copy(update={'rounds': 1}), 'alice')
        await service._rsi_tasks[started['id']]
        run = await service.rsi_run(agent_id, started['id'], 'alice')
        assert run['status'] == 'completed', run
        assert model.reads == 1
        workspace = await service.workspace_root(run['workspace_id'], agent_id)
        assert str(workspace) == run['workspace_path']
        assert workspace == service.runtime_root / 'rsi' / started['id'] / 'workspace'
        assert (workspace / 'iterations/round-001/editor/evidence/training-evidence/index.json').exists()
        assert (workspace / 'iterations/round-000/evaluation/training-evidence/index.json').exists()
        assert (workspace / 'iterations/round-001/input/training-evidence/index.json').exists()
        assert not (workspace / 'audit.jsonl').exists()
        content, _ = await service.read_file(run['workspace_id'], agent_id, 'iterations/round-001/editor/evidence/training-evidence/index.json')
        assert json.loads(content)['reading_order'] == ['mixed', 'failed', 'passed']
        with pytest.raises(PermissionError):
            await service.read_file(run['workspace_id'], agent_id, '../audit.jsonl')
        assert (await service._agent(agent_id, 'alice')).config == before.config
        assert before.config['availableTools'] == []
    finally:
        await service.close()


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
        validation_case_count=1,
        initial_training_case_count=1,
        training_cases_per_round=1,
    )


@pytest.mark.asyncio
@pytest.mark.timeout(180)
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
        assert run["result"]["report"]["final_verification"] is None
        assert run["validation_case_count"] == 1
        assert (await service._agent(agent_id, "alice")).config == original.config
        history = await service.rsi_history(agent_id, "alice")
        candidates = [v for v in history["versions"] if v["source"] == "rsi"]
        assert len(candidates) == 4
        assert all(
            "package" not in v and "config" not in v for v in history["versions"]
        )
        with pytest.raises(ValidationError):
            RsiApply(confirmed=cast('Literal[True]', False), expected_fingerprint=fingerprint(original))
        with pytest.raises(ValueError, match="not configured"):
            await service.rsi_version(agent_id, candidates[0]["id"], "bob")
        chosen = next(v for v in candidates if v["iteration"] == 1)
        version = await service.rsi_version(agent_id, chosen["id"], "alice")
        assert version["review"]["approved"]
        assert (
            "Verify calculations"
            in AgentPackageBundle.model_validate(version["package"]).resolved_manifest().agents[agent_id].instructions.inline
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
@pytest.mark.timeout(180)
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
        evaluation_inputs = list((service.runtime_root / 'rsi' / run['id'] / 'evaluations').rglob('context.json'))
        assert any(json.loads(path.read_text()).get('agent_configuration', {}).get('resources') for path in evaluation_inputs)
        assert any('Check arithmetic independently.' in path.read_text()
            for path in (service.runtime_root / 'rsi' / run['id'] / 'evaluations').rglob('configuration-001.md'))
    finally:
        await service.close()


@pytest.mark.asyncio
@pytest.mark.timeout(180)
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
@pytest.mark.timeout(180)
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


@pytest.mark.parametrize(
    "options",
    [
        {"initial_training_case_count": 0},
        {"initial_training_case_count": 101},
        {"training_cases_per_round": -1},
        {"training_cases_per_round": 101},
        {"validation_case_count": 0},
        {"test_case_count": 101},
        {"max_concurrency": 0},
        {"max_concurrency": 17},
    ],
)
def test_rsi_rejects_invalid_case_and_parallel_limits(options):
    with pytest.raises(ValidationError):
        RsiStart(goal="Improve reliability", request_id="bounded-options", **options)


class ToolCreatingRsiModel(RsiModel):
    async def _stream(self, request):
        raw = "".join(
            getattr(b, "text", "")
            for m in request.messages
            if m.role == "user"
            for b in m.content
        )
        if "<user_request>" in raw:
            raw = (
                raw.split("<user_request>")[-1].rsplit("</user_request>", 1)[0].strip()
            )
        try:
            properties = (
                json.loads(raw).get("response_schema", {}).get("properties", {})
            )
        except ValueError:
            properties = {}
        if "instruction_guidance" in properties or set(properties) == {"rationale", "experience_notes"}:
            # Tuner writes a new implementation, not a pre-existing native tool.
            answer = {
                "rationale": "Move arithmetic into a reusable pure calculator",
                "tools": ["rsi_multiply"],
                "tool_definitions": {
                    "rsi_multiply": {
                        "description": "Multiply two numbers",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "a": {"type": "number"},
                                "b": {"type": "number"},
                            },
                            "required": ["a", "b"],
                            "additionalProperties": False,
                        },
                        "expression": {
                            "op": "mul",
                            "args": [{"var": "a"}, {"var": "b"}],
                        },
                    }
                },
            }
            if set(properties) == {"rationale", "experience_notes"}:
                yield ModelStreamEvent(kind=ModelEventKind.COMPLETED,
                    response=authored_response(request, json.loads(raw), answer))
                return
            yield ModelStreamEvent(
                kind=ModelEventKind.COMPLETED,
                response=ModelResponse(
                    response_id="new-tool",
                    text=json.dumps(answer),
                    finish_reason="stop",
                ),
            )
            return
        if any(t.name == "rsi_multiply" for t in request.tools) and not any(
            m.role == "tool" for m in request.messages
        ):
            yield ModelStreamEvent(
                kind=ModelEventKind.COMPLETED,
                response=ModelResponse(
                    response_id="invoke-created-tool",
                    tool_calls=(
                        ModelToolCall(
                            tool_call_id="multiply",
                            name="rsi_multiply",
                            arguments={"a": 6, "b": 7},
                        ),
                    ),
                    finish_reason="tool_calls",
                ),
            )
            return
        async for event in super()._stream(request):
            yield event


@pytest.mark.asyncio
async def test_rsi_creates_tool_executes_it_and_versions_implementation(
    tmp_path, monkeypatch
):
    model = ToolCreatingRsiModel()
    service, agent_id = await setup_service(tmp_path, monkeypatch, model)
    try:
        request = start_request().model_copy(
            update={
                "rounds": 1,
                "optimization_scope": ("instructions", "tools"),
            }
        )
        started = await service.start_rsi(agent_id, request, "alice")
        await service._rsi_tasks[started["id"]]
        run = await service.rsi_run(agent_id, started["id"], "alice")
        assert run["status"] == "completed", run.get("error")
        version = await service.rsi_version(agent_id, f"{started['id']}.1", "alice")
        assert "tools/rsi/rsi_multiply.json" in version["package"]["files"]
        assert any(
            m.role == "tool" and m.tool_call_id == "multiply"
            for r in model.requests
            for m in r.messages
        )
        assert version["ready"]
        original = await service._agent(agent_id, "alice")
        assert original.config["availableTools"] == []
        await service.apply_rsi_version(
            agent_id,
            version["id"],
            RsiApply(confirmed=True, expected_fingerprint=fingerprint(original)),
            "alice",
        )
        updated = await service._agent(agent_id, "alice")
        assert updated.config["availableTools"] == ["rsi_multiply"]
        settings = await service.get_settings()
        await service.save_settings(
            settings.model_copy(
                update={
                    "component_selections": {
                        **settings.component_selections,
                        "tool.selection-policy": "sage.tool-selection.direct",
                        "agent.continuation-policy": "sage.agent.continuation.deterministic",
                    }
                }
            )
        )
        frames = [
            json.loads(frame)
            async for frame in service.run_events(
                DesktopRunRequest(
                    agent_id=agent_id,
                    messages=[RunMessage(role="user", text="6 times 7?")],
                    idempotency_key="activated-tool-execution",
                    run_context={
                        "model_provider_id": updated.config["llm_provider_id"],
                        "fast_model_provider_id": updated.config["llm_provider_id"],
                    },
                ),
                "alice",
            )
        ]
        tool_results = [
            frame.get("data", {}).get("item", {}).get("data", {})
            for frame in frames
            if frame.get("data", {}).get("item")
        ]
        assert any(
            item.get("kind") == "tool_result"
            and item.get("tool_call_id") == "multiply"
            and item.get("error") is None
            and any(block.get("text") == "42" for block in item.get("content", []))
            for item in tool_results
        ), tool_results
        # The next RSI snapshot keeps the executable definition as well as its name.
        package = await service._agent_bundle(updated)
        assert "tools/rsi/rsi_multiply.json" in package.files
        await service.start_rsi(agent_id, start_request("next-run"), "alice")
    finally:
        await service.close()


def test_large_rsi_workload_gets_a_bounded_deadline_scaled_to_parallelism():
    from app.v2.desktop.backend.rsi import rsi_timeout_seconds

    request = RsiStart(goal="Customer service", request_id="budget", rounds=8)
    assert 3600 < rsi_timeout_seconds(request) <= 86400
    assert rsi_timeout_seconds(
        request.model_copy(update={"max_concurrency": 1})
    ) >= rsi_timeout_seconds(request)
    assert (
        rsi_timeout_seconds(
            request.model_copy(
                update={
                    "rounds": 100,
                    "validation_case_count": 100,
                    "max_concurrency": 1,
                    "evaluation_repeats": 10,
                }
            )
        )
        == 86400
    )


@pytest.mark.asyncio
async def test_human_test_checkpoints_are_durable_and_absent_from_optimizer_payloads(tmp_path, monkeypatch):
    from sagents.v2.optimization.contracts import OptimizationTestSuite
    model = RsiModel()
    service, agent_id = await setup_service(tmp_path, monkeypatch, model)
    try:
        request = start_request().model_copy(update={"human_test_repeats": 2, "human_test_suite": OptimizationTestSuite(cases=(
            OptimizationCase(id="sealed-holdout-canary-731", input="Human-only question: 21+21?", rubric="42", split="test"),
        ))})
        started = await service.start_rsi(agent_id, request, "alice")
        await service._rsi_tasks[started['id']]
        run = await service.rsi_run(agent_id, started['id'], 'alice')
        assert run['status'] == 'completed', run
        assert run['human_test_repeats'] == 2
        assert all(r['repeats'] == 2 and len(r['cases'][0]['trials']) == 2 for r in run['test_observations'])
        assert all([t['trial'] for t in r['cases'][0]['trials']] == [1, 2] for r in run['test_observations'])
        assert [r['round'] for r in run['test_observations']] == [0, 1, 2, 3]
        assert all(r['status'] == 'completed' and r['scores']['test'] == .9 for r in run['test_observations'])
        assert not any(marker in json.dumps(run['result']) for marker in ('sealed-holdout-canary-731',))
        assert not any(marker in json.dumps(run['events']) for marker in ('Human-only question',))
        await service.close()
        restarted = DesktopV2Service(tmp_path)
        try:
            restored = await restarted.rsi_run(agent_id, started['id'], 'alice')
            assert restored['test_observations'] == run['test_observations']
        finally:
            await restarted.close()
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_independent_test_generation_uses_requested_count_and_separate_storage(tmp_path, monkeypatch):
    class TestDesignerModel(RsiModel):
        async def _stream(self, request):
            text = request.model_dump_json()
            if 'Generate ONLY split=test' in text:
                self.requests.append(request)
                answer = {'cases': [dict(id=f'holdout-{i}', input=f'Independent sealed probe {i}',
                    rubric='42', split='test') for i in range(2)]}
                yield ModelStreamEvent(kind=ModelEventKind.COMPLETED,
                    response=ModelResponse(response_id='sealed', text=json.dumps(answer), finish_reason='stop'))
                return
            async for item in super()._stream(request):
                yield item
    model = TestDesignerModel()
    service, agent_id = await setup_service(tmp_path, monkeypatch, model)
    try:
        request = start_request().model_copy(update={'human_test_count': 2, 'rounds': 1})
        started = await service.start_rsi(agent_id, request, 'alice')
        await service._rsi_tasks[started['id']]
        run = await service.rsi_run(agent_id, started['id'], 'alice')
        assert run['status'] == 'completed'
        assert len(run['human_test_suite']['cases']) == 2
        assert [r['round'] for r in run['test_observations']] == [0, 1]
        assert all(len(r['cases']) == 2 and r['status'] == 'completed' for r in run['test_observations'])
        assert not any(marker in json.dumps(run['result']) for marker in ('Independent sealed probe',))
    finally:
        await service.close()


@pytest.mark.asyncio
@pytest.mark.timeout(180)
async def test_interrupted_rsi_resumes_same_run_after_service_restart_without_repeating_cases(tmp_path, monkeypatch):
    class CutSecondTuning(RsiModel):
        cut = True
        target_calls = 0
        async def _stream(self, request):
            messages = [m for m in request.messages if m.role == 'user']
            raw = ''.join(block.text for block in messages[-1].content if hasattr(block, 'text'))
            if '<user_request>' in raw:
                raw = raw.split('<user_request>', 1)[1].rsplit('</user_request>', 1)[0].strip()
            try:
                data = json.loads(raw)
            except ValueError:
                data = {}
            props = data.get('response_schema', {}).get('properties', {})
            if ('instruction_guidance' in props or set(props) == {'rationale', 'experience_notes'}) and data['data']['round'] == 2 and self.cut:
                raise ConnectionError('Simulated interruption before second proposal')
            if not props:
                self.target_calls += 1
            async for event in super()._stream(request):
                yield event
    first = CutSecondTuning()
    service, agent_id = await setup_service(tmp_path, monkeypatch, first)
    run = await service.start_rsi(agent_id, start_request(), 'alice')
    await service._rsi_tasks[run['id']]
    old = await service.rsi_run(agent_id, run['id'], 'alice')
    assert old['status'] == 'failed' and old['resumable']
    original_completed = [e for e in old["events"] if e["event"] == "case_completed"]
    assert first.target_calls == len(original_completed) >= 4
    old_sequence = old['sequence']
    await service.close()
    second = CutSecondTuning()
    second.cut = False
    reopened = DesktopV2Service(tmp_path)
    async def bind(*args, **kwargs):
        return second
    monkeypatch.setattr(reopened, '_model_provider', bind)
    try:
        import httpx
        from app.v2.desktop.backend.app import create_app
        monkeypatch.setattr('app.v2.desktop.backend.app.get_desktop_user_id', lambda request: 'alice')
        app = create_app(service=reopened, auth_token='resume-test-token')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://desktop') as client:
            endpoint = f"/api/v2/agents/{agent_id}/rsi/runs/{run['id']}/resume"
            assert (await client.post(endpoint)).status_code == 401
            response = await client.post(endpoint, headers={'Authorization': 'Bearer resume-test-token'})
            assert response.status_code == 200, response.text
            continuing = response.json()['data']
        assert continuing['id'] == run['id']
        await reopened._rsi_tasks[run['id']]
        finished = await reopened.rsi_run(agent_id, run['id'], 'alice')
        assert finished['status'] == 'completed', finished
        assert finished['resume_count'] == 1
        assert finished['workspace_id'] == old['workspace_id']
        assert finished['workspace_path'] == old['workspace_path']
        settings = await reopened.get_settings()
        assert sum(p.id == finished['workspace_id'] for p in settings.projects) == 1
        workspace = await reopened.workspace_root(finished['workspace_id'], agent_id)
        assert (workspace / 'iterations/round-000/evaluation.json').exists()
        assert (workspace / 'iterations/round-003/decision.json').exists()
        recovered_cases = [e for e in finished["events"] if e["event"] == "case_completed" and e["data"].get("recovered")]
        assert len(recovered_cases) == len(original_completed)
        assert second.target_calls == len([e for e in finished["events"] if e["event"] == "target_call_started"])
        assert len(finished['result']['report']['rounds']) == 3
        assert finished['events'][0]['sequence'] > old_sequence
        root = reopened.runtime_root / 'rsi' / run['id']
        assert (root / 'audit.jsonl').exists()
        assert (root / finished['journal_name']).exists()
        assert (root / 'resume-context.json').stat().st_mode & 0o777 == 0o600
        with pytest.raises(ValueError, match='cannot resume'):
            await reopened.resume_rsi(agent_id, run['id'], 'alice')
    finally:
        await reopened.close()


@pytest.mark.asyncio
@pytest.mark.timeout(180)
async def test_five_transient_gateway_failures_recover_automatically_without_repeating_completed_cases(tmp_path, monkeypatch):
    from sagents.v2.optimization.contracts import OptimizationObservation
    class GatewayModel(RsiModel):
        failures = 0
        target_calls = 0
        async def _stream(self, request):
            messages = [m for m in request.messages if m.role == 'user']
            raw = ''.join(block.text for block in messages[-1].content if hasattr(block, 'text'))
            if '<user_request>' in raw:
                raw = raw.split('<user_request>', 1)[1].rsplit('</user_request>', 1)[0].strip()
            try:
                data = json.loads(raw)
            except ValueError:
                data = {}
            props = data.get('response_schema', {}).get('properties', {})
            if not props:
                self.target_calls += 1
            async for event in super()._stream(request):
                yield event
    model = GatewayModel()
    service, agent_id = await setup_service(tmp_path, monkeypatch, model)
    from sagents.v2 import IsolatedOptimizationRunner
    original_run = IsolatedOptimizationRunner.run
    failures = []
    async def interrupted_run(runner, package, agent_id, content, context):
        if package.manifest.metadata.id == 'desktop.rsi.tuner' and json.loads(content)['data']['round'] == 2 and len(failures) < 5:
            failures.append(1)
            return OptimizationObservation(state='failed', evidence={'error': {
                'code': 'model.provider_transient', 'category': 'provider_transient', 'provider_code': '502', 'retryable': True}})
        return await original_run(runner, package, agent_id, content, context)
    monkeypatch.setattr(IsolatedOptimizationRunner, 'run', interrupted_run)
    delays = []
    async def wait(seconds):
        delays.append(seconds)
        stored = service.rsi_store.list('alice', agent_id, 'run')[0]
        displayed = await service.rsi_run(agent_id, stored['id'], 'alice')
        assert displayed['events']  # waiting retains the previous audit, not a blank page
        assert displayed['status'] == 'running'
    monkeypatch.setattr(service, '_rsi_retry_wait', wait)
    try:
        request = start_request().model_copy(update={'grow_training': False})
        run = await service.start_rsi(agent_id, request, 'alice')
        await service._rsi_tasks[run['id']]
        final = await service.rsi_run(agent_id, run['id'], 'alice')
        assert final['status'] == 'completed', final
        assert final['automatic_recoveries'] == 5
        assert delays == [2, 4, 8, 16, 32]
        assert model.target_calls == 8  # baseline pair + three candidate pairs, no repeated executions
        assert len(final['result']['report']['rounds']) == 3
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_suspended_file_evaluation_transport_recovers_without_repeating_target(tmp_path, monkeypatch):
    from sagents.v2 import IsolatedOptimizationRunner
    from sagents.v2.optimization.contracts import OptimizationObservation
    service, agent_id = await setup_service(tmp_path, monkeypatch, RsiModel())
    original = IsolatedOptimizationRunner.run
    interrupted, target_inputs, finished_targets = [], [], []
    targets_finished = asyncio.Event()

    async def run(runner, package, selected, content, context):
        identity = package.manifest.metadata.id
        if identity == 'desktop.rsi.evaluator':
            await targets_finished.wait()
        if identity == 'desktop.rsi.evaluator' and not interrupted:
            interrupted.append(True)
            return OptimizationObservation(state='suspended', evidence={'runtime_events': [
                {'type': 'interaction.requested', 'data': {'payload': {'error': {
                    'code': 'model.stream_incomplete', 'category': 'provider_transient',
                    'retryable': True}}}}]})
        if not identity.startswith('desktop.rsi.'):
            target_inputs.append(content)
        result = await original(runner, package, selected, content, context)
        if not identity.startswith('desktop.rsi.'):
            finished_targets.append(True)
            if len(finished_targets) >= 2:
                targets_finished.set()
        return result

    monkeypatch.setattr(IsolatedOptimizationRunner, 'run', run)
    async def wait(seconds):
        pass
    monkeypatch.setattr(service, '_rsi_retry_wait', wait)
    try:
        request = start_request().model_copy(update={'grow_training': False, 'rounds': 1})
        started = await service.start_rsi(agent_id, request, 'alice')
        await service._rsi_tasks[started['id']]
        final = await service.rsi_run(agent_id, started['id'], 'alice')
        assert interrupted
        assert final['status'] == 'completed', final
        assert final['automatic_recoveries'] == 1
        assert len(target_inputs) == 4  # baseline and candidate; evaluation alone was retried
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_default_file_evaluation_repairs_nested_diagnosis_indexes_without_repeating_target(tmp_path, monkeypatch):
    original = RsiModel._stream.__globals__['authored_evaluation_response']
    bad_written = []
    def authored(request, payload, answer):
        if payload.get('response_schema', {}).get('title') == 'OptimizationGrade' and not bad_written:
            answer = {**answer, 'diagnosis': {**answer['diagnosis'], 'findings': [{
                'category': 'Unsupported citation', 'cause': 'Fixture cites unavailable evidence',
                'evidence_indexes': [999], 'recommendation': 'Use actual message indexes',
                'scope': 'procedure', 'confidence': 'hypothesis'}]}}
        response = original(request, payload, answer)
        if response and any(call.name == 'file_write' for call in response.tool_calls):
            bad_written.append(True)
        return response
    monkeypatch.setitem(RsiModel._stream.__globals__, 'authored_evaluation_response', authored)
    class Model(RsiModel):
        target_calls = 0
        async def _stream(self, request):
            raw = ''.join(getattr(block, 'text', '') for message in request.messages if message.role == 'user' for block in message.content)
            if '<user_request>' in raw:
                raw = raw.rsplit('<user_request>', 1)[1].split('</user_request>', 1)[0].strip()
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = {}
            if not payload.get('response_schema'):
                self.target_calls += 1
            async for event in super()._stream(request):
                yield event
    model = Model()
    service, agent = await setup_service(tmp_path, monkeypatch, model)
    try:
        started = await service.start_rsi(agent, start_request().model_copy(update={'rounds': 1, 'grow_training': False}), 'alice')
        await service._rsi_tasks[started['id']]
        run = await service.rsi_run(agent, started['id'], 'alice')
        assert run['status'] == 'completed', run.get('error_type')
        assert model.target_calls == 4
        rejected = [event for event in run['events'] if event['event'] == 'evaluation_response_rejected']
        assert len(rejected) == 1 and 'outside' in rejected[0]['data']['reason']
        assert all(case['grade']['diagnosis'] for case in run['result']['report']['baseline']['cases'])
    finally:
        await service.close()

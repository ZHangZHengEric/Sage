"""Exercise Server RSI through HTTP and the real optimizer/runtime with a fake model."""

import asyncio
import json

import pytest

from sagents.v2.model.contracts import ModelEventKind, ModelResponse, ModelStreamEvent, ModelToolCall
from sagents.v2.testing.plugins import ScriptedModelProvider
from tests.app.v2.server.conftest import register_and_login


def payload_for(request):
    raw = "".join(getattr(b, "text", "") for m in request.messages if m.role == "user" for b in m.content)
    if "<user_request>" in raw:
        raw = raw.split("<user_request>")[-1].split("</user_request>")[0].strip()
    try:
        return json.loads(raw)
    except ValueError:
        return {}


def fixture_experiment(payload):
    data = payload["data"]
    return {"parent_hash": data["retained_parent_hash"], "mechanism": "Verify arithmetic",
        "applicability": "Arithmetic", "change_locations": ["system_prompt"],
        "existing_rule_gap": "No verification", "expected_observation": "Correct arithmetic",
        "support_condition": "Wrong becomes correct", "falsification_condition": "Still wrong",
        "inconclusive_condition": "No relevant evidence", "training_case_ids": data["measured_training_case_ids"],
        "protected_behaviors": ["Preserve authorization"]}


class RsiModel(ScriptedModelProvider):
    def __init__(self, entered=None, release=None):
        super().__init__(())
        self.entered, self.release = entered, release

    async def _stream(self, request):
        if self.entered is not None:
            self.entered.set()
            await self.release.wait()
        self.requests.append(request)
        payload = payload_for(request)
        properties = payload.get("response_schema", {}).get("properties", {})
        if "priorities" in properties:
            answer = {"summary": "Verify arithmetic", "priorities": [], "uncertainties": [],
                "next_action": "test_hypothesis", "next_verification": "Compare verification with baseline"}
        elif "cases" in properties:
            split = "validation" if "split=validation" in payload["task"] else "training"
            answer = {"cases": [{"id": f"{split}-{index}", "input": f"Calculate {index}+42-{index}",
                "rubric": "42", "split": split} for index in range(payload["data"]["case_count"])]}
        else:
            answer = "42"
        yield ModelStreamEvent(kind=ModelEventKind.COMPLETED, response=ModelResponse(response_id="fixture",
            text=json.dumps(answer) if isinstance(answer, dict) else answer, finish_reason="stop"))


class ImprovingModel(RsiModel):
    async def _stream(self, request):
        payload = payload_for(request)
        properties = payload.get("response_schema", {}).get("properties", {})
        if "instruction_guidance" in properties:
            answer = {"rationale": "Verify arithmetic", "system_prompt": "Verify calculations before answering.",
                "experiment": fixture_experiment(payload)}
        elif "score" in properties:
            improved = payload["data"]["observation"]["output"] == "verified 42"
            answer = {"score": 0.8 if improved else 0.4, "passed": improved, "rationale": "Measured arithmetic",
                "diagnosis": {"summary": "Verify arithmetic", "findings": [], "strengths": [],
                    "uncertainties": [], "coverage": "Complete execution"}}
        elif not properties:
            improved = "Verify calculations before answering." in str(request.messages)
            answer = "verified 42" if improved else "42"
        else:
            async for event in super()._stream(request):
                yield event
            return
        self.requests.append(request)
        yield ModelStreamEvent(kind=ModelEventKind.COMPLETED, response=ModelResponse(
            response_id="rsi-fixture", text=json.dumps(answer) if isinstance(answer, dict) else answer, finish_reason="stop"))


class SkillModel(ImprovingModel):
    async def _stream(self, request):
        payload = payload_for(request)
        properties = payload.get("response_schema", {}).get("properties", {})
        if "instruction_guidance" in properties:
            experiment = fixture_experiment(payload)
            experiment["change_locations"] = ["skills/arithmetic/SKILL.md"]
            answer = {"rationale": "Reusable arithmetic verification", "skills": ["arithmetic"],
                "skill_definitions": {"arithmetic": "---\nname: arithmetic\ndescription: Verify arithmetic\n---\nCheck calculations before answering."},
                "experiment": experiment}
        elif not properties and "arithmetic" in str(request.messages):
            if not any(m.role == "tool" and m.tool_call_id == "load-arithmetic" for m in request.messages):
                yield ModelStreamEvent(kind=ModelEventKind.COMPLETED, response=ModelResponse(response_id="load", finish_reason="tool_calls",
                    tool_calls=(ModelToolCall(tool_call_id="load-arithmetic", name="load_skill", arguments={"skill_name": "arithmetic"}),)))
                return
            self.loaded = str(request.messages)
            answer = "verified 42" if "Check calculations before answering." in self.loaded else "42"
        else:
            async for event in super()._stream(request):
                yield event
            return
        self.requests.append(request)
        yield ModelStreamEvent(kind=ModelEventKind.COMPLETED, response=ModelResponse(response_id="skill-fixture",
            text=json.dumps(answer) if isinstance(answer, dict) else answer, finish_reason="stop"))


def setup(client):
    headers = {"Authorization": f"Bearer {register_and_login(client)}"}
    response = client.post("/api/agents", headers=headers,
        json={"name": "Calculator", "instructions": "Calculate accurately.", "tools": [],
              "tool_approval": {"default": "ask", "tools": {"load_skill": "auto_approve"}}})
    assert response.status_code == 200, response.text
    return headers, response.json()["data"]["id"]


def body(**changes):
    return {"request_id": "request-1", "goal": "Improve arithmetic", "rounds": 1,
        "initial_training_case_count": 1, "training_cases_per_round": 0, "max_concurrency": 1,
        "suite": {"cases": [{"id": "train", "input": "6 * 7?", "rubric": "42", "split": "training"},
                            {"id": "dev", "input": "40 + 2?", "rubric": "42", "split": "validation"}]},
        **changes}


def settled(client, headers, path):
    async def wait():
        for _ in range(1000):
            value = await client.app.state.service.rsi.get(headers["user"], headers["agent"], path.rsplit("/", 1)[-1])
            if value["status"] in {"completed", "failed", "interrupted"}:
                return value
            await asyncio.sleep(0.01)
        raise AssertionError("RSI did not finish")
    return client.portal.call(wait)


def wait_run(client, headers, agent, run):
    user = client.portal.call(client.app.state.service.identity.from_token, headers["Authorization"].removeprefix("Bearer ")).user_id
    return settled(client, {"user": user, "agent": agent}, run)


def test_real_engine_result_and_manual_apply(client, service):
    model = ImprovingModel()
    service.execution.fallback_model = model
    headers, agent = setup(client)
    before = client.get(f"/api/agents/{agent}", headers=headers).json()["data"]["package_ref"]
    prefix = f"/api/agents/{agent}/rsi/runs"
    response = client.post(prefix, headers=headers, json=body())
    assert response.status_code == 200, response.text
    run = response.json()["data"]["id"]
    state = wait_run(client, headers, agent, run)
    assert state["status"] == "completed", state
    assert state["improved"], state
    assert client.get(f"/api/agents/{agent}", headers=headers).json()["data"]["package_ref"] == before
    selected = next(v for v in state["versions"] if v["package_ref"] == state["candidate_ref"])
    applied = client.post(f"{prefix}/{run}/versions/{selected['version_id']}/apply", headers=headers,
                          json={"expected_package_ref": before})
    assert applied.status_code == 200, applied.text
    after = client.get(f"/api/agents/{agent}", headers=headers).json()["data"]
    assert after["instructions"] == "Verify calculations before answering."
    assert after["package_ref"] == state["candidate_ref"]
    stale = client.post(f"{prefix}/{run}/versions/{selected['version_id']}/apply", headers=headers,
                        json={"expected_package_ref": before})
    assert stale.status_code == 409, stale.text
    assert client.post(prefix, headers=headers, json=body()).json()["data"]["id"] == run
    assert client.post(prefix, headers=headers, json=body(goal="changed")).status_code == 409
    assert "lease_token" not in client.get(f"{prefix}/{run}", headers=headers).text


def test_rsi_auth_scope_and_input_contract(client, service):
    service.execution.fallback_model = ImprovingModel()
    headers, agent = setup(client)
    prefix = f"/api/agents/{agent}/rsi/runs"
    client.cookies.clear()
    assert client.post(prefix, json=body()).status_code == 401
    assert client.post(prefix, headers=headers, json=body(optimization_scope=["tools"])).status_code == 422
    run = client.post(prefix, headers=headers, json=body()).json()["data"]["id"]
    other = {"Authorization": f"Bearer {register_and_login(client, 'bob')}"}
    assert client.get(f"{prefix}/{run}", headers=other).status_code in {403, 404}
    assert client.post(f"{prefix}/{run}/cancel", headers=other).status_code in {403, 404}


@pytest.mark.parametrize("existing", [False, True])
def test_skill_candidate_is_loaded_after_apply_without_global_publish(client, service, existing):
    from tests.app.v2.server.conftest import CompletingJudgeModel
    from tests.app.v2.server.test_agui_chat import _run_input

    model = SkillModel()
    service.execution.fallback_model = model
    headers, agent = setup(client)
    if existing:
        created = client.post("/api/skills", headers=headers, json={"name": "arithmetic",
            "content": "---\nname: arithmetic\ndescription: Original arithmetic\n---\nAdd numbers."})
        assert created.status_code == 200, created.text
        bound = client.put(f"/api/agents/{agent}/skills", headers=headers, json={"names": ["arithmetic"]})
        assert bound.status_code == 200, bound.text
    prefix = f"/api/agents/{agent}/rsi/runs"
    response = client.post(prefix, headers=headers, json=body(optimization_scope=["skills"]))
    assert response.status_code == 200, response.text
    run = response.json()["data"]["id"]
    state = wait_run(client, headers, agent, run)
    assert state["status"] == "completed" and state["improved"], state
    assert "Check calculations before answering." in model.loaded
    selected = next(v for v in state["versions"] if v["package_ref"] == state["candidate_ref"])
    applied = client.post(f"{prefix}/{run}/versions/{selected['version_id']}/apply", headers=headers,
        json={"expected_package_ref": state["base_package_ref"]})
    assert applied.status_code == 200, applied.text
    assert client.get(f"/api/agents/{agent}", headers=headers).json()["data"]["skills"] == ["arithmetic"]
    model.loaded = ""
    service.execution.fallback_model = CompletingJudgeModel(model)
    message = _run_input("after-rsi", "after-rsi")
    message["forwardedProps"] = {"agentId": agent}
    chat = client.post("/api/agent", headers=headers, json=message)
    assert chat.status_code == 200, chat.text
    assert "Check calculations before answering." in model.loaded, chat.text
    assert "verified 42" in chat.text
    global_skills = client.get("/api/skills", headers=headers).json()["data"]
    if existing:
        assert global_skills[0]["description"] == "Original arithmetic"
        assert global_skills[0]["version_id"] == created.json()["data"]["version_id"]
    else:
        assert global_skills == []


def test_server_can_generate_its_own_fixed_validation_suite(client, service):
    service.execution.fallback_model = ImprovingModel()
    headers, agent = setup(client)
    request = body(suite=None, validation_case_count=1)
    response = client.post(f"/api/agents/{agent}/rsi/runs", headers=headers, json=request)
    assert response.status_code == 200, response.text
    state = wait_run(client, headers, agent, response.json()["data"]["id"])
    assert state["status"] == "completed", state
    assert {c["split"] for c in state["result"]["report"]["suite"]["cases"]} == {"training", "validation"}


@pytest.mark.asyncio
async def test_stop_resume_keeps_identity_and_checks_binding(tmp_path):
    from tests.app.v2.server.conftest import make_test_service
    from app.v2.server.optimization.contracts import RsiStart

    entered, release = asyncio.Event(), asyncio.Event()
    model = RsiModel(entered=entered, release=release)
    host = make_test_service(tmp_path, model_provider=model, stub_judge=False)
    await host.start()
    user = await host.users.admin()
    agent = (await host.catalog.get(user.user_id)).agents[0]
    await host.catalog.update_agent(user.user_id, agent.id, {"name": agent.name, "tools": []})
    try:
        started = await host.rsi.start(user.user_id, agent.id, RsiStart.model_validate(body()))
        await asyncio.wait_for(entered.wait(), 5)
        stopped = await host.rsi.cancel(user.user_id, agent.id, started["id"])
        assert stopped["status"] == "interrupted"
        from app.v2.server.catalog.packages import package_owner
        frozen = await host.rsi.store.get(package_owner(user.user_id), agent.id, started["id"])
        await host.rsi.store.update(package_owner(user.user_id), agent.id, started["id"], frozen["lease_token"], {"engine_id": "changed"})
        with pytest.raises(ValueError, match="binding conflict"):
            await host.rsi.resume(user.user_id, agent.id, started["id"])
        await host.rsi.store.update(package_owner(user.user_id), agent.id, started["id"], frozen["lease_token"], {"engine_id": frozen["engine_id"]})
        host.execution.fallback_model = ImprovingModel()
        resumed = await host.rsi.resume(user.user_id, agent.id, started["id"])
        assert resumed["id"] == started["id"]
        await host.rsi.tasks[started["id"]]
        final = await host.rsi.get(user.user_id, agent.id, started["id"])
        assert final["status"] == "completed", final
        with pytest.raises(ValueError, match="conflict"):
            await host.rsi.resume(user.user_id, agent.id, started["id"])
    finally:
        await host.close()


@pytest.mark.asyncio
async def test_database_restart_preserves_completed_target_checkpoint(tmp_path):
    from app.v2.server.database import Database, DatabaseSettings
    from app.v2.server.optimization.contracts import RsiStart
    from tests.app.v2.server.conftest import FixtureServerHost, make_settings

    entered = asyncio.Event()

    class PauseEvaluator(ImprovingModel):
        async def _stream(self, request):
            raw = "".join(getattr(b, "text", "") for m in request.messages if m.role == "user" for b in m.content)
            if '"score"' in raw and '"response_schema"' in raw:
                entered.set()
                await asyncio.Event().wait()
            async for event in super()._stream(request):
                yield event

    def host(model):
        return FixtureServerHost(make_settings(tmp_path, log_level="warning"), model_provider=model,
            database=Database(DatabaseSettings(url=f"sqlite+aiosqlite:///{tmp_path}/host.db")))

    first_model = PauseEvaluator()
    first = host(first_model)
    await first.start()
    user = await first.users.admin()
    agent = (await first.catalog.get(user.user_id)).agents[0]
    await first.catalog.update_agent(user.user_id, agent.id, {"name": agent.name, "instructions": "Calculate.", "tools": []})
    started = await first.rsi.start(user.user_id, agent.id, RsiStart.model_validate(body()))
    await asyncio.wait_for(entered.wait(), 5)
    await first.close()
    second_model = ImprovingModel()
    second = host(second_model)
    await second.start()
    try:
        old = await second.rsi.get(user.user_id, agent.id, started["id"])
        assert old["status"] == "interrupted"
        await second.rsi.resume(user.user_id, agent.id, started["id"])
        await second.rsi.tasks[started["id"]]
        state = await second.rsi.get(user.user_id, agent.id, started["id"])
        assert state["status"] == "completed" and state["improved"], state
        # One baseline target had already finished. Its execution is reused;
        # only its unfinished evaluator and the other cases execute on resume.
        def targets(model):
            return [r for r in model.requests if not any('"response_schema"' in getattr(b, "text", "")
                for m in r.messages if m.role == "user" for b in m.content)]
        assert len(targets(first_model)) + len(targets(second_model)) == 4
        selected = next(v for v in state["versions"] if v["package_ref"] == state["candidate_ref"])
        await second.rsi.apply(user.user_id, agent.id, started["id"], selected["version_id"], state["base_package_ref"])
        assert (await second.catalog_store.get_agent(user.user_id, agent.id)).instructions == "Verify calculations before answering."
    finally:
        await second.close()

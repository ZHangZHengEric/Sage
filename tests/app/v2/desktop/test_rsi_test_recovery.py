import asyncio
import json

import httpx
import pytest
from app.v2.desktop.backend import rsi as original_rsi
from app.v2.desktop.backend import app as original_app
from sagents.v2.optimization.contracts import OptimizationCase, OptimizationTestSuite
from tests.app.v2.desktop.test_rsi import setup_service, start_request, RsiModel


@pytest.fixture
def integrated(monkeypatch):
    from app.v2.desktop.backend import rsi_test_recovery

    monkeypatch.setattr(original_app, "get_desktop_user_id", lambda request: "alice")
    return original_rsi, original_app, rsi_test_recovery


def hidden_suite():
    return OptimizationTestSuite(
        cases=tuple(
            OptimizationCase(
                id=id,
                input="PRIVATE QUESTION " + id,
                rubric="PRIVATE RUBRIC",
                split="test",
            )
            for id in ("sealed-a", "sealed-b")
        )
    )


async def completed_legacy(
    service, agent, model, candidate, monkeypatch, override=None
):
    def old_rejection(**kwargs):
        raise ValueError("only terminal human checkpoints can be restored")

    monkeypatch.setattr(candidate, "resumable_human_test_observer", old_rejection)
    request = start_request().model_copy(
        update={
            "rounds": 1,
            "human_test_suite": hidden_suite(),
            "human_test_count": 2,
            **(override or {}),
        }
    )
    run = await service.start_rsi(agent, request, "alice")
    await service._rsi_tasks[run["id"]]
    await asyncio.sleep(0)
    value = service.rsi_store.get(run["id"], "alice", agent, "run")
    assert value["status"] == "completed" and value["human_test_error"] == "ValueError"
    root = service.runtime_root / "rsi" / run["id"]
    result = json.loads((root / "result.json").read_text())
    record = {
        "round": 0,
        "package_hash": result["report"]["baseline"]["package_hash"],
        "status": "cancelled",
        "valid": True,
        "repeats": 1,
        "scores": {"test": None},
        "cases": [
            {
                "id": "sealed-a",
                "status": "completed",
                "score": 0,
                "trials": [
                    {
                        "trial": 1,
                        "status": "completed",
                        "score": 0,
                        "passed": False,
                        "grade": {
                            "score": 0,
                            "passed": False,
                            "rationale": "PRIVATE FIXED FAILURE",
                        },
                        "conversation": [],
                    }
                ],
            },
            {
                "id": "sealed-b",
                "status": "cancelled",
                "score": None,
                "trials": [{"trial": 1, "status": "cancelled", "score": None}],
            },
        ],
    }
    value["test_observations"] = [record]
    service.rsi_store.put(value, "alice", agent, "run")
    return value, root


@pytest.mark.asyncio
async def test_authenticated_postrun_replay_preserves_report_and_never_optimizes(
    tmp_path, monkeypatch, integrated
):
    candidate, app, helper = integrated
    model = RsiModel()
    service, agent = await setup_service(tmp_path, monkeypatch, model)
    try:
        before, root = await completed_legacy(
            service, agent, model, candidate, monkeypatch
        )
        report = (root / "result.json").read_bytes()
        audit = (root / "audit.jsonl").read_bytes()
        requests = len(model.requests)
        monkeypatch.setattr(
            candidate,
            "resumable_human_test_observer",
            helper.resumable_human_test_observer,
        )
        called = []

        def evaluator(**kwargs):
            async def evaluate(package, case):
                called.append((package.content_hash, case.id))
                return {
                    "grade": {
                        "score": 1,
                        "passed": True,
                        "rationale": "PRIVATE NEW FEEDBACK",
                    },
                    "conversation": [],
                }

            return evaluate

        monkeypatch.setattr(candidate, "IsolatedTestEvaluator", evaluator)

        async def forbidden(*args, **kwargs):
            pytest.fail("postrun replay must never invoke optimizer")

        monkeypatch.setattr(candidate.AgentPackageOptimizer, "optimize", forbidden)
        api = app.create_app(service=service, auth_token="private-auth-token")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api), base_url="http://desktop"
        ) as client:
            url = f"/api/v2/agents/{agent}/rsi/runs/{before['id']}/resume-tests"
            assert (await client.post(url)).status_code == 401
            response = await client.post(
                url, headers={"Authorization": "Bearer private-auth-token"}
            )
            assert response.status_code == 200, response.text
        await service._rsi_tasks[before["id"]]
        after = service.rsi_store.get(before["id"], "alice", agent, "run")
        assert (
            after["status"] == "completed"
            and after["human_test_recovery_status"] == "completed"
        )
        assert (
            after["human_test_recovery_count"] == 1 and "human_test_error" not in after
        )
        assert len(called) == 3
        assert [case for _, case in called].count("sealed-a") == 1
        assert [case for _, case in called].count("sealed-b") == 2
        assert (
            called[0][1] == "sealed-b"
        )  # Cached baseline a is not rerun; later round is fresh.
        assert [record["scores"]["test"] for record in after["test_observations"]] == [
            0.5,
            1,
        ]
        assert all(
            record["status"] == "completed" for record in after["test_observations"]
        )
        assert after["retained_hash"] == before["retained_hash"]
        assert after.get("recommended_hash") == before.get("recommended_hash")
        assert after["finished_at"] == before["finished_at"]
        assert (root / "result.json").read_bytes() == report
        assert (root / "audit.jsonl").read_bytes() == audit
        assert len(model.requests) == requests
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_postrun_wrong_saved_package_fails_before_job_or_model(
    tmp_path, monkeypatch, integrated
):
    candidate, app, helper = integrated
    model = RsiModel()
    service, agent = await setup_service(tmp_path, monkeypatch, model)
    try:
        before, root = await completed_legacy(
            service, agent, model, candidate, monkeypatch
        )
        before["test_observations"][0]["package_hash"] = "wrong"
        service.rsi_store.put(before, "alice", agent, "run")
        monkeypatch.setattr(
            candidate,
            "resumable_human_test_observer",
            helper.resumable_human_test_observer,
        )
        requests = len(model.requests)
        with pytest.raises(ValueError, match="saved human checkpoint differs"):
            await service.resume_rsi_tests(agent, before["id"], "alice")
        assert len(model.requests) == requests
        assert (
            service.rsi_store.get(before["id"], "alice", agent, "run")["status"]
            == "completed"
        )
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_postrun_no_predeclared_test_plan_cannot_be_added(
    tmp_path, monkeypatch, integrated
):
    candidate, app, helper = integrated
    model = RsiModel()
    service, agent = await setup_service(tmp_path, monkeypatch, model)
    try:
        run = await service.start_rsi(
            agent, start_request().model_copy(update={"rounds": 1}), "alice"
        )
        await service._rsi_tasks[run["id"]]
        await asyncio.sleep(0)
        with pytest.raises(ValueError, match="no predeclared human test suite"):
            await service.resume_rsi_tests(agent, run["id"], "alice")
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_cancelling_human_only_replay_keeps_completed_training_and_can_resume(
    tmp_path, monkeypatch, integrated
):
    candidate, app, helper = integrated
    model = RsiModel()
    service, agent = await setup_service(tmp_path, monkeypatch, model)
    try:
        before, root = await completed_legacy(
            service, agent, model, candidate, monkeypatch
        )
        report = (root / "result.json").read_bytes()
        requests = len(model.requests)
        monkeypatch.setattr(
            candidate,
            "resumable_human_test_observer",
            helper.resumable_human_test_observer,
        )
        entered = asyncio.Event()

        def blocked(**kwargs):
            async def evaluate(package, case):
                entered.set()
                await asyncio.Event().wait()

            return evaluate

        monkeypatch.setattr(candidate, "IsolatedTestEvaluator", blocked)

        async def forbidden(*args, **kwargs):
            pytest.fail("human-only replay cannot optimize")

        monkeypatch.setattr(candidate.AgentPackageOptimizer, "optimize", forbidden)
        await service.resume_rsi_tests(agent, before["id"], "alice")
        await asyncio.wait_for(entered.wait(), 10)
        cancelled = await service.cancel_rsi(agent, before["id"], "alice")
        assert cancelled["status"] == "completed"
        assert cancelled["human_test_recovery_status"] == "cancelled"
        assert cancelled["retained_hash"] == before["retained_hash"]
        assert (root / "result.json").read_bytes() == report
        assert len(model.requests) == requests

        def ready(**kwargs):
            async def evaluate(package, case):
                return {"grade": {"score": 1, "passed": True, "rationale": "private"}}

            return evaluate

        monkeypatch.setattr(candidate, "IsolatedTestEvaluator", ready)
        await service.resume_rsi_tests(agent, before["id"], "alice")
        await service._rsi_tasks[before["id"]]
        after = service.rsi_store.get(before["id"], "alice", agent, "run")
        assert (
            after["status"] == "completed" and after["human_test_recovery_count"] == 2
        )
        assert all(
            record["status"] == "completed" for record in after["test_observations"]
        )
        assert after["test_observations"][0]["cases"][0]["trials"][0]["score"] == 0
        assert (root / "result.json").read_bytes() == report
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_postrun_real_python_scorer_remains_authority_and_diagnoses_still_run(
    tmp_path, monkeypatch, integrated
):
    from app.v2.desktop.backend.rsi_evaluation import ScorerImport
    from sagents.v2.model.contracts import (
        ModelEventKind,
        ModelResponse,
        ModelStreamEvent,
    )
    from tests.sagents.v2.test_python_scorer import request as scoring_request
    from tests.sagents.v2.test_optimization_diagnostics import diagnosis
    from tests.app.v2.desktop.test_rsi import authored_evaluation_response

    class Model(RsiModel):
        async def _stream(self, request):
            raw = "".join(
                getattr(b, "text", "")
                for m in request.messages
                if m.role == "user"
                for b in m.content
            )
            if "<user_request>" in raw:
                raw = (
                    raw.rsplit("<user_request>", 1)[1]
                    .split("</user_request>", 1)[0]
                    .strip()
                )
            try:
                payload = json.loads(raw)
                title = payload.get("response_schema", {}).get("title")
            except ValueError:
                payload = {}
                title = None
            if title in {"OptimizationDiagnosis", "OptimizationDiagnosisSummary"}:
                value = (
                    diagnosis()
                    if title == "OptimizationDiagnosis"
                    else {"summary": "Analyzed fixed score", "priorities": []}
                )
                response = authored_evaluation_response(request, payload, value)
                yield ModelStreamEvent(
                    kind=ModelEventKind.COMPLETED,
                    response=response
                    or ModelResponse(
                        response_id="analysis",
                        text=json.dumps(value),
                        finish_reason="stop",
                    ),
                )
                return
            async for event in super()._stream(request):
                yield event

    candidate, app, helper = integrated
    model = Model()
    service, agent = await setup_service(tmp_path, monkeypatch, model)
    try:
        source = "SCORER_CONTRACT = 'Fixed numeric authority; diagnosis is separate.'\ndef score(request):\n s = 0.0 if request['case']['id'] == 'sealed-a' else .75\n return {'score': s, 'passed': s > 0, 'rationale': 'Custom Python authority'}\n"
        source += "SCORER_TEST_CASES = " + repr(
            [
                {
                    "request": scoring_request().model_dump(mode="json"),
                    "expected_score": 0.75,
                    "expected_passed": True,
                }
            ]
        )
        scorer = await service.import_rsi_scorer(
            agent, ScorerImport(name="replay-scorer.py", source=source), "alice"
        )
        before, root = await completed_legacy(
            service,
            agent,
            model,
            candidate,
            monkeypatch,
            override={"scorer_id": scorer["id"]},
        )
        report = (root / "result.json").read_bytes()
        monkeypatch.setattr(
            candidate,
            "resumable_human_test_observer",
            helper.resumable_human_test_observer,
        )

        async def forbidden(*args, **kwargs):
            pytest.fail("test recovery cannot run optimizer")

        monkeypatch.setattr(candidate.AgentPackageOptimizer, "optimize", forbidden)
        await service.resume_rsi_tests(agent, before["id"], "alice")
        await service._rsi_tasks[before["id"]]
        after = service.rsi_store.get(before["id"], "alice", agent, "run")
        assert after["human_test_recovery_status"] == "completed"
        assert all(
            record["status"] == "completed" for record in after["test_observations"]
        )
        assert [record["scores"]["test"] for record in after["test_observations"]] == [
            0.375,
            0.375,
        ]
        for record in after["test_observations"]:
            for case in record["cases"]:
                trial = case["trials"][0]
                assert trial["grade"]["score"] == (
                    0 if case["id"] == "sealed-a" else 0.75
                )
                if record["round"] != 0 or case["id"] != "sealed-a":
                    assert trial["grade"]["diagnosis"]
        assert (root / "result.json").read_bytes() == report
        assert "PRIVATE QUESTION" not in report.decode()
    finally:
        await service.close()

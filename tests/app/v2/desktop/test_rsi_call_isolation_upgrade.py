import collections
import json

import httpx
import pytest

from sagents.v2 import AgentPackageOptimizer, IsolatedOptimizationRunner
from tests.app.v2.desktop.test_rsi import setup_service, start_request, RsiModel


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", ["none", "goal", "test", "assets"])
async def test_owner_opt_in_upgrade_is_verified_before_engine_change_and_preserves_baseline(
    tmp_path, monkeypatch, tamper
):
    import sagents.v2.optimization.optimizer as sdk
    from app.v2.desktop.backend import rsi, app

    engine = ["a" * 64]
    legacy = [True]
    broken = [True]
    monkeypatch.setattr(sdk, "engine_fingerprint", lambda: engine[0])
    monkeypatch.setattr(rsi, "engine_fingerprint", lambda: engine[0])
    original_optimize = AgentPackageOptimizer.optimize

    async def legacy_policy(self, *args, **kwargs):
        if legacy[0]:
            kwargs.update(call_retries=0, allow_call_isolation_upgrade=False)
        return await original_optimize(self, *args, **kwargs)

    monkeypatch.setattr(AgentPackageOptimizer, "optimize", legacy_policy)
    original_run = IsolatedOptimizationRunner.run
    counts = collections.Counter()
    request = start_request().model_copy(
        update={"rounds": 1, "grow_training": False, "max_concurrency": 1}
    )
    from sagents.v2.optimization.contracts import OptimizationTestSuite

    hidden = request.suite.cases[0].model_copy(
        update={"id": "private-test", "input": "Human-only original", "split": "test"}
    )
    request = request.model_copy(
        update={
            "human_test_suite": OptimizationTestSuite(cases=(hidden,)),
            "human_test_count": 1,
        }
    )
    bad = request.suite.cases[1].input

    async def run(runner, package, key, content, context):
        if not package.manifest.metadata.id.startswith("desktop.rsi."):
            counts[(package.content_hash, content)] += 1
            if content == bad and broken[0]:
                raise TimeoutError()
        return await original_run(runner, package, key, content, context)

    monkeypatch.setattr(IsolatedOptimizationRunner, "run", run)

    async def no_delay(seconds):
        pass

    monkeypatch.setattr("sagents.v2.optimization.call_isolation.retry_delay", no_delay)
    service, agent = await setup_service(tmp_path, monkeypatch, RsiModel())
    monkeypatch.setattr(service, "_rsi_retry_wait", no_delay)
    try:
        started = await service.start_rsi(agent, request, "alice")
        await service._rsi_tasks[started["id"]]
        old = await service.rsi_run(agent, started["id"], "alice")
        assert old["status"] == "failed" and old["recovery_engine_id"] == "a" * 64
        saved = next(e["data"] for e in old["events"] if e["event"] == "case_completed")
        base_hash = saved["package_hash"]
        train = saved["result"]["case"]["input"]
        grade = saved["result"]["grade"]
        assert counts[(base_hash, train)] == 1
        before = dict(counts)
        engine[0] = "b" * 64
        legacy[0] = False
        broken[0] = False
        monkeypatch.setattr(app, "get_desktop_user_id", lambda request: "alice")
        web = app.create_app(service=service, auth_token="test-owner")
        path = f"/api/v2/agents/{agent}/rsi/runs/{started['id']}/resume"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=web), base_url="http://test"
        ) as client:
            assert (
                await client.post(path, json={"upgrade_call_isolation": True})
            ).status_code == 401
            no_flag = await client.post(
                path, headers={"Authorization": "Bearer test-owner"}
            )
            assert no_flag.status_code == 400 and dict(counts) == before
            assert (
                service.rsi_store.get(started["id"], "alice", agent, "run")[
                    "recovery_engine_id"
                ]
                == "a" * 64
            )
            if tamper != "none":
                frozen = (
                    service.runtime_root / "rsi" / started["id"] / "resume-context.json"
                )
                data = json.loads(frozen.read_text())
                if tamper == "goal":
                    data["request"]["goal"] = "Different optimization goal"
                if tamper == "test":
                    data["request"]["human_test_suite"]["cases"][0]["input"] = (
                        "Changed private test question"
                    )
                if tamper == "assets":
                    data["assets"]["forged.txt"] = "Y2hhbmdlZA=="
                frozen.write_text(json.dumps(data))
            resumed = await client.post(
                path,
                json={"upgrade_call_isolation": True},
                headers={"Authorization": "Bearer test-owner"},
            )
            if tamper != "none":
                assert resumed.status_code == 400
                current = service.rsi_store.get(started["id"], "alice", agent, "run")
                assert (
                    current["recovery_engine_id"] == "a" * 64 and dict(counts) == before
                )
                return
            assert resumed.status_code == 200
        await service._rsi_tasks[started["id"]]
        final = await service.rsi_run(agent, started["id"], "alice")
        assert final["status"] == "completed", final.get("error_type")
        assert (
            final["recovery_engine_id"] == "b" * 64
            and final["call_isolation_upgrade"]["state"] == "verified"
        )
        assert final["call_isolation_upgrade"]["from_engine"] == "a" * 64
        assert counts[(base_hash, train)] == 1
        assert final["result"]["report"]["baseline"]["cases"][0]["grade"] == grade
        assert (
            len(
                [
                    e
                    for e in final["events"]
                    if e["event"] == "execution_policy_upgraded"
                ]
            )
            == 1
        )
    finally:
        await service.close()

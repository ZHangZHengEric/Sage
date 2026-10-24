import json
import pytest
from sagents.v2 import IsolatedOptimizationRunner
from tests.app.v2.desktop.test_rsi import setup_service, start_request, RsiModel


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    async def wait(attempt):
        pass

    monkeypatch.setattr("sagents.v2.optimization.call_isolation.retry_delay", wait)


@pytest.mark.asyncio
# Default Desktop uses deterministic candidate checks; no reviewer model is invoked.
@pytest.mark.parametrize("role", ["target", "evaluator", "tuner"])
async def test_native_desktop_single_failure_never_restarts_optimizer_or_other_targets(
    tmp_path, monkeypatch, role
):
    service, agent = await setup_service(tmp_path, monkeypatch, RsiModel())
    original = IsolatedOptimizationRunner.run
    failures = []
    targets = []
    snapshot = {}
    verified_reset = []

    async def run(runner, package, key, content, context):
        identity = package.manifest.metadata.id
        match = (
            not identity.startswith("desktop.rsi.")
            if role == "target"
            else identity == "desktop.rsi." + role
        )
        if match and not failures:
            failures.append(True)
            if role == "tuner":
                from sagents.v2.optimization.package_workspace import editor_binding

                editor = editor_binding(package, runner.root / "workspace") / "package"
                snapshot.update(
                    {p: p.read_bytes() for p in editor.rglob("*") if p.is_file()}
                )
                prompt = next(p for p in snapshot if p.suffix == ".md")
                prompt.write_text("BROKEN HALF EDIT")
                (editor / "files" / "orphan.txt").write_text(
                    "partial abandoned resource"
                )
            raise TimeoutError("one call failed")
        if match and role == "tuner" and snapshot:
            assert all(p.read_bytes() == before for p, before in snapshot.items()), [
                (
                    p.name,
                    p.read_bytes() == before,
                    json.loads(p.read_text()) == json.loads(before)
                    if p.suffix == ".json"
                    else None,
                )
                for p, before in snapshot.items()
            ]
            assert set(next(iter(snapshot)).parent.parent.rglob("orphan.txt")) == set()
            verified_reset.append(True)
        result = await original(runner, package, key, content, context)
        if not identity.startswith("desktop.rsi."):
            targets.append(content)
        return result

    monkeypatch.setattr(IsolatedOptimizationRunner, "run", run)
    try:
        request = start_request().model_copy(
            update={"rounds": 1, "grow_training": False}
        )
        start = await service.start_rsi(agent, request, "alice")
        await service._rsi_tasks[start["id"]]
        final = await service.rsi_run(agent, start["id"], "alice")
        assert final["status"] == "completed", final.get("error_type")
        assert final.get("automatic_recoveries", 0) == 0
        assert len(targets) == 4
        assert any(e["event"] == "call_retry_scheduled" for e in final["events"])
        assert not list(
            (service.runtime_root / "rsi" / start["id"]).glob("audit-retry*")
        )
        if role == "tuner":
            assert verified_reset
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_native_exhausted_target_keeps_other_case_and_does_not_restart_whole_job(
    tmp_path, monkeypatch
):
    service, agent = await setup_service(tmp_path, monkeypatch, RsiModel())
    original = IsolatedOptimizationRunner.run
    request = start_request().model_copy(update={"rounds": 1, "grow_training": False})
    bad = request.suite.cases[0].input
    counts = {}

    async def run(runner, package, key, content, context):
        if not package.manifest.metadata.id.startswith("desktop.rsi."):
            counts[content] = counts.get(content, 0) + 1
            if content == bad:
                raise TimeoutError("persistent failure")
        return await original(runner, package, key, content, context)

    monkeypatch.setattr(IsolatedOptimizationRunner, "run", run)
    try:
        started = await service.start_rsi(agent, request, "alice")
        await service._rsi_tasks[started["id"]]
        final = await service.rsi_run(agent, started["id"], "alice")
        assert final["status"] == "failed" and final["error_type"] == "TimeoutError"
        assert final.get("automatic_recoveries", 0) == 0
        assert counts[bad] == 4 and sum(counts.values()) == 5
        events = final["events"]
        completed = [e for e in events if e["event"] == "case_completed"]
        assert (
            len(completed) == 1
            and completed[0]["data"]["result"]["case"]["input"] != bad
        )
        assert len([e for e in events if e["event"] == "case_call_failed"]) == 1
    finally:
        await service.close()

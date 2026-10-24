"""Actual checkpoint replay after isolated target and internal-role failures."""

import json

import pytest

from app.v2.desktop.backend.rsi_call_recovery import failed_call
from sagents.v2 import IsolatedOptimizationRunner
from sagents.v2.optimization.python_scorer import ScorerExecutionError
from tests.app.v2.desktop.test_rsi import RsiModel, setup_service, start_request


def test_retry_metadata_has_no_requests_or_exception_messages(tmp_path):
    journal = tmp_path / "audit.jsonl"
    journal.write_text(json.dumps({"event": "agent_call_started", "data": {
        "call_id": "a", "role": "evaluation", "round": 1,
        "request": "PRIVATE QUESTION", "case_id": "train-1"}}) + "\n")
    result = failed_call(TimeoutError("SECRET PROVIDER MESSAGE"), journal)
    assert result["role"] == "evaluation" and result["retry_limit"] == 3
    assert "PRIVATE" not in json.dumps(result) and "SECRET" not in json.dumps(result)
    assert failed_call(PermissionError("denied"), journal) is None
    assert failed_call(ScorerExecutionError("frozen scorer source changed"), journal) is None
    assert failed_call(TimeoutError(), tmp_path / "missing") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("role,error_type", [
    ("target", TimeoutError), ("evaluator", TimeoutError),
    ("evaluator", RuntimeError), ("tuner", TimeoutError),
])
async def test_single_call_failure_recovers_without_reexecuting_completed_targets(
    tmp_path, monkeypatch, role, error_type,
):
    service, agent = await setup_service(tmp_path, monkeypatch, RsiModel())
    original = IsolatedOptimizationRunner.run
    failures, targets, delays = [], [], []

    async def run(runner, package, selected, content, context):
        current = package.manifest.metadata.id
        match = (not current.startswith("desktop.rsi.")) if role == "target" else current == "desktop.rsi." + role
        if match and not failures:
            failures.append(True)
            raise error_type("isolated invocation failed")
        result = await original(runner, package, selected, content, context)
        if not current.startswith("desktop.rsi."):
            targets.append(content)
        return result

    async def wait(seconds):
        delays.append(seconds)

    monkeypatch.setattr(IsolatedOptimizationRunner, "run", run)
    monkeypatch.setattr(service, "_rsi_retry_wait", wait)
    try:
        request = start_request().model_copy(update={"rounds": 1, "grow_training": False})
        started = await service.start_rsi(agent, request, "alice")
        await service._rsi_tasks[started["id"]]
        final = await service.rsi_run(agent, started["id"], "alice")
        assert failures and final["status"] == "completed", final.get("error_type")
        assert final["automatic_recoveries"] == 1 and delays == [2]
        assert len(targets) == 4  # original two cases and candidate two cases
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_repeated_call_failure_stops_at_bound_with_checkpoint(tmp_path, monkeypatch):
    service, agent = await setup_service(tmp_path, monkeypatch, RsiModel())
    original = IsolatedOptimizationRunner.run
    attempts, waits = [], []

    async def run(runner, package, selected, content, context):
        if not package.manifest.metadata.id.startswith("desktop.rsi."):
            attempts.append(True)
            raise TimeoutError()
        return await original(runner, package, selected, content, context)

    async def wait(seconds):
        waits.append(seconds)

    monkeypatch.setattr(IsolatedOptimizationRunner, "run", run)
    monkeypatch.setattr(service, "_rsi_retry_wait", wait)
    try:
        request = start_request().model_copy(update={"rounds": 1, "grow_training": False, "max_concurrency": 1})
        started = await service.start_rsi(agent, request, "alice")
        await service._rsi_tasks[started["id"]]
        final = await service.rsi_run(agent, started["id"], "alice")
        assert final["status"] == "failed" and final["error_type"] == "TimeoutError"
        assert len(attempts) == 4 and waits == [2, 4, 8]
        assert final["exhausted_call_recovery"]["retry_limit"] == 3
        assert final["resumable"] is True
    finally:
        await service.close()


def test_generation_failure_has_a_recovery_slot_before_first_completed_call(tmp_path):
    journal = tmp_path / "audit.jsonl"
    journal.write_text(json.dumps({"event": "test_generation_started", "data": {"split": "validation"}}) + "\n")
    assert failed_call(TimeoutError(), journal)["role"] == "test_design"


@pytest.mark.asyncio
async def test_distinct_failed_calls_have_independent_retry_budgets(tmp_path, monkeypatch):
    service, agent = await setup_service(tmp_path, monkeypatch, RsiModel())
    original = IsolatedOptimizationRunner.run
    counts = {}

    async def run(runner, package, selected, content, context):
        role = package.manifest.metadata.id
        # Each target input fails three times before succeeding. Recovery of a
        # different target must not inherit the previous target's used budget.
        if not role.startswith("desktop.rsi."):
            counts[content] = counts.get(content, 0) + 1
            if counts[content] <= 3:
                raise TimeoutError()
        return await original(runner, package, selected, content, context)

    async def wait(seconds):
        pass

    monkeypatch.setattr(IsolatedOptimizationRunner, "run", run)
    monkeypatch.setattr(service, "_rsi_retry_wait", wait)
    try:
        request = start_request().model_copy(update={"rounds": 1, "grow_training": False, "max_concurrency": 1})
        started = await service.start_rsi(agent, request, "alice")
        await service._rsi_tasks[started["id"]]
        final = await service.rsi_run(agent, started["id"], "alice")
        assert final["status"] == "completed", final.get("error_type")
        assert final["automatic_recoveries"] == 6
        assert set(counts.values()) == {5}  # baseline four attempts + candidate one
    finally:
        await service.close()


@pytest.fixture(autouse=True)
def legacy_checkpoint_fallback(monkeypatch):
    """Retain coverage of fallback for engines without local retry boundaries."""
    from sagents.v2 import AgentPackageOptimizer
    original = AgentPackageOptimizer.optimize
    async def optimize(self, *args, **kwargs):
        kwargs['call_retries'] = 0
        return await original(self, *args, **kwargs)
    monkeypatch.setattr(AgentPackageOptimizer, 'optimize', optimize)

import collections
import json

import pytest

from tests.sagents.v2.test_package_optimizer import Runner, bundle, context, suite
from tests.sagents.v2.test_call_isolation import isolated_optimizer


@pytest.fixture(autouse=True)
def instant(monkeypatch):
    async def wait(attempt):
        pass

    monkeypatch.setattr("sagents.v2.optimization.call_isolation.retry_delay", wait)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["none", "goal", "concurrency", "binding", "package"]
)
async def test_explicit_upgrade_preserves_completed_receipts_and_rejects_other_configuration_changes(
    tmp_path, monkeypatch, change
):
    import sagents.v2.optimization.optimizer as implementation

    engine = ["a" * 64]
    monkeypatch.setattr(implementation, "engine_fingerprint", lambda: engine[0])

    class Failing(Runner):
        def __init__(self):
            super().__init__(proposals=[{"rationale": "Keep correct behavior"}])
            self.fail = True
            self.counts = collections.Counter()

        async def run(self, p, key, content, ctx):
            if p.manifest.metadata.id == "test.target":
                self.counts[content] += 1
                if content == suite().cases[1].input and self.fail:
                    raise TimeoutError()
            return await super().run(p, key, content, ctx)

    runner = Failing()
    source = tmp_path / "old.jsonl"
    kwargs = dict(
        context=context(),
        goal="Conversions",
        suite=suite(),
        validation_case_count=None,
        rounds=1,
        final_max_cases=0,
        max_concurrency=1,
        journal_path=source,
        call_retries=0,
        restart_incomplete=True,
        recovery_binding_id="fixed-binding",
    )
    with pytest.raises(TimeoutError):
        await isolated_optimizer(runner).optimize(bundle(), **kwargs)
    events = [json.loads(line) for line in source.read_text().splitlines()]
    original = next(
        e["data"]["result"] for e in events if e["event"] == "case_completed"
    )
    before = dict(runner.counts)
    engine[0] = "b" * 64
    runner.fail = False
    kwargs.update(
        call_retries=3, resume_from=source, journal_path=tmp_path / "new.jsonl"
    )
    with pytest.raises(ValueError, match="configuration differs"):
        await isolated_optimizer(runner).optimize(bundle(), **kwargs)
    assert dict(runner.counts) == before
    kwargs["allow_call_isolation_upgrade"] = True
    target = bundle()
    if change == "goal":
        kwargs["goal"] = "Different goal"
    if change == "concurrency":
        kwargs["max_concurrency"] = 2
    if change == "binding":
        kwargs["recovery_binding_id"] = "different-model-binding"
    if change == "package":
        target.files["prompts/base.md"] = "Different target instructions"
    if change != "none":
        with pytest.raises(ValueError, match="frozen experiment configuration"):
            await isolated_optimizer(runner).optimize(target, **kwargs)
        assert dict(runner.counts) == before
        assert not kwargs["journal_path"].exists()
        return
    result = await isolated_optimizer(runner).optimize(target, **kwargs)
    assert (
        result.report.baseline.cases[0].grade.model_dump(mode="json")
        == original["grade"]
    )
    assert runner.counts[suite().cases[0].input] == 1
    new_events = [
        json.loads(line) for line in kwargs["journal_path"].read_text().splitlines()
    ]
    upgrades = [e for e in new_events if e["event"] == "execution_policy_upgraded"]
    assert (
        len(upgrades) == 1
        and upgrades[0]["data"]["from_engine"] == "a" * 64
        and upgrades[0]["data"]["to_engine"] == "b" * 64
    )
    old_count = dict(runner.counts)
    kwargs.update(
        allow_call_isolation_upgrade=False,
        resume_from=kwargs["journal_path"],
        journal_path=tmp_path / "normal-resume.jsonl",
    )
    await isolated_optimizer(runner).optimize(target, **kwargs)
    assert dict(runner.counts) == old_count

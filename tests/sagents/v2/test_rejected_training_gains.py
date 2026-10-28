import json
import pytest
from sagents.v2.optimization.contracts import OptimizationEvaluation, OptimizationRound
from tests.sagents.v2.test_optimization_evidence import measured
from tests.sagents.v2.test_package_optimizer import (
    AdaptiveRunner,
    bundle,
    context,
    optimizer,
    suite,
)


@pytest.mark.parametrize("generator", [False, True])
def test_rejected_attempt_preserves_fixed_training_paths_but_not_unchanged_success_or_hidden_data(
    generator,
):
    from sagents.v2.optimization.evidence import training_evidence_files

    retained = [measured("repaired", [0, 0]), measured("unchanged", [1, 1])]
    repaired = measured("repaired", [1, 1])
    repaired = repaired.model_copy(
        update={
            "trials": tuple(
                t.model_copy(
                    update={
                        "observation": t.observation.model_copy(
                            update={"output": "REJECTED BUT REPAIRED SUCCESS PATH"}
                        )
                    }
                )
                for t in repaired.trials
            )
        }
    )
    evaluation = OptimizationEvaluation(
        package_hash="attempt",
        cases=(
            repaired,
            measured("unchanged", [1, 1]),
            measured("PRIVATE-DEV", [1, 1], "validation"),
            measured("PRIVATE-TEST", [1, 1], "test"),
        ),
    )
    attempt = OptimizationRound(
        round=1,
        parent_hash="parent",
        evaluation=evaluation,
        accepted=False,
        reason="PRIVATE DEV REASON",
    )
    files, index = training_evidence_files(
        iter(retained) if generator else retained, attempts=[attempt]
    )
    previous = index["rejected_attempts"][0]
    assert previous["training_improvements"] == [
        {"case_id": "repaired", "metric": "score", "retained": 0, "attempt": 1}
    ]
    assert [x["case_id"] for x in previous["comparisons"]] == ["repaired"]
    assert "REJECTED BUT REPAIRED SUCCESS PATH" in "\n".join(files.values())
    assert not any(
        token in "\n".join(files.values())
        for token in (
            "PRIVATE-DEV",
            "PRIVATE-TEST",
            "PRIVATE DEV REASON",
            "EVALUATOR-ONLY",
        )
    )
    attempt_index = json.loads(files[previous["index"]])
    assert attempt_index["groups"]["passed"]["count"] == 1


def test_rejected_objective_improvement_survives_with_same_quality_score():
    from sagents.v2.optimization.evidence import training_evidence_files

    parent = measured("efficient", [1, 1]).model_copy(update={"objective_score": 0.2})
    improved = measured("efficient", [1, 1]).model_copy(update={"objective_score": 0.8})
    attempt = OptimizationRound(
        round=1,
        parent_hash="parent",
        evaluation=OptimizationEvaluation(package_hash="attempt", cases=(improved,)),
        accepted=False,
        reason="Worse overall",
    )
    files, index = training_evidence_files([parent], attempts=[attempt])
    assert index["rejected_attempts"][0]["training_improvements"] == [
        {
            "case_id": "efficient",
            "metric": "objective_score",
            "retained": 0.2,
            "attempt": 0.8,
        }
    ]
    assert (
        json.loads(files[index["rejected_attempts"][0]["index"]])["groups"]["passed"][
            "count"
        ]
        == 1
    )


@pytest.mark.asyncio
async def test_actual_next_tuning_call_can_read_successful_component_of_rejected_round():
    class Reader(AdaptiveRunner):
        seen = []

        async def run(self, package, agent_id, content, ctx):
            if package.manifest.metadata.id == "test.tuner":
                self.seen.append(dict(package.files))
            return await super().run(package, agent_id, content, ctx)

    runner = Reader(
        scores={
            "base": {"training": 0, "validation": .5},
            "guidance-1": {"training": 1, "validation": 0},
            "guidance-2": {"training": 1, "validation": 1},
        }
    )
    engine = optimizer(runner)
    data = engine.tuner.model_dump(mode="json")
    data["package"]["manifest"]["agents"][engine.tuner.agent_id]["tools"] = [
        "file_read"
    ]
    engine.tuner = type(engine.tuner).model_validate(data)
    result = await engine.optimize(
        bundle(),
        context=context(),
        goal="Accuracy",
        suite=suite(),
        validation_case_count=1,
        grow_training=False,
        rounds=2,
    )
    assert result.report.rounds[0].accepted is False
    assert result.report.rounds[1].accepted is True
    index = json.loads(runner.seen[1]["training-evidence/index.json"])
    attempt = index["rejected_attempts"][0]
    assert attempt["training_improvements"][0]["case_id"] == "train"
    link = attempt["comparisons"][0]["rejected_analysis"]
    entry = json.loads(runner.seen[1][link])
    assert json.loads(runner.seen[1][entry["trials"][0]["assessment"]])["score"] == 1
    assert "guidance-1" in runner.seen[1][entry["trials"][0]["execution"]]
    assert "holdout-secret" not in "\n".join(runner.seen[1].values())

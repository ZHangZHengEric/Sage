import json
import pytest
from sagents.v2.optimization.evidence import training_evidence_files
from tests.sagents.v2.test_optimization_evidence import measured
from tests.sagents.v2.test_package_optimizer import (
    AdaptiveRunner,
    bundle,
    context,
    optimizer,
    suite,
)


def test_training_question_is_separate_and_preserves_context_without_reference_or_hidden_splits():
    result = measured("train", [0, 1])
    result = result.model_copy(
        update={
            "case": result.case.model_copy(
                update={
                    "input": "Hello.",
                    "user_context": "Ask about tracking, then independently request a return.",
                }
            )
        }
    )
    files, index = training_evidence_files(
        [
            result,
            measured("PRIVATE-DEV", [0], "validation"),
            measured("PRIVATE-TEST", [0], "test"),
        ]
    )
    item = json.loads(files["training-evidence/mixed/index.json"])[0]
    case_index = json.loads(files[item["analysis"]])
    question = json.loads(files[case_index["question"]])
    assert question == {
        "input": "Hello.",
        "rubric": "Complete",
        "mode": "single_turn",
        "user_context": "Ask about tracking, then independently request a return.",
    }
    assert case_index["question"] == item["question"]
    for t in case_index["trials"]:
        execution = json.loads(files[t["execution"]])
        assert isinstance(execution, list)
        assert question["user_context"] not in files[t["execution"]]
    assert not any(
        token in "\n".join(files.values())
        for token in (
            "EVALUATOR-ONLY",
            "PRIVATE-DEV",
            "PRIVATE-TEST",
            "reference_answer",
        )
    )
    assert "never proof of what" in index["instructions"]


@pytest.mark.asyncio
async def test_actual_file_tuner_can_read_previously_measured_training_scenario():
    class Read(AdaptiveRunner):
        seen = []

        async def run(self, package, agent_id, content, ctx):
            if package.manifest.metadata.id == "test.tuner":
                self.seen.append(dict(package.files))
            return await super().run(package, agent_id, content, ctx)

    runner = Read()
    engine = optimizer(runner)
    data = engine.tuner.model_dump(mode="json")
    data["package"]["manifest"]["agents"][engine.tuner.agent_id]["tools"] = [
        "file_read"
    ]
    engine.tuner = type(engine.tuner).model_validate(data)
    fixed = suite()
    fixed = fixed.model_copy(
        update={
            "cases": tuple(
                c.model_copy(
                    update={
                        "user_context": "PRIVATE DEV SCENARIO"
                        if c.split == "validation"
                        else "FULL ALREADY MEASURED TRAINING SCENARIO",
                        "reference_answer": "PRIVATE ANSWER",
                    }
                )
                for c in fixed.cases
            )
        }
    )
    result = await engine.optimize(
        bundle(),
        context=context(),
        goal="Conversions",
        suite=fixed,
        validation_case_count=1,
        grow_training=False,
        rounds=1,
    )
    assert result.report.baseline.cases
    files = runner.seen[0]
    idx = json.loads(files["training-evidence/failed/index.json"])[0]
    question = json.loads(files[idx["question"]])
    assert question["user_context"] == "FULL ALREADY MEASURED TRAINING SCENARIO"
    assert "PRIVATE DEV SCENARIO" not in "\n".join(files.values())
    assert "PRIVATE ANSWER" not in "\n".join(files.values())

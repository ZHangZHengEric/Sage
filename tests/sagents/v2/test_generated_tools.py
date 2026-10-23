import json

import pytest
from pydantic import ValidationError

from sagents.v2.agent.management import AgentPackageBundle
from sagents.v2.optimization import OptimizationConstraints
from sagents.v2.optimization.contracts import OptimizationPatch
from sagents.v2.optimization.optimizer import AgentPackageOptimizer
from sagents.v2.tool.contracts import ToolCall
from sagents.v2.tool.generated import (
    GeneratedTool,
    evaluate,
    generated_tool_provider,
    generated_tools,
)
from tests.sagents.v2.test_package_optimizer import bundle, context


def spec(boundary=7):
    return GeneratedTool(
        description="Apply the return window without external effects",
        input_schema={
            "type": "object",
            "properties": {"days": {"type": "integer", "minimum": 0}},
            "required": ["days"],
            "additionalProperties": False,
        },
        expression={
            "op": "if",
            "args": [
                {"op": "lte", "args": [{"var": "days"}, boundary]},
                {"decision": "return", "action_executed": False},
                {"decision": "reject", "action_executed": False},
            ],
        },
    )


def test_collection_helpers_compute_from_supplied_data_and_are_bounded():
    expression = {"op": "sort", "args": [
        {"op": "filter", "args": [{"var": "items"}, {"var": "item.available"}]},
        {"var": "item.price"},
    ]}
    model = GeneratedTool(description="Rank eligible supplied options", input_schema={"type": "object"}, expression=expression)
    items = [{"available": True, "price": 7}, {"available": False, "price": 1}, {"available": True, "price": 3}]
    assert evaluate(model.expression, {"items": items}) == [items[2], items[0]]
    assert evaluate({"op": "sum", "args": [{"op": "map", "args": [{"var": "items"}, {"var": "item.price"}]}]}, {"items": items}) == 11
    with pytest.raises(ValueError, match="256"):
        evaluate(expression, {"items": items * 100})
    nested = {"op": "map", "args": [{"var": "items"}, {"op": "map", "args": [{"var": "items"}, {"var": "item"}]}]}
    with pytest.raises(ValueError, match="step bound"):
        evaluate(nested, {"items": list(range(256))})


def test_new_skills_are_versioned_and_scoped_without_predeclared_names(tmp_path):
    from sagents.v2.skill.plugins.filesystem import FilesystemSkillProvider
    original = bundle()
    patch = OptimizationPatch(rationale="Reusable workflow", skills=("workflow-check",),
        skill_definitions={"workflow-check": "---\nname: workflow-check\ndescription: Check complete inputs before action\n---\nReconcile every requested item before acting."})
    policy = OptimizationConstraints(allow_skill_changes=True, allow_skill_creation=True)
    candidate = AgentPackageOptimizer._apply(original, original, "assistant", patch, policy, "2")
    restored = AgentPackageBundle.model_validate_json(candidate.model_dump_json())
    for path, content in restored.files.items():
        destination = tmp_path / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content)
    assert "workflow-check" in FilesystemSkillProvider((tmp_path / "skills",)).descriptors()
    assert "skills/workflow-check/SKILL.md" not in original.files
    scoped = AgentPackageOptimizer._scope_constraints(original, policy, ("instructions",))
    with pytest.raises(ValueError, match="skill creation"):
        AgentPackageOptimizer._apply(original, original, "assistant", patch, scoped, "2")
    with pytest.raises((ValueError, ValidationError)):
        AgentPackageOptimizer._apply(original, original, "assistant",
            OptimizationPatch(rationale="invalid", skill_definitions={"../escape": "bad"}), policy, "2")


@pytest.mark.asyncio
async def test_create_revise_reload_and_execute_real_tool():
    original = bundle()
    policy = OptimizationConstraints(allow_tool_changes=True, allow_tool_creation=True)
    candidate = AgentPackageOptimizer._apply(
        original,
        original,
        "assistant",
        OptimizationPatch(
            rationale="Implement reusable window calculation",
            tools=("rsi_return_policy",),
            tool_definitions={"rsi_return_policy": spec()},
        ),
        policy,
        "2",
    )
    assert "rsi_return_policy" not in generated_tools(original.files)
    assert candidate.manifest.agents["assistant"].tools == ("rsi_return_policy",)
    # Package serialization retains executable implementation, with no process-local registry.
    restored = AgentPackageBundle.model_validate_json(candidate.model_dump_json())
    provider = generated_tool_provider(restored.files)
    call = ToolCall(
        tool_call_id="c",
        tool_name="rsi_return_policy",
        arguments={"days": 8},
        operation_id="o",
        idempotency_key="k",
        owner_run_id="r",
    )
    result = await provider.executor.execute(call, context())
    assert json.loads(result.content[0].text)["decision"] == "reject"
    revised = AgentPackageOptimizer._apply(
        original,
        candidate,
        "assistant",
        OptimizationPatch(
            rationale="Adjust policy implementation",
            tool_definitions={"rsi_return_policy": spec(30)},
        ),
        policy,
        "3",
    )
    result = await generated_tool_provider(revised.files).executor.execute(
        call, context()
    )
    assert json.loads(result.content[0].text)["decision"] == "return"
    # Restoring the previous version restores the old implementation.
    assert (
        evaluate(
            generated_tools(restored.files)["rsi_return_policy"].expression, {"days": 8}
        )["decision"]
        == "reject"
    )


def test_tool_generation_stays_inside_requested_scope_and_namespace():
    original = bundle()
    policy = OptimizationConstraints(allow_tool_changes=True, allow_tool_creation=True)
    scoped = AgentPackageOptimizer._scope_constraints(
        original, policy, ("instructions",)
    )
    patch = OptimizationPatch(
        rationale="new tool", tool_definitions={"rsi_return_policy": spec()}
    )
    with pytest.raises(ValueError, match="not enabled"):
        AgentPackageOptimizer._apply(
            original, original, "assistant", patch, scoped, "2"
        )
    with pytest.raises(ValueError, match="names must"):
        AgentPackageOptimizer._apply(
            original,
            original,
            "assistant",
            OptimizationPatch(
                rationale="override native",
                tool_definitions={"shell": spec()},
            ),
            policy,
            "2",
        )
    with pytest.raises(ValueError, match="tool_definitions"):
        AgentPackageOptimizer._apply(
            original,
            original,
            "assistant",
            OptimizationPatch(
                rationale="bypass",
                files={"tools/rsi/rsi_x.json": spec().model_dump_json()},
            ),
            policy.model_copy(update={"creatable_files": ("tools/rsi/rsi_x.json",)}),
            "2",
        )


@pytest.mark.parametrize(
    "expression",
    [
        {"op": "shell", "args": ["rm -rf /"]},
        {"op": "if", "args": [True]},
        {"var": "days", "extra": "hidden"},
        {"op": "add", "args": [1] * 40},
    ],
)
def test_generated_implementation_rejects_invalid_operations(expression):
    with pytest.raises(ValidationError):
        spec().model_copy(update={"expression": expression}).__class__.model_validate(
            {
                **spec().model_dump(),
                "expression": expression,
            }
        )


def test_lazy_branches_and_no_external_schema_resolution():
    assert (
        evaluate({"op": "if", "args": [True, 7, {"op": "div", "args": [1, 0]}]}, {})
        == 7
    )
    with pytest.raises(ValidationError, match="references"):
        GeneratedTool(
            description="bad schema",
            input_schema={
                "type": "object",
                "properties": {"x": {"$ref": "https://example.com/schema"}},
            },
            expression=1,
        )
    with pytest.raises(ValueError, match="bounded finite"):
        evaluate({"op": "mul", "args": [True, 4]}, {})


def test_generated_tool_honors_host_file_size_grant():
    original = bundle()
    with pytest.raises(ValueError, match="max_file_bytes"):
        AgentPackageOptimizer._apply(
            original,
            original,
            "assistant",
            OptimizationPatch(
                rationale="new tool",
                tool_definitions={"rsi_return_policy": spec()},
            ),
            OptimizationConstraints(
                allow_tool_changes=True, allow_tool_creation=True, max_file_bytes=10
            ),
            "2",
        )


def test_tool_failure_diagnostics_reach_tuner_even_after_large_receipts():
    from sagents.v2.optimization import (
        OptimizationCaseResult,
        OptimizationGrade,
        OptimizationObservation,
    )
    from sagents.v2.optimization.feedback import training_feedback
    from tests.sagents.v2.test_package_optimizer import suite

    result = OptimizationCaseResult(
        case=suite().cases[0],
        grade=OptimizationGrade(score=0, passed=False, rationale="Tool failed"),
        observation=OptimizationObservation(
            state="completed",
            output="Could not calculate",
            evidence={
                "runtime_events": [
                    {
                        "type": "tool.failed",
                        "data": {
                            "kind": "tool",
                            "tool_name": "rsi_policy",
                            "arguments": {"large": "x" * 5000},
                            "error": {
                                "code": "tool.provider_error",
                                "message": "Tool failed",
                                "metadata": {
                                    "diagnostic_message": "ValueError: concat requires strings"
                                },
                            },
                        },
                    }
                ],
            },
        ),
    )
    before = result.model_dump_json()
    feedback = training_feedback(result)
    assert feedback["observation"]["evidence"]["tool_errors"] == [
        {
            "tool_name": "rsi_policy",
            "code": "tool.provider_error",
            "diagnostic": "ValueError: concat requires strings",
        }
    ]
    assert len(json.dumps(feedback)) < 8000
    assert result.model_dump_json() == before

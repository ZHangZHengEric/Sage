"""Offline multi-round optimization demo using the real v2 runtime (Python 3.12+).

Run: .venv/bin/python -m examples.sagents_v2_package_optimizer
Scripted responses demonstrate orchestration, not model intelligence. In a real
host, configure evaluator/tuner ModelRoutes and supply sandboxed tool/Skill ports.
"""

from __future__ import annotations
from sagents.v2 import ApplicationConfiguration
from examples.sagents_v2_host.registrations import provided, runtime_for

import asyncio
import json
import tempfile
from pathlib import Path

from sagents.v2 import (
    AgentPackageBundle,
    AgentPackageOptimizer,
    IsolatedOptimizationRunner,
    OptimizationAgent,
    OptimizationCase,
    OptimizationSuite,
    OptimizationFinalSuite,
)
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.model.contracts import ModelEventKind, ModelResponse, ModelStreamEvent
from sagents.v2.package.presets import BuiltinPackageFactory
from sagents.v2.testing.plugins.scripted_model import (
    ScriptedModelProvider,
    ScriptedModelStep,
)


def package(name, instructions):
    data = BuiltinPackageFactory.create(
        "assistant", package_id=f"demo.{name}",
    ).model_dump(mode="json")
    data["agents"]["assistant"]["instructions"] = {"inline": instructions}
    data["agents"]["assistant"]["tools"] = []
    return AgentPackageBundle.model_validate({"manifest": data})


async def demo(root: Path):
    target = package(
        "target", "Convert units accurately. Return the resulting quantity."
    )
    evaluator = package(
        "evaluator",
        "Evaluate task evidence using the supplied rubric. Return JSON only.",
    )
    tuner = package(
        "tuner",
        "Improve the supplied agent within the allowed scope. Return a JSON patch only.",
    )
    proposals = iter(("Verify units", "Be brief", "Verify units and arithmetic"))
    scores = {
        "original": 0.4,
        "Verify units": 0.6,
        "Be brief": 0.5,
        "Verify units and arithmetic": 0.8,
    }

    async def authorize(action, bundle, ctx):
        if action != "optimize_run" or ctx.actor.principal_id != "demo":
            raise PermissionError("outside demo grant")
        if bundle.manifest.metadata.id not in {
            "demo.target",
            "demo.evaluator",
            "demo.tuner",
        }:
            raise PermissionError("unexpected package")
        if bundle.manifest.agents["assistant"].tools:
            raise PermissionError("offline demo grants no tools")

    def factory(bundle, workspace, ctx):
        name = bundle.manifest.metadata.id
        if name == "demo.tuner":
            text = json.dumps(
                {
                    "rationale": "Try an alternative conversion strategy",
                    "instruction_guidance": next(proposals),
                }
            )
        elif name == "demo.target":
            instructions = (
                bundle.resolved_manifest().agents["assistant"].instructions.inline
            )
            text = (
                instructions.split("Optimization guidance:\n")[-1]
                if "Optimization guidance:" in instructions
                else "original"
            )
        else:
            # Scripted grader reads the target observation from the current request.
            # This model adapter is configured below using a small wrapper.
            text = ""
        provider = ScriptedModelProvider(
            (
                ScriptedModelStep(
                    events=(
                        ModelStreamEvent(
                            kind=ModelEventKind.COMPLETED,
                            response=ModelResponse(
                                response_id="demo", text=text, finish_reason="stop"
                            ),
                        ),
                    )
                ),
            )
        )
        return (
            ApplicationConfiguration((provided('example.model-provider', lambda context, deps, value=provider: value, 'model.provider'),), runtime_for(workspace / 'sessions', bundle.manifest.runtime, capabilities={'model.provider': {'plugin': 'example.model-provider'}}), {'models': {'primary': {'provider': 'openai-responses', 'model': 'scripted'}}})
        )

    native = IsolatedOptimizationRunner(
        builder_factory=factory, authorize=authorize, root=root
    )

    class DemoRunner:
        async def run(self, bundle, agent_id, content, ctx):
            if bundle.manifest.metadata.id == "demo.evaluator":
                request = json.loads(content)
                if request["task"].startswith("Audit"):
                    answer = json.dumps(
                        {
                            "approved": True,
                            "rationale": "Scripted consistent suite",
                            "issues": [],
                        }
                    )
                elif request["task"].startswith("Review"):
                    answer = json.dumps(
                        {
                            "approved": True,
                            "memorization_detected": False,
                            "goal_drift_detected": False,
                            "permission_drift_detected": False,
                            "rationale": "Scripted demonstration of semantic approval",
                        }
                    )
                else:
                    score = scores[request["data"]["observation"]["output"]]
                    answer = json.dumps(
                        {
                            "score": score,
                            "passed": score >= 0.6,
                            "rationale": "Scripted demonstration grade",
                        }
                    )

                # Make the evaluator a real v2 Agent invocation too.
                def grader_factory(package, workspace, context):
                    provider = ScriptedModelProvider(
                        (
                            ScriptedModelStep(
                                events=(
                                    ModelStreamEvent(
                                        kind=ModelEventKind.COMPLETED,
                                        response=ModelResponse(
                                            response_id="grade",
                                            text=answer,
                                            finish_reason="stop",
                                        ),
                                    ),
                                )
                            ),
                        )
                    )
                    return (
                        ApplicationConfiguration((provided('example.model-provider', lambda context, deps, value=provider: value, 'model.provider'),), runtime_for(workspace / 'sessions', package.manifest.runtime, capabilities={'model.provider': {'plugin': 'example.model-provider'}}), {'models': {'primary': {'provider': 'openai-responses', 'model': 'scripted'}}})
                    )

                grader = IsolatedOptimizationRunner(
                    builder_factory=grader_factory, authorize=authorize, root=root
                )
                return await grader.run(bundle, agent_id, content, ctx)
            return await native.run(bundle, agent_id, content, ctx)

    optimizer = AgentPackageOptimizer(
        runner=DemoRunner(),
        evaluator=OptimizationAgent(package=evaluator, agent_id="assistant"),
        tuner=OptimizationAgent(package=tuner, agent_id="assistant"),
    )
    suite = OptimizationSuite(
        cases=(
            OptimizationCase(
                id="km", input="Convert 2 km to meters", rubric="Exactly 2000 m"
            ),
            OptimizationCase(
                id="cm",
                input="Convert 7 cm to millimeters",
                rubric="Exactly 70 mm",
                split="validation",
            ),
        )
    )
    ctx = RequestContext(
        actor=ActorRef(principal_id="demo", principal_type=PrincipalType.USER)
    )
    result = await optimizer.optimize(
        target,
        context=ctx,
        goal="Improve conversion accuracy",
        rounds=3,
        suite=suite,
        final_suite=OptimizationFinalSuite(
            cases=(
                OptimizationCase(
                    id="final",
                    input="Convert 13 meters to centimeters",
                    rubric="Exactly 1300 cm",
                    split="final",
                ),
            )
        ),
    )
    print(
        json.dumps(
            {
                "original_hash": target.content_hash,
                "candidate_hash": result.candidate_package.content_hash,
                "baseline_score": result.report.baseline.mean_score("validation"),
                "selected_score": result.report.selected.mean_score("validation"),
                "final_passed": result.report.final_verification.passed,
                "rounds": [
                    {
                        "round": item.round,
                        "accepted": item.accepted,
                        "reason": item.reason,
                    }
                    for item in result.report.rounds
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="sage-optimizer-demo-") as directory:
        asyncio.run(demo(Path(directory)))

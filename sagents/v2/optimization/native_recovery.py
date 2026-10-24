"""Recover local assessment responses for revalidation, including repair inputs.

This preserves the native state and rejected assessments. A recovered response
must pass the same file/schema/evidence checks as the original call; replaying
an invalid response lets the existing bounded repair consume its next receipt.
"""

from collections import defaultdict, deque
import json

from sagents.v2.optimization.contracts import OptimizationObservation
from sagents.v2.optimization.evaluation_files import (
    assessment_loop_interrupted,
    assessment_terminal_response_empty,
)
from sagents.v2.optimization.recovery import OptimizationRecovery, call_key

PROTOCOL = "sage.rsi.local-assessment-revalidation/v1"


class RevalidatingOptimizationRecovery(OptimizationRecovery):
    def __init__(self, path, **options):
        super().__init__(path, **options)
        if not options.get("local_file_evaluator"):
            return
        responses = defaultdict(deque)
        for line in self.path.read_text().splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                # The base reader already checked that only a partial tail can
                # be ignored. Do not relax corruption or run-identity checks.
                break
            if event["event"] != "agent_call_completed":
                continue
            data = event["data"]
            start = self._agent_starts.get(data["call_id"])
            if start is None or start["role"] != "evaluation":
                continue
            request = json.loads(start["request"])
            if (
                request.get("data", {}).get("protocol")
                != "sage.rsi.evaluation-files/v1"
            ):
                continue
            definitions = (
                (self.operation.get("internal_agents") or {})
                .get("evaluator", {})
                .get("package", {})
                .get("manifest", {})
                .get("agents", {})
            )
            if not definitions or any(
                not {"file_read", "file_write"} <= set(agent.get("tools", ()))
                or not set(agent.get("tools", ())) <= {"file_read", "file_write"}
                for agent in definitions.values()
            ):
                continue
            observation = OptimizationObservation.model_validate(data["observation"])
            if observation.state != "completed" and not (
                assessment_loop_interrupted(observation)
                or assessment_terminal_response_empty(observation)
            ):
                continue
            responses[call_key(start)].append((data["call_id"], observation))
        for key, queue in responses.items():
            self.calls[key] = queue

"""Host-computed selection scores; quality judgments and pass/fail stay intact."""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from sagents.v2.contracts.common import StrictModel


class BuiltinScoringUnavailable(ValueError):
    """The selected resource cannot be measured; never substitute a free run."""
    def __init__(self, message, *, code="rsi.cost_unavailable"):
        super().__init__(message)
        self.code = code


class BuiltinScoring(StrictModel):
    mode: Literal["quality", "quality_cost", "quality_latency", "quality_tokens"] = "quality"
    efficiency_weight: float = Field(default=0.2, gt=0, lt=1, allow_inf_nan=False)
    cost_reference: float = Field(default=1, gt=0, allow_inf_nan=False)
    latency_reference: float = Field(default=60, gt=0, allow_inf_nan=False)
    token_reference: float = Field(default=10000, gt=0, allow_inf_nan=False)

    def apply(self, result):
        if self.mode == "quality":
            return result
        observation = result.observation
        metrics = {"quality": result.grade.score}
        if self.mode == "quality_cost":
            value, reference, name = observation.cost, self.cost_reference, "cost"
            if value is None:
                raise BuiltinScoringUnavailable("quality_cost scoring requires reported execution cost; missing cost is not zero")
        elif self.mode == "quality_latency":
            value, reference, name = observation.elapsed_seconds, self.latency_reference, "elapsed_seconds"
        else:
            if observation.usage_reported is not True:
                raise BuiltinScoringUnavailable("quality_tokens scoring requires complete provider usage", code="rsi.tokens_unavailable")
            value = observation.input_tokens + observation.output_tokens
            reference, name = self.token_reference, "tokens"
        metrics[name] = float(value)
        if name == "tokens":
            metrics.update(input_tokens=float(observation.input_tokens), output_tokens=float(observation.output_tokens),
                cached_input_tokens=float(observation.cached_input_tokens), reasoning_tokens=float(observation.reasoning_tokens))
        efficiency = 1 / (1 + value / reference)
        # Efficiency cannot turn a zero-quality execution into a useful result.
        score = result.grade.score * (1 - self.efficiency_weight + self.efficiency_weight * efficiency)
        return result.model_copy(update={"objective_score": score, "score_metrics": metrics})

    def selection_policy(self):
        return {"builtin_scoring": self.model_dump(mode="json"),
            "metric": ("validation_mean" if self.mode == "quality" else
                "Validation mean of quality * (1 - weight + weight / (1 + measured_resource / reference))"),
            "instruction": "Quality grades and task pass/fail remain authoritative. Resource metrics come from target execution only. "
                "Do not weaken task completion or claim unmeasured savings."}

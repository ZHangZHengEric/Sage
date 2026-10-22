"""Dataset-independent execution scoring protocol; the default remains eval-agent scoring."""
from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import Field, model_validator

from sagents.v2.contracts.common import StrictModel
from sagents.v2.optimization.contracts import OptimizationCase, OptimizationGrade, OptimizationObservation


class ScorerDescriptor(StrictModel):
    protocol: Literal['sage.rsi.scorer/v1'] = 'sage.rsi.scorer/v1'
    id: str = Field(min_length=1, max_length=192)
    name: str = Field(min_length=1, max_length=255)
    version: str = Field(min_length=1, max_length=128)
    contract: str | None = Field(default=None, min_length=1, max_length=16000)


class ScoringRequest(StrictModel):
    protocol: Literal['sage.rsi.scorer/v1'] = 'sage.rsi.scorer/v1'
    goal: str
    case: OptimizationCase
    observation: OptimizationObservation
    conversation: tuple[dict[str, Any], ...] = ()


class ScoringResult(StrictModel):
    protocol: Literal['sage.rsi.scorer/v1'] = 'sage.rsi.scorer/v1'
    grade: OptimizationGrade | None = None
    not_applicable_reason: str | None = Field(default=None, min_length=1, max_length=2000)
    details: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode='after')
    def one_scoring_outcome(self):
        if (self.grade is None) == (self.not_applicable_reason is None):
            raise ValueError('return either a grade or an explicit not_applicable_reason')
        if self.not_applicable_reason is not None and not self.not_applicable_reason.strip():
            raise ValueError('not_applicable_reason must explain why this case cannot be scored')
        return self


class ExecutionScorer(Protocol):
    """Trusted host binding, never a tool granted to the target or tuner."""
    descriptor: ScorerDescriptor

    async def score(self, request: ScoringRequest) -> ScoringResult: ...

"""Shared pairwise wire types, independent of plugins and evaluation engines."""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from sagents.v2.contracts.common import StrictModel
from sagents.v2.optimization.contracts import OptimizationDiagnosis


class PairwiseDecision(StrictModel):
    protocol: Literal['sage.rsi.comparison.result/v1'] = 'sage.rsi.comparison.result/v1'
    winner: Literal['A', 'B', 'tie']
    rationale: str = Field(min_length=1, max_length=4000)
    analysis: OptimizationDiagnosis | None = None


class PairwiseMeasurementError(ValueError):
    rsi_requires_feedback = True
    rsi_authoritative_measurement_failed = True

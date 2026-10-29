"""Server RSI admission: only instructions and package-owned Skills are editable."""

from typing import Literal

from pydantic import Field, model_validator

from sagents.v2.contracts.common import StrictModel
from sagents.v2.optimization.contracts import OptimizationSuite, OptimizationStoppingPolicy


class RsiStart(StrictModel):
    request_id: str = Field(min_length=1, max_length=128, pattern=r"\S")
    goal: str = Field(min_length=1, max_length=16000, pattern=r"\S")
    optimization_scope: tuple[Literal["instructions", "skills"], ...] = ("instructions", "skills")
    model_id: str | None = Field(default=None, min_length=1, max_length=128)
    suite: OptimizationSuite | None = None
    rounds: int = Field(default=8, ge=1, le=100)
    initial_training_case_count: int = Field(default=6, ge=1, le=100)
    training_cases_per_round: int = Field(default=6, ge=0, le=100)
    validation_case_count: int = Field(default=24, ge=1, le=100)
    evaluation_repeats: int = Field(default=1, ge=1, le=10)
    max_concurrency: int = Field(default=3, ge=1, le=16)
    call_timeout_seconds: int = Field(default=240, ge=1, le=7200)
    timeout_seconds: int = Field(default=3600, ge=1, le=86400)
    max_system_prompt_chars: int = Field(default=64000, ge=1, le=1000000)
    max_skill_chars: int = Field(default=32000, ge=1, le=1000000)
    max_skill_count: int = Field(default=16, ge=0, le=256)
    max_edit_repairs: int = Field(default=3, ge=0, le=10)
    stopping_policy: OptimizationStoppingPolicy = Field(default_factory=OptimizationStoppingPolicy)

    @model_validator(mode="before")
    @classmethod
    def imported_validation_count(cls, value):
        if isinstance(value, dict) and value.get("suite") is not None:
            suite = OptimizationSuite.model_validate(value["suite"])
            return {**value, "suite": suite, "validation_case_count": sum(c.split == "validation" for c in suite.cases)}
        return value

    @model_validator(mode="after")
    def validate_scope(self):
        if not self.optimization_scope or len(set(self.optimization_scope)) != len(self.optimization_scope):
            raise ValueError("optimization_scope must contain unique parts")
        return self


class RsiApply(StrictModel):
    expected_package_ref: str = Field(min_length=1, max_length=80)

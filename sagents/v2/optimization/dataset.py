"""Portable data-only RSI dataset format, independent of runners and scorers."""
from typing import Literal

from pydantic import Field, model_validator

from sagents.v2.contracts.common import StrictModel
from sagents.v2.optimization.contracts import OptimizationCase, OptimizationSuite, OptimizationTestSuite


class DatasetEnvironment(StrictModel):
    protocol: Literal['sage.rsi.case/v1'] = 'sage.rsi.case/v1'
    mcp_servers: tuple[str, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode='after')
    def unique_servers(self):
        if len(set(self.mcp_servers)) != len(self.mcp_servers) or any(not name.strip() for name in self.mcp_servers):
            raise ValueError('environment MCP server names must be nonempty and unique')
        return self


class OptimizationDataset(StrictModel):
    format_version: Literal['sage.rsi.dataset/v1'] = 'sage.rsi.dataset/v1'
    name: str = Field(min_length=1, max_length=255)
    cases: tuple[OptimizationCase, ...] = Field(min_length=2, max_length=10000)
    environment: DatasetEnvironment | None = None

    @model_validator(mode='after')
    def validate_splits(self):
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError('dataset case IDs must be unique across splits')
        splits = {case.split for case in self.cases}
        if not {'training', 'validation'} <= splits or not splits <= {'training', 'validation', 'test'}:
            raise ValueError('dataset requires training and validation; test is optional')
        return self

    def optimization_suite(self):
        return OptimizationSuite(cases=tuple(c for c in self.cases if c.split != 'test'))

    def human_test_suite(self):
        cases = tuple(c for c in self.cases if c.split == 'test')
        return OptimizationTestSuite(cases=cases) if cases else None

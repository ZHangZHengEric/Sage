"""Portable data-only RSI dataset format, independent of runners and scorers."""
from typing import Literal
from collections import Counter

from pydantic import Field, model_validator, model_serializer

from sagents.v2.contracts.common import StrictModel
from sagents.v2.optimization.contracts import OptimizationCase, OptimizationSuite, OptimizationTestSuite


class DatasetEnvironment(StrictModel):
    protocol: Literal['sage.rsi.case/v1'] = 'sage.rsi.case/v1'
    mcp_servers: tuple[str, ...] = Field(min_length=1, max_length=16)
    terminal_on_done: bool = Field(default=False, strict=True)

    @model_serializer(mode='wrap')
    def stable_legacy_binding(self, serialize):
        value = serialize(self)
        if not self.terminal_on_done:
            value.pop('terminal_on_done', None)
        return value

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
        if not self.name.strip():
            raise ValueError('dataset.name must not be blank')
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError(f'duplicate dataset case IDs: {sorted(k for k, n in Counter(case.id for case in self.cases).items() if n > 1)}')
        if any(not case.id.strip() for case in self.cases):
            raise ValueError('dataset contains an empty case ID')
        invalid = [case.id for case in self.cases if case.split not in {'training', 'validation', 'test'}]
        if invalid:
            raise ValueError(f'dataset cases have invalid splits: {invalid}')
        splits = {case.split for case in self.cases}
        if not {'training', 'validation'} <= splits or not splits <= {'training', 'validation', 'test'}:
            raise ValueError('dataset requires training and validation; test is optional')
        return self

    def optimization_suite(self):
        return OptimizationSuite(cases=tuple(c for c in self.cases if c.split != 'test'))

    def human_test_suite(self):
        cases = tuple(c for c in self.cases if c.split == 'test')
        return OptimizationTestSuite(cases=cases) if cases else None


def validate_imported_dataset(value):
    """Require explicit wire fields; Python constructors retain ergonomic defaults."""
    if not isinstance(value, dict):
        raise ValueError('dataset: expected an object')
    if value.get('format_version') != 'sage.rsi.dataset/v1':
        raise ValueError('dataset.format_version: expected sage.rsi.dataset/v1')
    if isinstance(value.get('cases'), list):
        for index, case in enumerate(value['cases']):
            if isinstance(case, dict):
                missing = {'id', 'input', 'rubric', 'split'} - case.keys()
                if missing:
                    raise ValueError(f'dataset.cases[{index}] ({case.get("id", "unknown")}): missing {sorted(missing)}')
    return OptimizationDataset.model_validate(value)

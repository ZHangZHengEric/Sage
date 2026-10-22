"""Imported evaluation plans and host-only MCP scorer bindings."""
from __future__ import annotations

import ast
import hashlib
import json
from typing import Literal

from pydantic import Field, model_validator

from sagents.v2.contracts.common import StrictModel, ToolName, new_id
from sagents.v2.optimization.contracts import OptimizationSuite, OptimizationTestSuite
from sagents.v2.optimization.scoring import ScorerDescriptor, ScoringResult
from sagents.v2.optimization.dataset import OptimizationDataset
from sagents.v2.tool.contracts import ToolCall


class ScorerSelection(StrictModel):
    mode: Literal['eval_agent', 'mcp', 'python'] = 'eval_agent'
    descriptor: ScorerDescriptor | None = None
    tool: ToolName | None = None
    module_id: str | None = None
    # A host-owned transport/schema fingerprint, not a model grant.
    binding_id: str | None = None

    @model_validator(mode='after')
    def validate_choice(self):
        if self.mode == 'mcp' and (self.descriptor is None or self.tool is None):
            raise ValueError('MCP scoring requires a descriptor and tool')
        if self.mode == 'python' and (self.descriptor is None or self.module_id is None or self.tool is not None):
            raise ValueError('Python scoring requires a frozen module and descriptor')
        if self.mode == 'eval_agent' and (self.descriptor is not None or self.tool is not None or self.binding_id is not None or self.module_id is not None):
            raise ValueError('default eval scoring must not include an external binding')
        return self


class ScorerImport(StrictModel):
    name: str = Field(min_length=1, max_length=255)
    source: str = Field(min_length=1, max_length=1024 * 1024)

    @model_validator(mode='after')
    def validate_source(self):
        try:
            tree = ast.parse(self.source)
        except SyntaxError as exc:
            raise ValueError('scorer must be valid Python source') from exc
        if not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == 'score' for node in tree.body):
            raise ValueError('scorer must export score(request)')
        return self


class EvaluationPlan(StrictModel):
    format_version: Literal['sage.rsi.evaluation/v1'] = 'sage.rsi.evaluation/v1'
    name: str = Field(min_length=1, max_length=255)
    goal: str | None = Field(default=None, min_length=1, max_length=16000)
    dataset: OptimizationDataset | None = None
    suite: OptimizationSuite | None = None
    human_test_suite: OptimizationTestSuite | None = None
    scorer: ScorerSelection = Field(default_factory=ScorerSelection)

    @model_validator(mode='after')
    def no_host_identity(self):
        if self.scorer.binding_id is not None:
            raise ValueError('imported plans cannot specify host binding identity')
        if self.dataset is not None and (self.suite is not None or self.human_test_suite is not None):
            raise ValueError('dataset is the single source of imported cases')
        return self

    def training_suite(self):
        return self.dataset.optimization_suite() if self.dataset else self.suite

    def test_suite(self):
        return self.dataset.human_test_suite() if self.dataset else self.human_test_suite


class McpExecutionScorer:
    """Calls a frozen MCP scoring tool; it is never added to Agent allowlists."""
    def __init__(self, selection, plugin, context, run_id):
        self.selection, self.plugin = selection, plugin
        self.descriptor = selection.descriptor
        self.context, self.run_id = context, run_id

    async def score(self, request):
        token = new_id('score')
        result = await self.plugin.execute(ToolCall(tool_call_id=token,
            tool_name=self.selection.tool, arguments={'request': request.model_dump(mode='json')},
            operation_id=token, idempotency_key=token, owner_run_id=self.run_id,
            owner_agent_id='rsi-scorer'), self.context)
        if result.error is not None:
            raise RuntimeError('configured scorer did not return a completed score')
        json_values = [block.value for block in result.content if block.kind == 'json']
        if json_values:
            return ScoringResult.model_validate(json_values[0])
        text = ''.join(block.text for block in result.content if block.kind == 'text')
        return ScoringResult.model_validate_json(text)


def scorer_binding(selection, plugin, definition):
    data = {'selection': selection.model_dump(mode='json', exclude={'binding_id'}),
        'servers': plugin.servers_fingerprint(plugin.servers),
        'definition': definition.model_dump(mode='json')}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

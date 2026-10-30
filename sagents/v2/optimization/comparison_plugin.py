"""Standard dataset-owned preparation and anonymous comparison plugin protocol."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import Field, model_validator

from sagents.v2.contracts.common import StrictModel
from sagents.v2.optimization.contracts import OptimizationCase, OptimizationObservation
from sagents.v2.optimization.pairwise import PairwiseDecision
from sagents.v2.optimization.scoring import ScorerDescriptor
from sagents.v2.optimization.python_scorer import PythonExecutionScorer, ScorerExecutionError


class ComparisonPreparationRequest(StrictModel):
    protocol: Literal['sage.rsi.comparison.prepare/v1'] = 'sage.rsi.comparison.prepare/v1'
    capture_id: str = Field(min_length=1, max_length=128)
    artifact_directory: str | None = Field(default=None, min_length=1, max_length=4096)
    goal: str
    case: OptimizationCase
    observation: OptimizationObservation


class FrozenComparisonFile(StrictModel):
    path: str = Field(min_length=1, max_length=4096)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    size_bytes: int = Field(ge=0, le=64 * 1024 * 1024)
    media_type: str = Field(min_length=1, max_length=128)

    def verify(self):
        from sagents.v2.optimization.pairwise import PairwiseMeasurementError
        path = Path(self.path)
        try:
            if not path.is_absolute() or path.is_symlink() or not path.is_file() or path.stat().st_size != self.size_bytes:
                raise ValueError('invalid artifact file')
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            if digest != self.sha256:
                raise ValueError('artifact file content changed')
        except (OSError, ValueError) as error:
            raise PairwiseMeasurementError('Frozen comparison artifact is missing or changed') from error


class EvaluationPresentation(StrictModel):
    text: str = Field(default='', max_length=32000)
    images: tuple[str, ...] = Field(default=(), max_length=32)


class DiagnosticEvidence(StrictModel):
    text: str = Field(default='', max_length=32000)
    files: tuple[str, ...] = Field(default=(), max_length=128)


class PreparedComparisonArtifact(StrictModel):
    protocol: Literal['sage.rsi.comparison.artifact/v1'] = 'sage.rsi.comparison.artifact/v1'
    artifact: dict[str, Any]
    execution_failure: str | None = Field(default=None, min_length=1, max_length=256)
    files: tuple[FrozenComparisonFile, ...] = Field(default=(), max_length=256)
    diagnostics: DiagnosticEvidence | None = None

    @model_validator(mode='after')
    def bounded_artifact(self):
        encoded = json.dumps(self.artifact, allow_nan=False)
        if not self.artifact or len(encoded.encode()) > 4 * 1024 * 1024:
            raise ValueError('prepared artifact must be nonempty and at most 4 MiB')
        if 'presentation' in self.artifact:
            presentation = EvaluationPresentation.model_validate(self.artifact['presentation'])
            files = {item.path: item for item in self.files}
            if any(path not in files or files[path].media_type not in {'image/png', 'image/jpeg', 'image/webp'}
                    for path in presentation.images):
                raise ValueError('Presentation images must reference declared frozen image files')
        if self.diagnostics:
            declared = {item.path: item for item in self.files}
            if any(path not in declared or declared[path].media_type not in {
                    'text/plain', 'text/html', 'text/css', 'text/javascript', 'application/javascript',
                    'application/json', 'image/svg+xml'} for path in self.diagnostics.files):
                raise ValueError('Diagnostic files must reference declared UTF-8 evidence files')
        return self


    def verify_files(self):
        for item in self.files:
            item.verify()


class ComparisonRequest(StrictModel):
    protocol: Literal['sage.rsi.comparison/v1'] = 'sage.rsi.comparison/v1'
    goal: str
    case: OptimizationCase
    A: PreparedComparisonArtifact
    B: PreparedComparisonArtifact


class ComparisonPlugin(Protocol):
    descriptor: ScorerDescriptor

    async def prepare(self, request: ComparisonPreparationRequest) -> PreparedComparisonArtifact: ...

    async def compare(self, request: ComparisonRequest) -> PairwiseDecision: ...


class PythonComparisonPlugin(PythonExecutionScorer):
    """Same frozen dependency/runtime binding as score plugins, distinct wire protocol."""
    worker_module = 'sagents.v2.optimization.comparison_plugin_worker'

    async def _invoke(self, operation, request, schema):
        payload = json.dumps({'operation': operation, 'request': request.model_dump(mode='json')}).encode()
        if len(payload) > 32 * 1024 * 1024:
            raise ScorerExecutionError('comparison request exceeds 32 MiB')
        if self.model_api_factory is not None and operation == 'compare':
            async with self.model_api_factory(request) as api:
                return schema.model_validate_json(await self._execute(payload, model_api=api))
        return schema.model_validate_json(await self._execute(payload, model_api=self.model_api))

    async def prepare(self, request):
        return await self._invoke('prepare', request, PreparedComparisonArtifact)

    async def compare(self, request):
        return await self._invoke('compare', request, PairwiseDecision)

    async def score(self, request):
        raise ScorerExecutionError('comparison plugins require prepare/compare, not absolute score')

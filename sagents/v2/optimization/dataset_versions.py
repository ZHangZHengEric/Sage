"""Human-owned, immutable dataset revisions; never an optimization-agent action."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Literal

from pydantic import Field, model_validator, field_validator

from sagents.v2.contracts.common import StrictModel
from sagents.v2.optimization.dataset import OptimizationDataset
from sagents.v2.optimization.recovery import configuration_fingerprint


class SuitePreflightPolicy(StrictModel):
    protocol: Literal['sage.rsi.preflight/v1'] = 'sage.rsi.preflight/v1'
    imported_semantics: Literal['diagnostic_only'] = 'diagnostic_only'
    generated_repairs: int = Field(default=2, ge=0, le=5)


class CaseExclusionProposal(StrictModel):
    case_id: str = Field(min_length=1)
    reason_code: Literal['missing_information', 'invalid_fixture', 'invalid_reference', 'policy_conflict', 'protocol_error']
    reason: str = Field(min_length=1, max_length=4000)
    evidence: tuple[str, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode='after')
    def concrete_evidence(self):
        if not self.case_id.strip() or not self.reason.strip() or any(not item.strip() for item in self.evidence):
            raise ValueError(f'case {self.case_id!r}: exclusion requires a reason and concrete evidence')
        return self


class ConfirmedCaseExclusion(CaseExclusionProposal):
    operator: str = Field(min_length=1)
    confirmed_at: datetime
    source_version: str = Field(min_length=1)


class DatasetRevisionRequest(StrictModel):
    expected_version: str = Field(min_length=1)
    confirmed: Literal[True]
    exclusions: tuple[CaseExclusionProposal, ...] = Field(min_length=1, max_length=10000)

    @field_validator('confirmed', mode='before')
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError('explicit human confirmation is required')
        return value


class DatasetVersion(StrictModel):
    protocol: Literal['sage.rsi.dataset-version/v1'] = 'sage.rsi.dataset-version/v1'
    id: str
    source_version: str
    parent_version: str | None = None
    dataset: OptimizationDataset
    exclusions: tuple[ConfirmedCaseExclusion, ...] = ()

    @staticmethod
    def source_id(dataset):
        return 'dataset_' + configuration_fingerprint(dataset.model_dump(mode='json'))

    @staticmethod
    def identity(source, parent, exclusions):
        if not exclusions and parent is None:
            return source
        return 'dataset_' + configuration_fingerprint(dict(source=source, parent=parent,
            exclusions=[item.model_dump(mode='json') for item in exclusions]))

    @model_validator(mode='after')
    def integrity(self):
        if self.source_version != self.source_id(self.dataset):
            raise ValueError('dataset source version does not match original content')
        ids = [item.case_id for item in self.exclusions]
        if len(ids) != len(set(ids)):
            raise ValueError('exclusion case IDs must be unique')
        known = {case.id for case in self.dataset.cases}
        if set(ids) - known:
            raise ValueError(f'exclusions reference unknown case IDs: {sorted(set(ids) - known)}')
        if any(item.source_version != self.source_version for item in self.exclusions):
            raise ValueError('exclusion source version mismatch')
        if self.id != self.identity(self.source_version, self.parent_version, self.exclusions):
            raise ValueError('dataset version identity mismatch')
        self.active_dataset()  # Exclusions cannot remove an entire required split.
        return self

    @classmethod
    def imported(cls, dataset):
        source = cls.source_id(dataset)
        return cls(id=source, source_version=source, dataset=dataset)

    def revise(self, request, *, operator):
        request = DatasetRevisionRequest.model_validate(request.model_dump(mode='json'))
        if request.expected_version != self.id:
            raise ValueError('dataset version changed; review the current version before confirming')
        existing = {item.case_id for item in self.exclusions}
        proposed = [item.case_id for item in request.exclusions]
        if len(set(proposed)) != len(proposed) or existing.intersection(proposed):
            raise ValueError('case is already excluded or appears more than once')
        marks = (*self.exclusions, *(ConfirmedCaseExclusion(**item.model_dump(), operator=operator,
            confirmed_at=datetime.now(timezone.utc), source_version=self.source_version)
            for item in request.exclusions))
        return DatasetVersion(id=self.identity(self.source_version, self.id, marks),
            source_version=self.source_version, parent_version=self.id, dataset=self.dataset, exclusions=marks)

    def active_dataset(self):
        removed = {item.case_id for item in self.exclusions}
        return OptimizationDataset.model_validate({**self.dataset.model_dump(mode='json'),
            'cases': [case.model_dump(mode='json') for case in self.dataset.cases if case.id not in removed]})

    def manifest(self):
        removed = {item.case_id for item in self.exclusions}
        original = Counter(case.split for case in self.dataset.cases)
        excluded = Counter(case.split for case in self.dataset.cases if case.id in removed)
        return dict(version_id=self.id, source_version=self.source_version, parent_version=self.parent_version,
            name=self.dataset.name, label='revised' if removed else 'original',
            original_count=len(self.dataset.cases), excluded_count=len(removed),
            active_count=len(self.dataset.cases) - len(removed),
            counts={split: dict(original=original[split], excluded=excluded[split],
                               active=original[split] - excluded[split])
                    for split in ('training', 'validation', 'test')},
            active_case_ids=[case.id for case in self.dataset.cases if case.id not in removed],
            exclusions=[item.model_dump(mode='json') for item in self.exclusions],
            complete_original_test=not any(case.split == 'test' and case.id in removed for case in self.dataset.cases))


def optimization_dataset_manifest(manifest):
    """Bind the full human-owned version without passing hidden case IDs or diagnostics."""
    if manifest is None:
        return None
    safe = {key: manifest[key] for key in ('version_id', 'source_version', 'parent_version',
        'label', 'original_count', 'excluded_count', 'active_count', 'counts', 'complete_original_test') if key in manifest}
    safe['binding'] = configuration_fingerprint(manifest)
    return safe

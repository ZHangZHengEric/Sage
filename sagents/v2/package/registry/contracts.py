"""SAgents V2 module for package/registry/contracts.py."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import Field

from sagents.v2.contracts.common import Identifier, StrictModel
from sagents.v2.package.manifest import SageManifest
from sagents.v2.testing import ScenarioSuiteReport


class PackageStage(str, Enum):
    DRAFT = "draft"
    VALIDATED = "validated"
    TESTED = "tested"
    PUBLISHED = "published"
    RETIRED = "retired"


class AgentPackageRecord(StrictModel):
    package_id: Identifier
    version: str
    revision: int = Field(ge=0)
    stage: PackageStage
    manifest: SageManifest
    manifest_hash: str
    test_report: ScenarioSuiteReport | None = None
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None = None
    retired_at: datetime | None = None


class PackageValidationReport(StrictModel):
    valid: bool
    manifest_hash: str
    revision: int = Field(ge=0)
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

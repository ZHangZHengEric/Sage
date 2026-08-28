"""Reference AgentPackage lifecycle registry with validation and promotion gates."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from sagents.v2.contracts.common import utc_now
from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.package.manifest import CompositionResolver, SageManifest
from sagents.v2.package.registry.contracts import (
    AgentPackageRecord,
    PackageStage,
    PackageValidationReport,
)
from sagents.v2.testing import ScenarioSuiteReport


PackageEvaluator = Callable[[SageManifest], Awaitable[ScenarioSuiteReport]]


class InMemoryAgentPackageRegistry:
    """Exercise draft/validate/test/publish/retire semantics in one process.

    Publication state is intentionally explicit, but this implementation does
    not provide a persistent organization registry, package signatures, or a
    production trust store.
    """

    def __init__(self, *, resolver=None, clock=utc_now) -> None:
        self._resolver = resolver or CompositionResolver()
        self._clock = clock
        self._lock = asyncio.Lock()
        self._records: dict[tuple[str, str], AgentPackageRecord] = {}

    async def save_draft(
        self, manifest: SageManifest, *, expected_revision: int | None = None
    ) -> AgentPackageRecord:
        resolved = self._resolver.resolve(manifest)
        key = (manifest.metadata.id, manifest.metadata.version)
        async with self._lock:
            current = self._records.get(key)
            if current is not None and current.stage in {
                PackageStage.PUBLISHED,
                PackageStage.RETIRED,
            }:
                raise self._error(
                    "package.version_immutable",
                    "published package versions are immutable",
                )
            if current is None:
                if expected_revision not in {None, 0}:
                    raise self._revision_conflict(expected_revision, None)
                now = self._clock()
                record = AgentPackageRecord(
                    package_id=key[0],
                    version=key[1],
                    revision=0,
                    stage=PackageStage.DRAFT,
                    manifest=manifest,
                    manifest_hash=resolved.manifest_hash,
                    created_at=now,
                    updated_at=now,
                )
            else:
                if expected_revision is None or expected_revision != current.revision:
                    raise self._revision_conflict(expected_revision, current.revision)
                record = current.model_copy(
                    update={
                        "revision": current.revision + 1,
                        "stage": PackageStage.DRAFT,
                        "manifest": manifest,
                        "manifest_hash": resolved.manifest_hash,
                        "test_report": None,
                        "updated_at": self._clock(),
                    }
                )
            self._records[key] = record
            return record

    async def validate(
        self, package_id: str, version: str, *, expected_revision: int
    ) -> PackageValidationReport:
        async with self._lock:
            current = self._require(package_id, version)
            self._assert_revision(current, expected_revision)
            self._assert_editable(current)
            try:
                resolved = self._resolver.resolve(current.manifest)
                report = PackageValidationReport(
                    valid=True,
                    manifest_hash=resolved.manifest_hash,
                    revision=current.revision + 1,
                )
            except SageV2Error as exc:
                return PackageValidationReport(
                    valid=False,
                    manifest_hash=current.manifest_hash,
                    revision=current.revision,
                    errors=(f"{exc.info.code}: {exc.info.message}",),
                )
            self._records[(package_id, version)] = current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "stage": PackageStage.VALIDATED,
                    "updated_at": self._clock(),
                }
            )
            return report

    async def test(
        self,
        package_id: str,
        version: str,
        evaluator: PackageEvaluator,
        *,
        expected_revision: int,
    ) -> AgentPackageRecord:
        async with self._lock:
            current = self._require(package_id, version)
            self._assert_revision(current, expected_revision)
            if current.stage not in {PackageStage.VALIDATED, PackageStage.TESTED}:
                raise self._error(
                    "package.not_validated", "package must be validated before testing"
                )
            manifest = current.manifest
            manifest_hash = current.manifest_hash
        report = await evaluator(manifest)
        async with self._lock:
            current = self._require(package_id, version)
            self._assert_revision(current, expected_revision)
            if current.manifest_hash != manifest_hash:
                raise self._error(
                    "package.changed_during_test",
                    "package content changed while its test suite was running",
                )
            updated = current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "stage": PackageStage.TESTED,
                    "test_report": report,
                    "updated_at": self._clock(),
                }
            )
            self._records[(package_id, version)] = updated
            return updated

    async def publish(
        self, package_id: str, version: str, *, expected_revision: int
    ) -> AgentPackageRecord:
        async with self._lock:
            current = self._require(package_id, version)
            self._assert_revision(current, expected_revision)
            if current.stage != PackageStage.TESTED or current.test_report is None:
                raise self._error(
                    "package.not_tested",
                    "package must have a test report before publish",
                )
            required_rate = float(
                current.manifest.tests.gates.get("required_pass_rate", 1.0)
            )
            total = current.test_report.passed_count + current.test_report.failed_count
            pass_rate = current.test_report.passed_count / total if total else 0.0
            if not current.test_report.passed or pass_rate < required_rate:
                raise self._error(
                    "package.test_gate_failed",
                    f"test pass rate {pass_rate:.3f} is below required {required_rate:.3f}",
                )
            now = self._clock()
            published = current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "stage": PackageStage.PUBLISHED,
                    "updated_at": now,
                    "published_at": now,
                }
            )
            self._records[(package_id, version)] = published
            return published

    async def retire(
        self, package_id: str, version: str, *, expected_revision: int
    ) -> AgentPackageRecord:
        async with self._lock:
            current = self._require(package_id, version)
            self._assert_revision(current, expected_revision)
            if current.stage != PackageStage.PUBLISHED:
                raise self._error(
                    "package.not_published",
                    "only a published package version can be retired",
                )
            now = self._clock()
            retired = current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "stage": PackageStage.RETIRED,
                    "updated_at": now,
                    "retired_at": now,
                }
            )
            self._records[(package_id, version)] = retired
            return retired

    async def get(self, package_id: str, version: str) -> AgentPackageRecord:
        async with self._lock:
            return self._require(package_id, version)

    async def list(self, package_id: str | None = None):
        async with self._lock:
            return tuple(
                value
                for key, value in sorted(self._records.items())
                if package_id is None or key[0] == package_id
            )

    def _require(self, package_id, version):
        try:
            return self._records[(package_id, version)]
        except KeyError as exc:
            raise self._error(
                "package.not_found", "agent package version was not found"
            ) from exc

    @staticmethod
    def _assert_editable(current):
        if current.stage in {PackageStage.PUBLISHED, PackageStage.RETIRED}:
            raise InMemoryAgentPackageRegistry._error(
                "package.version_immutable",
                "published or retired package versions are immutable",
            )

    @staticmethod
    def _assert_revision(current, expected):
        if current.revision != expected:
            raise InMemoryAgentPackageRegistry._revision_conflict(
                expected, current.revision
            )

    @staticmethod
    def _revision_conflict(expected, current):
        return SageV2Error(
            RuntimeErrorInfo(
                code="package.revision_conflict",
                category=ErrorCategory.CONFLICT,
                message=f"expected revision {expected}, current revision {current}",
                safe_to_resume=True,
            )
        )

    @staticmethod
    def _error(code, message):
        return SageV2Error(
            RuntimeErrorInfo(
                code=code,
                category=ErrorCategory.VALIDATION,
                message=message,
                safe_to_resume=True,
            )
        )

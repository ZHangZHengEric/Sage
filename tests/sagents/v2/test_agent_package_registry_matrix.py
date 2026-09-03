from __future__ import annotations

import asyncio

import pytest

from sagents.v2.package.presets import BuiltinPackageFactory
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.package.registry import InMemoryAgentPackageRegistry, PackageStage
from sagents.v2.testing import ScenarioSuiteReport


def package(*, version="0.1.0", required_rate=1.0):
    value = BuiltinPackageFactory.create(
        "assistant",
        package_id="com.example.assistant",
        model="gpt-test",
    )
    return value.model_copy(
        update={
            "metadata": value.metadata.model_copy(update={"version": version}),
            "tests": value.tests.model_copy(
                update={"gates": {"required_pass_rate": required_rate}}
            ),
        }
    )


def report(*, passed, failed):
    return ScenarioSuiteReport(
        passed=failed == 0,
        passed_count=passed,
        failed_count=failed,
        results=(),
    )


def test_in_memory_registry_reports_non_durable_trust_capabilities():
    assert InMemoryAgentPackageRegistry().capabilities == {
        "durable_across_process_restart": False,
        "supports_package_signatures": False,
        "shared_across_processes": False,
    }


@pytest.mark.asyncio
async def test_package_lifecycle_requires_validation_tests_and_gate_before_publish():
    registry = InMemoryAgentPackageRegistry()
    draft = await registry.save_draft(package())
    assert draft.stage == PackageStage.DRAFT

    with pytest.raises(SageV2Error) as early:
        await registry.publish(draft.package_id, draft.version, expected_revision=0)
    assert early.value.info.code == "package.not_tested"

    validation = await registry.validate(
        draft.package_id, draft.version, expected_revision=0
    )
    assert validation.valid is True
    assert validation.revision == 1
    tested = await registry.test(
        draft.package_id,
        draft.version,
        lambda manifest: asyncio.sleep(0, result=report(passed=2, failed=0)),
        expected_revision=1,
    )
    assert tested.stage == PackageStage.TESTED
    published = await registry.publish(
        draft.package_id, draft.version, expected_revision=2
    )
    assert published.stage == PackageStage.PUBLISHED
    assert published.published_at is not None


@pytest.mark.asyncio
async def test_failed_eval_gate_blocks_publish_and_published_version_is_immutable():
    registry = InMemoryAgentPackageRegistry()
    draft = await registry.save_draft(package(required_rate=0.75))
    await registry.validate(draft.package_id, draft.version, expected_revision=0)
    tested = await registry.test(
        draft.package_id,
        draft.version,
        lambda manifest: asyncio.sleep(0, result=report(passed=2, failed=1)),
        expected_revision=1,
    )
    with pytest.raises(SageV2Error) as failed:
        await registry.publish(
            tested.package_id, tested.version, expected_revision=tested.revision
        )
    assert failed.value.info.code == "package.test_gate_failed"

    registry = InMemoryAgentPackageRegistry()
    draft = await registry.save_draft(package())
    await registry.validate(draft.package_id, draft.version, expected_revision=0)
    tested = await registry.test(
        draft.package_id,
        draft.version,
        lambda manifest: asyncio.sleep(0, result=report(passed=1, failed=0)),
        expected_revision=1,
    )
    await registry.publish(
        tested.package_id, tested.version, expected_revision=tested.revision
    )
    with pytest.raises(SageV2Error) as immutable:
        await registry.save_draft(package(), expected_revision=3)
    assert immutable.value.info.code == "package.version_immutable"


@pytest.mark.asyncio
@pytest.mark.parametrize("required_rate", [-0.1, 1.1, "invalid", float("nan"), True])
async def test_invalid_package_test_gate_is_rejected(required_rate):
    registry = InMemoryAgentPackageRegistry()
    draft = await registry.save_draft(package(required_rate=required_rate))
    await registry.validate(draft.package_id, draft.version, expected_revision=0)
    tested = await registry.test(
        draft.package_id,
        draft.version,
        lambda manifest: asyncio.sleep(0, result=report(passed=1, failed=0)),
        expected_revision=1,
    )

    with pytest.raises(SageV2Error) as invalid:
        await registry.publish(
            tested.package_id, tested.version, expected_revision=tested.revision
        )

    assert invalid.value.info.code == "package.test_gate_invalid"


@pytest.mark.asyncio
async def test_stale_revision_and_concurrent_update_are_rejected():
    registry = InMemoryAgentPackageRegistry()
    draft = await registry.save_draft(package())
    updated = package().model_copy(
        update={"metadata": package().metadata.model_copy(update={"name": "Updated"})}
    )
    results = await asyncio.gather(
        registry.save_draft(updated, expected_revision=draft.revision),
        registry.save_draft(updated, expected_revision=draft.revision),
        return_exceptions=True,
    )
    assert sum(not isinstance(value, Exception) for value in results) == 1
    error = next(value for value in results if isinstance(value, SageV2Error))
    assert error.info.code == "package.revision_conflict"


@pytest.mark.asyncio
async def test_content_change_invalidates_previous_validation_and_test_report():
    registry = InMemoryAgentPackageRegistry()
    draft = await registry.save_draft(package())
    await registry.validate(draft.package_id, draft.version, expected_revision=0)
    tested = await registry.test(
        draft.package_id,
        draft.version,
        lambda manifest: asyncio.sleep(0, result=report(passed=1, failed=0)),
        expected_revision=1,
    )
    changed = tested.manifest.model_copy(
        update={
            "metadata": tested.manifest.metadata.model_copy(update={"name": "Changed"})
        }
    )
    revised = await registry.save_draft(changed, expected_revision=tested.revision)
    assert revised.stage == PackageStage.DRAFT
    assert revised.test_report is None
    assert revised.manifest_hash != tested.manifest_hash


@pytest.mark.asyncio
async def test_published_package_can_only_transition_to_auditable_retired_state():
    registry = InMemoryAgentPackageRegistry()
    draft = await registry.save_draft(package())
    await registry.validate(draft.package_id, draft.version, expected_revision=0)
    tested = await registry.test(
        draft.package_id,
        draft.version,
        lambda manifest: asyncio.sleep(0, result=report(passed=1, failed=0)),
        expected_revision=1,
    )
    published = await registry.publish(
        tested.package_id, tested.version, expected_revision=tested.revision
    )

    with pytest.raises(SageV2Error) as revalidate:
        await registry.validate(
            published.package_id,
            published.version,
            expected_revision=published.revision,
        )
    assert revalidate.value.info.code == "package.version_immutable"

    retired = await registry.retire(
        published.package_id,
        published.version,
        expected_revision=published.revision,
    )
    assert retired.stage == PackageStage.RETIRED
    assert retired.retired_at is not None
    assert retired.published_at == published.published_at
    with pytest.raises(SageV2Error) as immutable:
        await registry.save_draft(retired.manifest, expected_revision=retired.revision)
    assert immutable.value.info.code == "package.version_immutable"

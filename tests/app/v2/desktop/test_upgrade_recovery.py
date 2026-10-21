"""Desktop must resume admitted work after an SDK/plugin contract upgrade."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from sagents.v2.application import SAgentApplication
    from typing import Any

from sagents.v2.contracts.events import ToolEventData

import hashlib
import json
import os
import sqlite3
from pathlib import Path

import pytest

from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.execution import ExecutionConfigurationSnapshot
from sagents.v2.runtime.execution.sandbox.plugins.local.support.interpreter import (
    inspect_isolation_python,
)
from sagents.v2.testing.plugins import ScriptedModelProvider
from tests.app.v2.desktop.sdk_fixture import completed, desktop, step


def install_legacy_approval(root: Path, *, include_revision: bool = True) -> dict[str, Any]:
    """Rebind only machine-local paths in a real HEAD~10 persisted Run."""
    source = Path(__file__).with_name("fixtures") / "legacy_approval_snapshot.json"
    fixture = json.loads(source.read_text(encoding="utf-8"))
    interpreter = inspect_isolation_python()

    def bind(value) -> Any:
        if isinstance(value, str):
            if value == "{CURRENT_INTERPRETER}":
                return interpreter
            if value == "{COMMAND_PATH}":
                return os.defpath
            return value.replace("{DATA_ROOT}", str(root))
        if isinstance(value, list):
            return [bind(item) for item in value]
        if isinstance(value, dict):
            result = {key: bind(item) for key, item in value.items()}
            if result.get("schema_version") == "sage.execution/v1":
                result["configuration_id"] = ExecutionConfigurationSnapshot.identity(
                    result
                )
            return result
        return value

    fixture = bind(fixture)
    case = fixture["case"]
    snapshot = fixture["session_snapshot"]
    unsigned = {key: value for key, value in snapshot.items() if key != "checksum"}
    encoded = json.dumps(
        unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    snapshot["checksum"] = "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()
    session_root = root / "runtime" / "sessions" / case["session_id"]
    session_root.mkdir(parents=True)
    (session_root / "state.json").write_text(json.dumps(snapshot), encoding="utf-8")
    (root / "runtime" / "desktop-catalog.json").write_text(
        json.dumps(fixture["catalog"]), encoding="utf-8"
    )
    (root / "agent_workspace").mkdir()
    with sqlite3.connect(root / "runtime" / "self-configuration.sqlite3") as db:
        db.execute(
            "CREATE TABLE runs (owner TEXT, run TEXT, data TEXT NOT NULL, PRIMARY KEY(owner, run))"
        )
        db.executemany(
            "INSERT INTO runs VALUES (?, ?, ?)",
            [
                (row["owner"], row["run"], json.dumps(row["state"]))
                for row in fixture["self_configuration_runs"]
            ],
        )
    if include_revision:
        revision = fixture["agent_revision"]
        name = hashlib.sha256(revision["spec_hash"].encode()).hexdigest() + ".json"
        revision_root = root / "runtime" / "agent-revisions"
        revision_root.mkdir()
        (revision_root / name).write_text(json.dumps(revision), encoding="utf-8")
    return case


def archived_revision_path(root: Path) -> Path:
    return next((root / "runtime" / "agent-revisions").glob("*.json"))


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["reply_interaction", "resume"])
async def test_legacy_approval_requires_the_original_owner(tmp_path, operation):
    case = install_legacy_approval(tmp_path)
    service, _, _ = desktop(tmp_path)
    try:
        await service.start()
        before = await service.session_store.get_run(case["run_id"])
        archive = archived_revision_path(tmp_path)
        original_archive = archive.read_bytes()
        with pytest.raises(SageV2Error) as rejected:
            if operation == "reply_interaction":
                await service.reply_interaction(
                    before.run_id, case["interaction_id"], "approve_once", {}, "user_2"
                )
            else:
                await service.resume(before.run_id, "user_2")
        assert rejected.value.info.code == "session.actor_not_authorized"
        assert await service.session_store.get_run(before.run_id) == before
        assert archive.read_bytes() == original_archive
        assert not (tmp_path / "agent_workspace" / "review.txt").exists()
    finally:
        await service.close()


@pytest.mark.asyncio
@pytest.mark.timeout(60)
async def test_legacy_desktop_approval_resumes_original_run_after_restart(tmp_path):
    case = install_legacy_approval(tmp_path)
    service, model, _ = desktop(
        tmp_path, model=ScriptedModelProvider((step(text="Done"),))
    )
    try:
        await service.start()
        before = await service.session_store.get_run(case["run_id"])
        original_context = await service.session_store.get_run_context(before.run_id)
        command = await service.session_store.get_start_command(before.run_id)
        suspension = await service.session_store.get_suspension(cast(str, before.suspension_id))
        interaction = await service.session_store.get_interaction(
            case["interaction_id"]
        )
        assert before.state.value == "suspended"
        assert suspension.status.value == "pending"
        assert interaction.payload["tool_name"] == "file_write"
        assert interaction.payload["arguments"] == {
            "file_path": "review.txt",
            "content": "ok",
            "session_id": case["session_id"],
        }

        await service.reply_interaction(
            before.run_id, case["interaction_id"], "approve_once", {}, "user_1"
        )
        after = await completed(service, before.run_id)

        events = await service.session_store.read_events(after.run_id)
        assert after.state.value == "completed", [
            event.model_dump(mode="json")
            for event in events
            if event.type == "run.failed"
        ]
        assert after.run_id == before.run_id
        assert after.session_id == before.session_id == case["session_id"]
        assert after.resolved_spec_hash == before.resolved_spec_hash
        assert (
            await service.session_store.get_run_context(after.run_id)
            == original_context
        )
        assert await service.session_store.get_start_command(after.run_id) == command
        assert (tmp_path / "agent_workspace" / "review.txt").read_text() == "ok"
        writes = [
            event
            for event in events
            if event.type == "tool.call.succeeded"
            and cast(ToolEventData, event.data).tool_name == "file_write"
        ]
        assert len(writes) == 1
        assert len(model.requests) == 1
    finally:
        await service.close()

    # A migrated revision must also be readable on a subsequent process restart.
    restarted, _, _ = desktop(tmp_path)
    try:
        await restarted.start()
        loaded = await cast('SAgentApplication', restarted.application).agent_for_run(
            case["run_id"], restarted._context("user_1")
        )
        assert loaded.composition_hash == before.resolved_spec_hash
        assert (
            await restarted.session_store.get_run(case["run_id"])
        ).state.value == "completed"
    finally:
        await restarted.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["reply_interaction", "resume"])
async def test_unavailable_agent_revision_keeps_approval_pending(tmp_path, operation):
    case = install_legacy_approval(tmp_path, include_revision=False)
    service, _, _ = desktop(tmp_path)
    try:
        await service.start()
        before = await service.session_store.get_run(case["run_id"])
        suspension = await service.session_store.get_suspension(cast(str, before.suspension_id))
        interaction = await service.session_store.get_interaction(
            case["interaction_id"]
        )
        events = await service.session_store.read_events(before.run_id)

        with pytest.raises(ValueError, match="admitted Agent revision is unavailable"):
            if operation == "reply_interaction":
                await service.reply_interaction(
                    before.run_id, case["interaction_id"], "approve_once", {}, "user_1"
                )
            else:
                await service.resume(before.run_id, "user_1")

        after = await service.session_store.get_run(before.run_id)
        assert after == before
        assert after.state.value == "suspended"
        assert (
            await service.session_store.get_suspension(cast(str, before.suspension_id))
            == suspension
        )
        assert (
            await service.session_store.get_interaction(case["interaction_id"])
            == interaction
        )
        assert await service.session_store.read_events(before.run_id) == events
    finally:
        await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("capability", "plugin", "message"),
    [
        (
            "context.unit-compactor",
            "test.custom-compactor",
            "custom archived context compactor",
        ),
        (
            "observability.log-sink",
            "test.custom-log-sink",
            "custom archived observation sink",
        ),
        (
            "observability.diagnostic-sink",
            "test.custom-diagnostic-sink",
            "custom archived observation sink",
        ),
        (
            "observability.trace-sink",
            "test.custom-trace-sink",
            "custom archived observation sink",
        ),
    ],
)
async def test_custom_legacy_provider_is_not_silently_replaced_during_approval(
    tmp_path, capability, plugin, message
):
    case = install_legacy_approval(tmp_path)
    archive = archived_revision_path(tmp_path)
    raw = json.loads(archive.read_text(encoding="utf-8"))
    raw["package"]["runtime"]["capabilities"][capability] = {
        "plugin": plugin,
        "scope": "process",
        "config": {},
    }
    archive.write_text(json.dumps(raw), encoding="utf-8")
    archived_before = archive.read_bytes()
    service, _, _ = desktop(tmp_path)
    try:
        await service.start()
        before = await service.session_store.get_run(case["run_id"])
        command = await service.session_store.get_start_command(before.run_id)
        interaction = await service.session_store.get_interaction(
            case["interaction_id"]
        )
        suspension = await service.session_store.get_suspension(cast(str, before.suspension_id))

        with pytest.raises(ValueError, match=message):
            await service.reply_interaction(
                before.run_id, case["interaction_id"], "approve_once", {}, "user_1"
            )

        assert (
            await service.session_store.get_run(before.run_id)
        ).state.value == "suspended"
        assert await service.session_store.get_run(before.run_id) == before
        assert await service.session_store.get_start_command(before.run_id) == command
        assert (
            await service.session_store.get_interaction(case["interaction_id"])
            == interaction
        )
        assert (
            await service.session_store.get_suspension(cast(str, before.suspension_id))
            == suspension
        )
        assert archive.read_bytes() == archived_before
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_migrated_archive_still_checks_assembly_hash_on_next_restart(tmp_path):
    case = install_legacy_approval(tmp_path)
    service, _, _ = desktop(tmp_path)
    try:
        await service.start()
        run = await service.session_store.get_run(case["run_id"])
        command = await service.session_store.get_start_command(run.run_id)
        loaded = await cast('SAgentApplication', service.application).agent_for_run(
            run.run_id, service._context("user_1")
        )
        assert loaded.composition_hash == run.resolved_spec_hash
    finally:
        await service.close()

    archive = archived_revision_path(tmp_path)
    raw = json.loads(archive.read_text(encoding="utf-8"))
    assert raw["spec_hash"] == run.resolved_spec_hash
    assert raw["recovery"]["version"] == 1
    assert raw["recovery"]["assembly_hash"].startswith("sha256:")
    raw["recovery"]["assembly_hash"] = "sha256:" + "0" * 64
    archive.write_text(json.dumps(raw), encoding="utf-8")
    tampered = archive.read_bytes()

    restarted, _, _ = desktop(tmp_path)
    try:
        await restarted.start()
        with pytest.raises(
            ValueError, match="no longer matches the runtime composition"
        ):
            await cast('SAgentApplication', restarted.application).agent_for_run(
                run.run_id, restarted._context("user_1")
            )
        assert await restarted.session_store.get_run(run.run_id) == run
        assert await restarted.session_store.get_start_command(run.run_id) == command
        assert archive.read_bytes() == tampered
    finally:
        await restarted.close()

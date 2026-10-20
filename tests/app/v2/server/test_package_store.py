import asyncio

import pytest
from sqlalchemy import event

from app.v2.server.database import Database, DatabaseSettings
from app.v2.server.database.schema import create_host_schema
from app.v2.server.packages.repository import DatabasePackageStore
from sagents.v2.agent.management import AgentPackageBundle
from sagents.v2.package.presets import BuiltinPackageFactory


@pytest.mark.asyncio
async def test_database_package_cas_handles_archives_and_reopen(tmp_path):
    db = Database(DatabaseSettings(url=f"sqlite+aiosqlite:///{tmp_path}/store.db"))
    await db.start()
    await create_host_schema(db)
    store = DatabasePackageStore(db)
    bundle = AgentPackageBundle(
        manifest=BuiltinPackageFactory.create(
            "assistant", package_id="test.package",
        )
    )
    try:
        ref = await store.save("owner", bundle)
        assert (
            await store.version_ref(
                "owner", bundle.manifest.metadata.id, bundle.manifest.metadata.version
            )
            == ref
        )
        outcomes = await asyncio.gather(
            store.activate("owner", ref, None),
            store.activate("owner", ref, None),
            return_exceptions=True,
        )
        assert sum(isinstance(item, ValueError) for item in outcomes) == 1
        assert (await store.list("owner"))[0]["active"]
        handle = {"run_id": "r", "session_id": "s"}
        await store.invocation("owner", "operation", ref, "assistant", "hello")
        await store.invocation("owner", "operation", handle=handle)
        assert await store.owns_session("owner", ref, "assistant", "s")
        assert not await store.owns_session("other", ref, "assistant", "s")
        assert len(await store.unarchived_invocations("owner", ref, "assistant")) == 1
        value = dict(operation="operation", ref=ref, terminal=True, run={"run_id": "r"})
        assert await store.terminal_status("owner", "operation", value=value) == value
        assert await store.unarchived_invocations("owner", ref, "assistant") == []
        assert len(await store.list_invocations("owner")) == 1
        with pytest.raises(ValueError):
            await store.invocation("owner", "operation", ref, "assistant", "changed")
        with pytest.raises(ValueError):
            await store.get("other", ref)
        assert await store.reply_command(
            "owner", "operation", "question", "answer", {"revision": 1}
        ) == {"revision": 1}
        await store.discard_stale_reply(
            "owner", "operation", "question", "answer", {"revision": 2}
        )
        assert await store.reply_command(
            "owner", "operation", "question", "answer"
        ) == {"revision": 1}
        await store.discard_stale_reply(
            "owner", "operation", "question", "answer", {"revision": 1}
        )
        assert (
            await store.reply_command("owner", "operation", "question", "answer")
            is None
        )
        reopened = DatabasePackageStore(db)
        assert await reopened.terminal_status("owner", "operation") == value
        assert await reopened.get("owner", ref) == bundle
    finally:
        await db.stop()


@pytest.fixture
async def package_store(tmp_path):
    db = Database(DatabaseSettings(url=f"sqlite+aiosqlite:///{tmp_path}/packages.db"))
    await db.start()
    await create_host_schema(db)
    try:
        yield DatabasePackageStore(db)
    finally:
        await db.stop()


async def test_package_inventory_batches_active_versions_in_two_selects(package_store):
    store = package_store
    expected = {}
    for index in range(25):
        package = f"test.package-{index:02d}"
        refs = []
        for version in ("0.1.0", "0.2.0"):
            manifest = BuiltinPackageFactory.create("assistant", package_id=package)
            manifest = manifest.model_copy(update={
                "metadata": manifest.metadata.model_copy(update={"version": version}),
            })
            bundle = AgentPackageBundle(manifest=manifest)
            refs.append(await store.save("owner", bundle))
        if index % 2 == 0:
            await store.activate("owner", refs[0], None)
        for ref in refs:
            active_ref = refs[0] if index % 2 == 0 else None
            expected[ref] = (ref == active_ref, active_ref)
    foreign = AgentPackageBundle(
        manifest=BuiltinPackageFactory.create("assistant", package_id="foreign.package")
    )
    foreign_ref = await store.save("other-owner", foreign)
    await store.activate("other-owner", foreign_ref, None)

    statements = []
    async with store.database.session() as session:
        engine = session.bind.sync_engine

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        rows = await store.list("owner", limit=50)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(rows) == 50
    assert {row["ref"]: (row["active"], row["active_ref"]) for row in rows} == expected
    assert len(statements) <= 2, f"50 inventory items issued {len(statements)} SELECTs"


@pytest.mark.parametrize("query", [
    "version_ref", "get", "list", "invocation", "reply_command", "owns_session",
    "terminal_status", "unarchived_invocations", "history_location", "list_invocations",
])
async def test_package_reads_do_not_wait_for_same_store_write_lock(package_store, query):
    store = package_store
    bundle = AgentPackageBundle(
        manifest=BuiltinPackageFactory.create("assistant", package_id="test.package")
    )
    ref = await store.save("owner", bundle)
    handle = {"run_id": "run", "session_id": "session"}
    await store.invocation("owner", "operation", ref, "assistant", "hello", handle)
    command = {"revision": 1}
    await store.reply_command("owner", "operation", "interaction", "request", command)
    terminal = dict(operation="operation", ref=ref, terminal=True, run={"run_id": "run"})
    await store.terminal_status("owner", "operation", value=terminal)
    await store.history_location("owner", ref, "assistant", root="/test/history")
    queries = {
        "version_ref": lambda: store.version_ref("owner", "test.package", "0.1.0"),
        "get": lambda: store.get("owner", ref),
        "list": lambda: store.list("owner"),
        "invocation": lambda: store.invocation("owner", "operation"),
        "reply_command": lambda: store.reply_command("owner", "operation", "interaction", "request"),
        "owns_session": lambda: store.owns_session("owner", ref, "assistant", "session"),
        "terminal_status": lambda: store.terminal_status("owner", "operation"),
        "unarchived_invocations": lambda: store.unarchived_invocations("owner", ref, "assistant"),
        "history_location": lambda: store.history_location("owner", ref, "assistant"),
        "list_invocations": lambda: store.list_invocations("owner"),
    }
    expected = await queries[query]()
    entered = asyncio.Event()

    async def read():
        entered.set()
        return await queries[query]()

    # Enter the real writer boundary, without taking a database write lock.
    # The read must finish while this same store's writer is still occupied.
    async with store.transaction():
        task = asyncio.create_task(read())
        await asyncio.wait_for(entered.wait(), timeout=1)
        assert await asyncio.wait_for(task, timeout=0.5) == expected


@pytest.mark.parametrize("operation", [
    "invocation", "reply_command", "terminal_status", "history_location",
])
async def test_package_optional_writes_still_wait_for_same_store_write_lock(
    package_store, operation,
):
    store = package_store
    bundle = AgentPackageBundle(
        manifest=BuiltinPackageFactory.create("assistant", package_id="test.package")
    )
    ref = await store.save("owner", bundle)
    handle = {"run_id": "run", "session_id": "session"}
    await store.invocation("owner", "operation", ref, "assistant", "hello", handle)
    terminal = dict(operation="operation", ref=ref, terminal=True, run={"run_id": "run"})
    writes = {
        "invocation": lambda: store.invocation("owner", "operation", handle=handle),
        "reply_command": lambda: store.reply_command(
            "owner", "operation", "interaction", "request", {"revision": 1},
        ),
        "terminal_status": lambda: store.terminal_status("owner", "operation", value=terminal),
        "history_location": lambda: store.history_location("owner", ref, "assistant", root="/history"),
    }
    reads = {
        "invocation": lambda: store.invocation("owner", "operation"),
        "reply_command": lambda: store.reply_command("owner", "operation", "interaction", "request"),
        "terminal_status": lambda: store.terminal_status("owner", "operation"),
        "history_location": lambda: store.history_location("owner", ref, "assistant"),
    }
    entered = asyncio.Event()

    async def write():
        entered.set()
        return await writes[operation]()

    task = None
    try:
        async with store.transaction():
            task = asyncio.create_task(write())
            await asyncio.wait_for(entered.wait(), timeout=1)
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(task), timeout=0.05)
        result = await asyncio.wait_for(task, timeout=1)
        assert result == await reads[operation]()
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

import asyncio

import pytest

from app.server_v2.core.database import Database, DatabaseSettings
from app.server_v2.db.models import create_host_schema
from app.server_v2.repositories.packages import DatabasePackageStore
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
            "assistant", package_id="test.package", model="default"
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

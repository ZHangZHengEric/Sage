"""MySQL start-key collisions preserve the public conflict contract."""

from unittest.mock import AsyncMock

import pytest

from sagents.v2.contracts.errors import ConflictError
from sagents.v2.runtime.session.plugins.mysql.state import _MysqlSessionState


@pytest.mark.asyncio
@pytest.mark.parametrize("errno", [1062, 1452])
async def test_start_key_integrity_error_is_only_translated_for_duplicates(errno):
    aiomysql = pytest.importorskip("aiomysql")
    store = _MysqlSessionState("mysql://user:password@localhost/test")
    error = aiomysql.IntegrityError(errno, "integrity failure")
    cursor = AsyncMock()
    cursor.executemany.side_effect = error
    row = ("tenant", "principal", "key", "session", "run", "digest")
    expected = ConflictError if errno == 1062 else aiomysql.IntegrityError
    with pytest.raises(expected) as caught:
        await store._sync_start_idempotency(cursor, "session", {row})
    if errno == 1062:
        assert caught.value.info.code == "session.revision_conflict"
        assert caught.value.__cause__ is error
    else:
        assert caught.value is error

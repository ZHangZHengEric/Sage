import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.v2.server.catalog.records import AgentRecord
from app.v2.server.catalog.repository import DatabaseCatalogStore
from app.v2.server.database import Database, DatabaseSettings
from app.v2.server.database.schema import create_host_schema
from app.v2.server.identity.orm import UserRow
from sagents.v2.contracts.common import new_id
from sagents.v2.contracts.errors import SageV2Error


@pytest.fixture
async def store(tmp_path):
    db = Database(DatabaseSettings(url=f'sqlite+aiosqlite:///{tmp_path}/agents.db'))
    await db.start()
    await create_host_schema(db)
    async with db.transaction() as session:
        for owner in ('alice', 'bob'):
            session.add(UserRow(user_id=owner, username=owner, password_hash='test', role='user'))
    try:
        yield DatabaseCatalogStore(db)
    finally:
        await db.stop()


async def test_defaults_are_persistent_globally_unique_and_owned(store):
    alice = await store.get('alice')
    bob = await store.get('bob')
    assert alice.default_agent_id != bob.default_agent_id
    assert (await store.get('alice')).default_agent_id == alice.default_agent_id
    assert await store.agent_owner(alice.default_agent_id) == 'alice'
    assert await store.agent_owner('missing') is None
    with pytest.raises(SageV2Error):
        await store.update_agent('bob', alice.agents[0])
    with pytest.raises(SageV2Error):
        await store.delete_agent('bob', alice.default_agent_id)
    with pytest.raises(IntegrityError):
        await store.create_agent('bob', alice.agents[0])
    assert (await store.get('alice')).agents == alice.agents


async def test_single_agent_update_does_not_replace_other_agents_or_default(store):
    catalog = await store.get('alice')
    first = AgentRecord(id=new_id('agent'), name='First')
    second = AgentRecord(id=new_id('agent'), name='Second')
    await store.create_agent('alice', first)
    await store.create_agent('alice', second)
    await store.update_agent('alice', first.model_copy(update={'name': 'Updated'}))
    current = await store.get('alice')
    assert {a.name for a in current.agents} == {'Main Assistant', 'Updated', 'Second'}
    assert current.default_agent_id == catalog.default_agent_id
    await store.delete_agent('alice', current.default_agent_id)
    current = await store.get('alice')
    assert current.default_agent_id in {first.id, second.id}
    await store.delete_agent('alice', second.id)
    with pytest.raises(SageV2Error):
        await store.delete_agent('alice', first.id)


async def test_agent_json_is_not_part_of_catalog_schema(store):
    from app.v2.server.catalog.orm import CatalogRow
    assert 'agents' not in CatalogRow.__table__.columns
    await store.get('alice')
    async with store.database.session() as session:
        assert (await session.scalar(select(CatalogRow))).default_agent_id.startswith('agent_')

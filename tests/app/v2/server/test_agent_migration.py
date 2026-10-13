import json

from sqlalchemy import create_engine, text, inspect

from app.v2.server.database.base import Base
from app.v2.server.database.migrations.agents import prepare, migrate, finalize
from app.v2.server.database import schema as _schema  # noqa: F401


def test_migration_preserves_config_and_rekeys_owned_references(tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path}/legacy.db')
    with engine.begin() as c:
        Base.metadata.create_all(c)
        c.execute(text('DROP TABLE agents'))
        c.execute(text('DROP TABLE catalogs'))
        c.execute(text('CREATE TABLE catalogs (user_id VARCHAR(64) PRIMARY KEY, agents JSON NOT NULL, models JSON NOT NULL, mcp_servers JSON NOT NULL, a2a_agents JSON NOT NULL)'))
        for user in ['alice', 'bob']:
            c.execute(text("INSERT INTO users VALUES (:u, :u, 'hash', 'user', '{}')"), {'u': user})
            c.execute(text("INSERT INTO catalogs VALUES (:u, :a, '[]', '[]', '[]')"),
                      {'u': user, 'a': json.dumps([{'id': 'main', 'name': user, 'instructions': 'Keep this', 'skills': ['demo']}])})
            c.execute(text("INSERT INTO threads VALUES (:u, :u, 'thread', 'main', 'now')"), {'u': user})
        c.execute(text('CREATE TABLE sessions (session_id VARCHAR(128) PRIMARY KEY, compact_state JSON NOT NULL)'))
        c.execute(text('CREATE TABLE session_mutations (session_id VARCHAR(128))'))
        state = {'runs': [{'state': 'completed', 'request_context': {'actor': {'principal_id': 'alice'}},
                          'start_command': {'agent_id': 'main', 'config': {'metadata': {'server_v2.composition': {'agent': {'id': 'main'}}, 'server_v2.execution': {'agent_id': 'main'}}}}}],
                 'messages': [{'text': 'main'}]}
        c.execute(text('INSERT INTO sessions VALUES (:s, :j)'), {'s': 'session', 'j': json.dumps(state)})
    with engine.begin() as c:
        assert prepare(c)
    with engine.begin() as c:
        report = migrate(c)
        assert report['agents'] == 2
    with engine.begin() as c:
        finalize(c)
        agents = c.execute(text('SELECT id, owner_user_id, instructions FROM agents')).all()
        assert len({a.id for a in agents}) == 2
        assert all(a.instructions == 'Keep this' for a in agents)
        assert 'agents' not in {col['name'] for col in inspect(c).get_columns('catalogs')}
        for aid, owner, _ in agents:
            assert c.execute(text('SELECT agent_id FROM threads WHERE user_id=:u'), {'u': owner}).scalar_one() == aid
            assert c.execute(text('SELECT agent_id FROM agent_skill_selections WHERE owner_user_id=:u'), {'u': owner}).scalar_one() == aid
        saved = json.loads(c.execute(text('SELECT compact_state FROM sessions')).scalar_one())
        alice_id = next(a.id for a in agents if a.owner_user_id == 'alice')
        assert saved['runs'][0]['start_command']['agent_id'] == alice_id
        assert saved['messages'] == [{'text': 'main'}]
        assert not prepare(c)

"""Explicit one-time migration from per-user Agent JSON to global Agent rows.

Run with the Server v2 writers stopped. No migration history/audit table is added.
The caller backs up the database before invoking this migration.
"""
from __future__ import annotations

import json
from copy import deepcopy

from sqlalchemy import MetaData, Table, inspect, select, text, update

from app.v2.server.catalog.orm import AgentRow, CatalogRow
from app.v2.server.catalog.records import AgentRecord, empty_catalog
from sagents.v2.contracts.common import new_id


def _decode(value):
    return json.loads(value) if isinstance(value, str) else value


def prepare(connection) -> bool:
    columns = {c['name'] for c in inspect(connection).get_columns('catalogs')}
    if 'agents' not in columns:
        return False
    AgentRow.__table__.create(connection, checkfirst=True)
    if 'default_agent_id' not in columns:
        connection.execute(text("ALTER TABLE catalogs ADD COLUMN default_agent_id VARCHAR(64) NOT NULL DEFAULT ''"))
    return True


def migrate(connection) -> dict:
    """All data changes run in one transaction after the DDL preparation."""
    metadata = MetaData()
    tables = {name: Table(name, metadata, autoload_with=connection)
              for name in inspect(connection).get_table_names()}
    users = connection.execute(select(tables['users']).with_for_update()).mappings().all()
    catalogs = {r['user_id']: r for r in connection.execute(
        select(tables['catalogs']).with_for_update()).mappings()}
    mapping = {}
    defaults = {}
    agents = []
    for user in users:
        uid = user['user_id']
        catalog = catalogs.get(uid)
        if catalog and catalog['default_agent_id']:
            raise ValueError('Agent migration already committed; verify and finalize instead')
        old = _decode(catalog['agents']) if catalog else []
        old = old or [a.model_dump(mode='json') for a in empty_catalog().agents]
        seen = set()
        for value in old:
            record = AgentRecord.model_validate(value)
            if record.id in seen:
                raise ValueError('duplicate agent id within a user catalog')
            seen.add(record.id)
            new = new_id('agent')
            mapping[(uid, record.id)] = new
            agents.append(dict(id=new, owner_user_id=uid,
                               **record.model_dump(mode='json', exclude={'id', 'skills'})))
            if uid not in defaults or record.id == 'main':
                defaults[uid] = new
        if catalog is None:
            connection.execute(tables['catalogs'].insert().values(
                user_id=uid, agents=[], default_agent_id='',
                models=[], mcp_servers=[], a2a_agents=[]))
    if len(catalogs.keys() - {u['user_id'] for u in users}):
        raise ValueError('catalog without owner')
    connection.execute(AgentRow.__table__.insert(), agents)
    for uid, default in defaults.items():
        connection.execute(update(CatalogRow).where(CatalogRow.user_id == uid).values(default_agent_id=default))
    changed = {}
    for name, owner_column in [('threads', 'user_id'), ('api_keys', 'owner_user_id'),
                               ('agent_skill_selections', 'owner_user_id')]:
        table = tables[name]
        count = 0
        for row in connection.execute(select(table).with_for_update()).mappings():
            uid, old = row[owner_column], row['agent_id']
            if not old and name == 'api_keys':
                continue  # An unscoped key remains unscoped.
            new = defaults.get(uid) if not old else mapping.get((uid, old))
            if new is None:
                raise ValueError(f'unresolved agent reference in {name}')
            predicate = [table.c[col.name] == row[col.name] for col in table.primary_key]
            connection.execute(table.update().where(*predicate).values(agent_id=new))
            count += 1
        changed[name] = count
    # Skill bindings stored in an old Agent document also become independent rows.
    bindings = tables['agent_skill_selections']
    for uid, catalog in catalogs.items():
        for agent in _decode(catalog['agents']) or []:
            aid = mapping[(uid, agent['id'])]
            current = set(connection.execute(select(bindings.c.skill_name).where(
                bindings.c.owner_user_id == uid, bindings.c.agent_id == aid)).scalars())
            for position, skill in enumerate(agent.get('skills', [])):
                if skill not in current:
                    connection.execute(bindings.insert().values(owner_user_id=uid, agent_id=aid,
                        skill_name=skill, source_skill_id='', position=position))
                    current.add(skill)
    if 'sessions' in tables:
        # Journalled or external sessions need a dedicated replay migration, not
        # an unsafe recursive string replacement inside user messages/tool data.
        if connection.execute(select(tables['session_mutations'].c.session_id).limit(1)).first():
            raise ValueError('journalled sessions require replay migration before changing Agent IDs')
        table = tables['sessions']
        count = 0
        for row in connection.execute(select(table).with_for_update()).mappings():
            state = deepcopy(_decode(row['compact_state']))
            for run in state.get('runs', []):
                if run['state'] not in {'completed', 'failed', 'cancelled', 'rejected'}:
                    raise ValueError('stop/finish active runs before migrating Agent IDs')
                command = run['start_command']
                uid = run['request_context']['actor']['principal_id']
                aid = mapping.get((uid, command['agent_id']))
                if aid is None:
                    raise ValueError('unresolved session Agent reference')
                config = command.get('config', {}).get('metadata', {})
                if 'server_v2.external.request_id' in config:
                    raise ValueError('external sessions require external identity migration')
                command['agent_id'] = aid
                composition = config.get('server_v2.composition', {})
                if composition.get('agent'):
                    composition['agent']['id'] = aid
                policy = config.get('server_v2.execution')
                if isinstance(policy, dict):
                    policy['agent_id'] = aid
            connection.execute(table.update().where(table.c.session_id == row['session_id']).values(compact_state=state))
            count += 1
        changed['sessions'] = count
    return {'agents': len(agents), 'owners': len(defaults), 'references': changed}


def finalize(connection) -> None:
    missing = connection.execute(text('''SELECT COUNT(*) FROM catalogs c LEFT JOIN agents a
        ON c.default_agent_id=a.id AND c.user_id=a.owner_user_id WHERE a.id IS NULL''')).scalar_one()
    if missing:
        raise ValueError('invalid default Agent references')
    if 'agents' in {c['name'] for c in inspect(connection).get_columns('catalogs')}:
        connection.execute(text('ALTER TABLE catalogs DROP COLUMN agents'))

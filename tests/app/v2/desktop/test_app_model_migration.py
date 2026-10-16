"""Desktop migration backs up every changed source and retains Run snapshots."""
import json
import sqlite3

from scripts.v2.migrate_desktop_app_models import migrate
from sagents.v2.agent.management import AgentPackageBundle


def test_desktop_backup_migration_and_second_run_are_safe(tmp_path):
    package = {"manifest": {"schema_version": "sage/v2", "metadata": {"id": "agent", "version": "1", "name": "Agent"},
               "credentials": {"desktop_model": {"source": "host", "ref": "llm-provider:configured-model"}},
               "models": {"primary": {"provider": "openai-responses", "model": "actual-model", "credential": "desktop_model",
                                     "request": {"reasoning_effort": "high"}}},
               "agents": {"main": {"name": "Agent", "instructions": {"inline": "Help"}, "models": {"primary": "primary"}}},
               "entrypoint": {"agent": "main"}}, "files": {}}
    value = {"resolved_spec_hash": "admitted-original", "package": package,
             "providers": {"configured-model": {"request": {"reasoning_effort": "high"}}}}
    source = tmp_path / "command.json"
    source.write_text(json.dumps(value))
    before = source.read_bytes()
    db = tmp_path / "rsi.sqlite3"
    with sqlite3.connect(db) as connection:
        connection.execute('CREATE TABLE records (id TEXT PRIMARY KEY,body TEXT,summary TEXT)')
        connection.execute('INSERT INTO records VALUES (?,?,?)', ("version", json.dumps(value), '{}'))
    assert migrate(tmp_path) == {"files": 1, "records": 1, "applied": False}
    assert source.read_bytes() == before
    result = migrate(tmp_path, apply=True)
    from pathlib import Path
    assert (Path(result["backup"]) / "command.json").read_bytes() == before
    updated = json.loads(source.read_text())
    bundle = AgentPackageBundle.model_validate(updated["package"])
    assert bundle.manifest.agents["main"].models == {"primary": "configured-model"}
    assert updated["resolved_spec_hash"] == value["resolved_spec_hash"]
    assert updated["providers"] == value["providers"]
    assert migrate(tmp_path) == {"files": 0, "records": 0, "applied": False}

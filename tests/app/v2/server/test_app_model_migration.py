"""Offline migration must preserve admission identities and rekey Packages."""
from copy import deepcopy

import pytest

from scripts.v2.migrate_app_models import migrate_document, plan_rows, replace_references
from sagents.v2.agent.management import AgentPackageBundle


def old_package():
    return {"manifest": {"schema_version": "sage/v2", "metadata": {"id": "agent", "version": "1", "name": "Agent"},
                         "models": {"primary": {"provider": "server", "model": "model-1"}}, "credentials": {},
                         "agents": {"main": {"name": "Agent", "instructions": {"inline": "Help"}, "models": {"primary": "primary"}}},
                         "entrypoint": {"agent": "main"}}, "files": {}}


def test_migration_rekeys_bundle_and_keeps_admitted_hashes():
    bundle = old_package()
    frozen = {"resolved_spec_hash": "original-run-hash", "server_v2.composition": {"package": bundle}, "package_ref": "stored-old-ref"}
    rows = [{"table": "managed_agent_records", "kind": "bundle", "ref": "stored-old-ref", "value": bundle},
            {"table": "sessions", "value": frozen}]
    before = deepcopy(rows)
    planned, references = plan_rows(rows)
    assert rows == before
    package = AgentPackageBundle.model_validate(planned[0]["after"])
    assert package.manifest.agents["main"].models == {"primary": "model-1"}
    assert references["stored-old-ref"] == package.content_hash
    assert planned[1]["after"]["package_ref"] == package.content_hash
    assert planned[1]["after"]["resolved_spec_hash"] == "original-run-hash"
    assert migrate_document(package.model_dump(mode="json")) == package.model_dump(mode="json")


@pytest.mark.parametrize("change", [{"credential": "key"}, {"request": {"temperature": 0.5}}, {"provider": "openai-responses"}])
def test_unknown_model_customizations_abort_instead_of_losing_configuration(change):
    bundle = old_package()
    bundle["manifest"]["models"]["primary"].update(change)
    with pytest.raises(ValueError, match="explicit migration"):
        migrate_document(bundle)


def test_reference_replacement_cannot_rewrite_run_identity():
    assert replace_references({"ref": "old", "manifest_hash": "old", "resolved_spec_hash": "old"}, {"old": "new"}) == {
        "ref": "new", "manifest_hash": "old", "resolved_spec_hash": "old"}

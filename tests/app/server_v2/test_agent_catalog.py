from app.server_v2.domain.catalog import (
    empty_catalog,
    require_agent,
    upsert_agent,
    upsert_mcp,
)


def test_empty_catalog_has_main_agent():
    catalog = empty_catalog()
    assert require_agent(catalog, None).id == "main"
    assert require_agent(catalog, "main").instructions


def test_upsert_agent_keeps_skill_bindings():
    catalog = empty_catalog()
    catalog.agents[0] = catalog.agents[0].model_copy(update={"skills": ["demo"]})
    record, catalog = upsert_agent(
        catalog,
        {"id": "main", "name": "Writer", "instructions": "Write briefly."},
    )
    assert record.name == "Writer"
    assert record.instructions == "Write briefly."
    assert record.skills == ["demo"]


def test_upsert_mcp_stdio():
    catalog = empty_catalog()
    record, catalog = upsert_mcp(
        catalog,
        {"name": "files", "protocol": "stdio", "command": "npx", "args": ["-y", "demo"]},
    )
    assert record.name == "files"
    assert [item.name for item in catalog.mcp_servers] == ["files"]

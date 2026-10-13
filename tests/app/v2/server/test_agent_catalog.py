from app.v2.server.catalog.records import (
    empty_catalog,
    require_agent,
    upsert_agent,
    upsert_mcp,
)


def test_empty_catalog_has_unique_default_agent():
    catalog = empty_catalog()
    assert require_agent(catalog, None).id == catalog.default_agent_id
    assert catalog.default_agent_id != empty_catalog().default_agent_id
    assert require_agent(catalog, catalog.default_agent_id).instructions


def test_upsert_agent_keeps_skill_bindings():
    catalog = empty_catalog()
    catalog.agents[0] = catalog.agents[0].model_copy(update={"skills": ["demo"]})
    record, catalog = upsert_agent(
        catalog,
        {"id": catalog.default_agent_id, "name": "Writer", "instructions": "Write briefly."},
    )
    assert record.name == "Writer"
    assert record.instructions == "Write briefly."
    assert record.skills == ["demo"]


def test_upsert_mcp_streamable_http():
    catalog = empty_catalog()
    record, catalog = upsert_mcp(
        catalog,
        {
            "name": "files",
            "protocol": "streamable_http",
            "url": "https://mcp.example.com/files",
        },
    )
    assert record.name == "files"
    assert [item.name for item in catalog.mcp_servers] == ["files"]

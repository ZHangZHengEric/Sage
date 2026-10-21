"""HTTP query behavior is independent of observation backend classes and paths."""

from sagents.v2.runtime.observability import ObservabilityProvider
from tests.app.v2.server.test_admin import admin_login


def test_custom_queries_serve_performance_and_traces(client, service, monkeypatch):
    class Queries:
        available = True

        async def report(self, **options):
            return {"summary": {"requests": 7}, "agent_id": options["agent_id"]}

        async def summary(self, **options):
            return {"requests": 7, "session_id": options["session_id"]}

        async def spans(self, **options):
            return {"items": [], "next_cursor": options.get("cursor")}

        async def span(self, span_id):
            return None

    query = Queries()
    monkeypatch.setattr(
        service,
        "observability",
        ObservabilityProvider(
            plugin_id="test.custom",
            performance_query=query,
            trace_query=query,
        ),
    )
    assert client.get("/api/observability/performance").status_code == 401
    admin = {"Authorization": f"Bearer {admin_login(client)}"}
    report = client.get(
        "/api/observability/performance", params={"agent_id": "agent"}, headers=admin
    )
    assert report.status_code == 200
    assert report.json()["data"] == {"summary": {"requests": 7}, "agent_id": "agent"}
    summary = client.get(
        "/api/observability/traces/summary",
        params={"session_id": "session"},
        headers=admin,
    )
    assert summary.json()["data"] == {"requests": 7, "session_id": "session"}
    page = client.get(
        "/api/observability/trace-spans", params={"cursor": "next"}, headers=admin
    )
    assert page.json()["data"] == {"items": [], "next_cursor": "next"}
    missing = client.get("/api/observability/trace-spans/" + "a" * 16, headers=admin)
    assert missing.status_code == 404

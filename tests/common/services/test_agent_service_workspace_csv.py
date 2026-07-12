import asyncio
import csv
import hashlib
from io import StringIO
from pathlib import Path

import pytest
from starlette.requests import Request

from app.server.routers import agent as server_agent_router
from common.core import config
from common.core.exceptions import SageHTTPException
from common.schemas.agent import FileWorkspaceCsvMutationOperation
from common.services import agent_service


def _build_cfg(tmp_path: Path) -> config.StartupConfig:
    root = tmp_path / "sage"
    cfg = config.StartupConfig(
        app_mode="server",
        logs_dir=str(root / "logs"),
        session_dir=str(root / "sessions"),
        agents_dir=str(root / "agents"),
        skill_dir=str(root / "skills"),
        user_dir=str(root / "users"),
    )
    Path(cfg.agents_dir).mkdir(parents=True, exist_ok=True)
    return cfg


def _request() -> Request:
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    request.state.user_claims = {"userid": "user_a", "role": "user"}
    return request


def _mutation(operation: str, key: str, *, value: str = "") -> dict:
    return {
        "operation": operation,
        "row_key": key,
        "values": {"key": key, "value": value} if operation != "delete" else {},
    }


def test_mutate_workspace_csv_is_sorted_escaped_and_idempotent(tmp_path):
    workspace = tmp_path / "workspace"
    result = agent_service.mutate_workspace_csv(
        workspace,
        path="user_health_data/demo/2026-07.csv",
        header=["key", "value"],
        row_key_columns=["key"],
        sort_columns=["key"],
        operations=[
            _mutation("append", "b", value='comma,quote"'),
            _mutation("append", "a", value="first"),
        ],
    )

    path = workspace / "user_health_data" / "demo" / "2026-07.csv"
    content = path.read_bytes()
    assert result["row_count"] == 2
    assert result["content_hash"] == hashlib.sha256(content).hexdigest()
    assert list(csv.DictReader(StringIO(content.decode("utf-8")))) == [
        {"key": "a", "value": "first"},
        {"key": "b", "value": 'comma,quote"'},
    ]

    repeated = agent_service.mutate_workspace_csv(
        workspace,
        path="user_health_data/demo/2026-07.csv",
        header=["key", "value"],
        row_key_columns=["key"],
        sort_columns=["key"],
        operations=[_mutation("append", "a", value="first")],
        expected_content_hash=result["content_hash"],
    )
    assert repeated["operations"]["noop"] == 1
    assert path.read_bytes() == content


def test_mutate_workspace_csv_upserts_and_deletes_empty_partition(tmp_path):
    workspace = tmp_path / "workspace"
    common = {
        "path": "user_health_data/demo/2026-07.csv",
        "header": ["key", "value"],
        "row_key_columns": ["key"],
        "sort_columns": ["key"],
    }
    agent_service.mutate_workspace_csv(
        workspace,
        **common,
        operations=[_mutation("append", "a", value="old")],
    )
    updated = agent_service.mutate_workspace_csv(
        workspace,
        **common,
        operations=[_mutation("upsert", "a", value="new")],
    )
    assert updated["operations"]["upsert"] == 1
    deleted = agent_service.mutate_workspace_csv(
        workspace,
        **common,
        operations=[_mutation("delete", "a")],
    )
    assert deleted["deleted"] is True
    assert not (workspace / common["path"]).exists()


def test_mutate_workspace_csv_rejects_conflicts_and_unsafe_paths(tmp_path):
    workspace = tmp_path / "workspace"
    with pytest.raises(SageHTTPException):
        agent_service.mutate_workspace_csv(
            workspace,
            path="../outside.csv",
            header=["key"],
            row_key_columns=["key"],
            sort_columns=["key"],
            operations=[],
        )
    with pytest.raises(SageHTTPException) as raised:
        agent_service.mutate_workspace_csv(
            workspace,
            path="safe.csv",
            header=["key"],
            row_key_columns=["key"],
            sort_columns=["key"],
            operations=[],
            expected_content_hash="wrong",
        )
    assert raised.value.status_code == 409


def test_server_csv_route_forwards_user_scoped_mutation(monkeypatch):
    captured = {}

    async def fake_mutate(agent_id, user_id, **kwargs):
        captured.update({"agent_id": agent_id, "user_id": user_id, **kwargs})
        return {"path": kwargs["path"], "row_count": 1, "operations": {"append": 1}}

    monkeypatch.setattr(server_agent_router.agent_service, "mutate_server_agent_csv", fake_mutate)
    body = server_agent_router.FileWorkspaceCsvMutationRequest(
        path="user_health_data/demo.csv",
        header=["key", "value"],
        row_key_columns=["key"],
        sort_columns=["key"],
        operations=[
            FileWorkspaceCsvMutationOperation(
                operation="append",
                row_key="a",
                values={"key": "a", "value": "1"},
            )
        ],
    )
    response = asyncio.run(server_agent_router.mutate_csv_file("agent_demo", body, _request()))
    assert response.data["row_count"] == 1
    assert captured["user_id"] == "user_a"


def test_delete_workspace_entry_missing_ok(tmp_path):
    assert agent_service.delete_workspace_entry(
        tmp_path / "workspace",
        "missing.csv",
        missing_ok=True,
    ) is False

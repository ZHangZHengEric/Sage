import asyncio
from pathlib import Path
from types import SimpleNamespace

from common.services import chat_service


def _server_stream_service(
    workspace: Path,
    *,
    workspace_existed: bool,
    agent_id: str = "agent_demo",
):
    service = object.__new__(chat_service.SageStreamService)
    service.agent_workspace = str(workspace)
    service._workspace_existed = workspace_existed
    service.request = SimpleNamespace(agent_id=agent_id)
    return service


def test_server_new_workspace_does_not_create_sage_docs_and_repeats_cleanly(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "agent_workspace"
    workspace.mkdir()
    service = _server_stream_service(workspace, workspace_existed=False)

    def copy_inherit(_agent_id, target_workspace):
        (Path(target_workspace) / "inherited.txt").write_text(
            "kept", encoding="utf-8"
        )

    monkeypatch.setattr(
        chat_service.importlib,
        "import_module",
        lambda _name: SimpleNamespace(
            copy_agent_inherit_to_workspace=copy_inherit
        ),
    )
    asyncio.run(service.initialize_workspace_assets())
    asyncio.run(service.initialize_workspace_assets())

    assert (workspace / "inherited.txt").read_text(encoding="utf-8") == "kept"
    assert not (workspace / ".sage-docs").exists()
    assert not (workspace / "sage_usage_docs").exists()


def test_server_existing_workspace_cleans_exact_historical_directories(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "agent_workspace"
    for directory_name in (
        ".sage-docs",
        "sage_usage_docs",
        ".sage-docs-user",
        "sage_usage_docs_backup",
    ):
        directory = workspace / directory_name
        directory.mkdir(parents=True)
        (directory / "guide.md").write_text("content", encoding="utf-8")
    (workspace / "user-file.txt").write_text("keep", encoding="utf-8")
    nested_docs = workspace / "project" / ".sage-docs"
    nested_docs.mkdir(parents=True)
    (nested_docs / "user-guide.md").write_text("keep", encoding="utf-8")
    service = _server_stream_service(workspace, workspace_existed=True)

    asyncio.run(service.initialize_workspace_assets())
    asyncio.run(service.initialize_workspace_assets())

    assert not (workspace / ".sage-docs").exists()
    assert not (workspace / "sage_usage_docs").exists()
    assert (workspace / ".sage-docs-user" / "guide.md").exists()
    assert (workspace / "sage_usage_docs_backup" / "guide.md").exists()
    assert (nested_docs / "user-guide.md").exists()
    assert (workspace / "user-file.txt").read_text(encoding="utf-8") == "keep"


def test_server_workspace_cleanup_failure_warns_and_continues(monkeypatch):
    calls = []
    warnings = []

    def fail_delete(_workspace, directory_name, *, missing_ok):
        calls.append((directory_name, missing_ok))
        raise RuntimeError("read-only")

    monkeypatch.setattr(chat_service, "delete_workspace_entry", fail_delete)
    monkeypatch.setattr(chat_service.logger, "warning", warnings.append)

    chat_service._cleanup_server_workspace_sage_docs("/agent/workspace")

    assert calls == [(".sage-docs", True), ("sage_usage_docs", True)]
    assert len(warnings) == 2
    assert all("read-only" in warning for warning in warnings)

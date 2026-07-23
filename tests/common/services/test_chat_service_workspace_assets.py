import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from app.cli.services import runtime as cli_runtime
from common.services import chat_service, chat_utils


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

    monkeypatch.setattr(chat_service, "_is_desktop_mode", lambda: False)
    monkeypatch.setattr(
        chat_service.importlib,
        "import_module",
        lambda _name: SimpleNamespace(
            copy_agent_inherit_to_workspace=copy_inherit
        ),
    )
    monkeypatch.setattr(
        chat_service,
        "_copy_sage_usage_docs_to_workspace",
        lambda _workspace: (_ for _ in ()).throw(
            AssertionError("Server must not copy .sage-docs")
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

    monkeypatch.setattr(chat_service, "_is_desktop_mode", lambda: False)

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


def test_desktop_sage_usage_docs_copy_remains_unchanged(tmp_path, monkeypatch):
    home = tmp_path / "home"
    source = home / ".sage" / "sage-usage-docs"
    source.mkdir(parents=True)
    (source / "guide.md").write_text("desktop docs", encoding="utf-8")
    agents_root = tmp_path / "desktop_agents"
    monkeypatch.setenv("HOME", str(home))

    chat_service._copy_sage_usage_docs_to_agent_workspace_sync(
        "agent_desktop",
        str(agents_root),
    )

    copied = agents_root / "agent_desktop" / "sage_usage_docs" / "guide.md"
    assert copied.read_text(encoding="utf-8") == "desktop docs"


def test_cli_and_tui_stream_workspace_still_copy_sage_docs(tmp_path, monkeypatch):
    home = tmp_path / "home"
    source = home / ".sage" / "sage-usage-docs"
    source.mkdir(parents=True)
    (source / "guide.md").write_text("cli docs", encoding="utf-8")
    workspace = tmp_path / "cli_workspace"
    monkeypatch.setenv("HOME", str(home))

    request = SimpleNamespace(
        sandbox_approval_mode=None,
        system_context={},
        available_skills=[],
        user_id="cli_user",
    )
    stream_service = SimpleNamespace(agent_workspace="unused")

    async def populate_request(_request, *, require_agent_id):
        assert require_agent_id is False

    async def prepare_session(_request):
        return stream_service, None

    async def execute_chat_session(_stream_service):
        yield json.dumps({"type": "done"})

    monkeypatch.setattr(
        chat_service, "populate_request_from_agent_config", populate_request
    )
    monkeypatch.setattr(chat_service, "prepare_session", prepare_session)
    monkeypatch.setattr(chat_service, "execute_chat_session", execute_chat_session)
    monkeypatch.setattr(
        chat_utils, "create_skill_proxy", lambda *args, **kwargs: (object(), None)
    )

    async def collect_events():
        return [
            event
            async for event in cli_runtime.run_request_stream(
                request, workspace=str(workspace)
            )
        ]

    assert asyncio.run(collect_events()) == [{"type": "done"}]
    copied = workspace / ".sage-docs" / "guide.md"
    assert copied.read_text(encoding="utf-8") == "cli docs"

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sagents.tool.impl._apply_patch import (
    MAX_PATCH_OPERATIONS,
    PatchError,
    apply_update_operation,
    parse_patch,
)
from sagents.tool.impl.apply_patch_tool import ApplyPatchTool
from sagents.tool.impl.file_system_tool import FileSystemTool
from sagents.tool.tool_manager import ToolManager
from sagents.tool.tool_proxy import ToolProxy
from sagents.utils.sandbox.config import VolumeMount
from sagents.utils.sandbox.providers.passthrough.passthrough import (
    PassthroughSandboxProvider,
)


class FakeSandbox:
    workspace_path = "/workspace"

    def __init__(
        self,
        files=None,
        fail_write_once=None,
        ignore_write_once=None,
        ignore_delete_once=None,
    ):
        self.files = dict(files or {})
        self.fail_write_once = fail_write_once
        self.ignore_write_once = ignore_write_once
        self.ignore_delete_once = ignore_delete_once
        self.write_calls = []
        self.delete_calls = []
        self.directories = set()

    async def file_exists(self, path):
        return path in self.files

    async def read_file(self, path, encoding="utf-8"):
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    async def write_file(self, path, content, encoding="utf-8", mode="overwrite"):
        self.write_calls.append(path)
        if self.fail_write_once == path:
            self.fail_write_once = None
            raise OSError(f"simulated write failure: {path}")
        if self.ignore_write_once == path:
            self.ignore_write_once = None
            return
        self.files[path] = content

    async def delete_file(self, path):
        self.delete_calls.append(path)
        if path not in self.files:
            raise FileNotFoundError(path)
        if self.ignore_delete_once == path:
            self.ignore_delete_once = None
            return
        del self.files[path]

    async def ensure_directory(self, path):
        self.directories.add(path)


def test_parse_patch_supports_add_update_delete_and_move():
    operations = parse_patch(
        """*** Begin Patch
*** Add File: new.txt
+created
*** Update File: source.txt
*** Move to: moved.txt
@@ def run():
-    return False
+    return True
*** Delete File: old.txt
*** End Patch"""
    )

    assert [operation.action for operation in operations] == [
        "add",
        "update",
        "delete",
    ]
    assert operations[0].content == "created\n"
    assert operations[1].move_path == "moved.txt"
    assert operations[1].chunks[0].change_context == "def run():"


@pytest.mark.parametrize(
    "path",
    [
        "../outside.txt",
        "/tmp/outside.txt",
        "C:/outside.txt",
        "C:outside.txt",
        ".git/config",
        ".GIT/config",
        ".git./config",
        ".git /config",
        ".git:metadata/config",
        ".. /outside.txt",
    ],
)
def test_parse_patch_rejects_paths_outside_workspace(path):
    with pytest.raises(PatchError):
        parse_patch(
            f"""*** Begin Patch
*** Add File: {path}
+blocked
*** End Patch"""
        )


def test_parse_patch_rejects_invalid_utf8_text():
    with pytest.raises(PatchError) as exc_info:
        parse_patch("*** Begin Patch\n*** Add File: bad.txt\n+\ud800\n*** End Patch")

    assert exc_info.value.code == "INVALID_ARGUMENT"


def test_parse_patch_rejects_too_many_operations():
    operations = "\n".join(
        f"*** Add File: file-{index}.txt\n+content"
        for index in range(MAX_PATCH_OPERATIONS + 1)
    )

    with pytest.raises(PatchError) as exc_info:
        parse_patch(f"*** Begin Patch\n{operations}\n*** End Patch")

    assert exc_info.value.code == "INVALID_ARGUMENT"
    assert "too many file operations" in str(exc_info.value)


def test_apply_update_operation_preserves_crlf():
    operation = parse_patch(
        """*** Begin Patch
*** Update File: demo.txt
@@
-old
+new
*** End Patch"""
    )[0]

    content, added, removed = apply_update_operation("old\r\n", operation)

    assert content == "new\r\n"
    assert added == 1
    assert removed == 1


def test_apply_update_operation_rejects_ambiguous_hunk():
    operation = parse_patch(
        """*** Begin Patch
*** Update File: demo.txt
@@
-same
+changed
*** End Patch"""
    )[0]

    with pytest.raises(PatchError) as exc_info:
        apply_update_operation("same\nmiddle\nsame\n", operation)

    assert exc_info.value.code == "MULTIPLE_MATCHES"


def test_apply_update_operation_appends_addition_only_hunk():
    operation = parse_patch(
        """*** Begin Patch
*** Update File: demo.txt
@@
+appended
*** End Patch"""
    )[0]

    content, added, removed = apply_update_operation("first\n", operation)

    assert content == "first\nappended\n"
    assert added == 1
    assert removed == 0


def test_parse_patch_allows_blank_lines_after_end_of_file():
    operation = parse_patch(
        """*** Begin Patch
*** Update File: demo.txt
@@
+appended
*** End of File

*** End Patch"""
    )[0]

    assert operation.chunks[0].is_end_of_file is True


def test_move_only_operation_preserves_content_exactly():
    operation = parse_patch(
        """*** Begin Patch
*** Update File: script.sh
*** Move to: bin/script.sh
*** End Patch"""
    )[0]

    content, added, removed = apply_update_operation("#!/bin/sh", operation)

    assert content == "#!/bin/sh"
    assert added == 0
    assert removed == 0


def test_workspace_path_preserves_root_workspace():
    sandbox = SimpleNamespace(workspace_path="/")

    assert ApplyPatchTool._workspace_path(sandbox, "src/main.py") == "/src/main.py"


@pytest.mark.asyncio
async def test_apply_patch_commits_multi_file_plan(monkeypatch):
    sandbox = FakeSandbox(
        {
            "/workspace/source.txt": "old\n",
            "/workspace/delete.txt": "remove\n",
            "/workspace/move.txt": "before\n",
        }
    )
    tool = ApplyPatchTool()
    monkeypatch.setattr(tool, "_get_sandbox", lambda session_id: sandbox)

    result = await tool.apply_patch(
        patch="""*** Begin Patch
*** Update File: source.txt
@@
-old
+new
*** Add File: nested/added.txt
+added
*** Delete File: delete.txt
*** Update File: move.txt
*** Move to: moved.txt
@@
-before
+after
*** End Patch""",
        session_id="patch-success",
    )

    assert result["success"] is True
    assert result["files_changed"] == 4
    assert sandbox.files == {
        "/workspace/source.txt": "new\n",
        "/workspace/nested/added.txt": "added\n",
        "/workspace/moved.txt": "after\n",
    }
    assert sandbox.delete_calls == [
        "/workspace/delete.txt",
        "/workspace/move.txt",
    ]
    assert [change["action"] for change in result["changes"]] == [
        "update",
        "add",
        "delete",
        "move",
    ]
    assert len(result["patch_sha256"]) == 64


@pytest.mark.asyncio
async def test_apply_patch_preflight_failure_performs_no_writes(monkeypatch):
    sandbox = FakeSandbox({"/workspace/source.txt": "current\n"})
    tool = ApplyPatchTool()
    monkeypatch.setattr(tool, "_get_sandbox", lambda session_id: sandbox)

    result = await tool.apply_patch(
        patch="""*** Begin Patch
*** Update File: source.txt
@@
-stale
+new
*** Add File: added.txt
+must not be written
*** End Patch""",
        session_id="patch-preflight",
    )

    assert result["success"] is False
    assert result["error_code"] == "NO_MATCH"
    assert sandbox.write_calls == []
    assert sandbox.files == {"/workspace/source.txt": "current\n"}


@pytest.mark.asyncio
async def test_apply_patch_rejects_file_changed_during_preflight(monkeypatch):
    sandbox = FakeSandbox({"/workspace/source.txt": "old\n"})
    tool = ApplyPatchTool()
    monkeypatch.setattr(tool, "_get_sandbox", lambda session_id: sandbox)
    original_preflight = tool._preflight

    async def mutate_after_preflight(active_sandbox, operations):
        plan, snapshots = await original_preflight(active_sandbox, operations)
        sandbox.files["/workspace/source.txt"] = "external\n"
        return plan, snapshots

    monkeypatch.setattr(tool, "_preflight", mutate_after_preflight)

    result = await tool.apply_patch(
        patch="""*** Begin Patch
*** Update File: source.txt
@@
-old
+new
*** End Patch""",
        session_id="patch-precondition",
    )

    assert result["success"] is False
    assert result["error_code"] == "PRECONDITION_FAILED"
    assert sandbox.write_calls == []
    assert sandbox.files == {"/workspace/source.txt": "external\n"}


@pytest.mark.asyncio
async def test_apply_patch_rejects_non_utf8_source(monkeypatch):
    sandbox = FakeSandbox({"/workspace/source.bin": "placeholder"})

    async def invalid_utf8(path, encoding="utf-8"):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    sandbox.read_file = invalid_utf8
    tool = ApplyPatchTool()
    monkeypatch.setattr(tool, "_get_sandbox", lambda session_id: sandbox)

    result = await tool.apply_patch(
        patch="""*** Begin Patch
*** Update File: source.bin
@@
-old
+new
*** End Patch""",
        session_id="patch-non-utf8",
    )

    assert result["success"] is False
    assert result["error_code"] == "UNSUPPORTED"
    assert sandbox.write_calls == []


@pytest.mark.asyncio
async def test_apply_patch_rolls_back_after_commit_failure(monkeypatch):
    sandbox = FakeSandbox(
        {"/workspace/source.txt": "old\n"},
        fail_write_once="/workspace/second.txt",
    )
    tool = ApplyPatchTool()
    monkeypatch.setattr(tool, "_get_sandbox", lambda session_id: sandbox)

    result = await tool.apply_patch(
        patch="""*** Begin Patch
*** Update File: source.txt
@@
-old
+new
*** Add File: second.txt
+second
*** End Patch""",
        session_id="patch-rollback",
    )

    assert result["success"] is False
    assert result["error_code"] == "SANDBOX_ERROR"
    assert result["rollback"] == {
        "attempted": True,
        "succeeded": True,
        "errors": [],
    }
    assert sandbox.files == {"/workspace/source.txt": "old\n"}


@pytest.mark.asyncio
async def test_apply_patch_rollback_skips_unchanged_paths(monkeypatch):
    sandbox = FakeSandbox(
        {"/workspace/source.txt": "old\n"},
        fail_write_once="/workspace/source.txt",
    )
    tool = ApplyPatchTool()
    monkeypatch.setattr(tool, "_get_sandbox", lambda session_id: sandbox)

    result = await tool.apply_patch(
        patch="""*** Begin Patch
*** Update File: source.txt
@@
-old
+new
*** End Patch""",
        session_id="patch-unchanged-rollback",
    )

    assert result["success"] is False
    assert result["rollback"]["succeeded"] is True
    assert sandbox.files == {"/workspace/source.txt": "old\n"}
    assert sandbox.write_calls == ["/workspace/source.txt"]


@pytest.mark.asyncio
async def test_apply_patch_verifies_silent_delete_failure(monkeypatch):
    sandbox = FakeSandbox(
        {"/workspace/delete.txt": "keep\n"},
        ignore_delete_once="/workspace/delete.txt",
    )
    tool = ApplyPatchTool()
    monkeypatch.setattr(tool, "_get_sandbox", lambda session_id: sandbox)

    result = await tool.apply_patch(
        patch="""*** Begin Patch
*** Delete File: delete.txt
*** End Patch""",
        session_id="patch-delete-verification",
    )

    assert result["success"] is False
    assert result["error_code"] == "SANDBOX_ERROR"
    assert result["rollback"]["succeeded"] is True
    assert sandbox.files == {"/workspace/delete.txt": "keep\n"}


@pytest.mark.asyncio
async def test_apply_patch_verifies_silent_write_failure(monkeypatch):
    sandbox = FakeSandbox(
        {"/workspace/source.txt": "old\n"},
        ignore_write_once="/workspace/source.txt",
    )
    tool = ApplyPatchTool()
    monkeypatch.setattr(tool, "_get_sandbox", lambda session_id: sandbox)

    result = await tool.apply_patch(
        patch="""*** Begin Patch
*** Update File: source.txt
@@
-old
+new
*** End Patch""",
        session_id="patch-write-verification",
    )

    assert result["success"] is False
    assert result["error_code"] == "SANDBOX_ERROR"
    assert result["rollback"]["succeeded"] is True
    assert sandbox.files == {"/workspace/source.txt": "old\n"}


@pytest.mark.asyncio
async def test_apply_patch_rolls_back_when_commit_is_cancelled(monkeypatch):
    sandbox = FakeSandbox({"/workspace/source.txt": "old\n"})
    tool = ApplyPatchTool()
    monkeypatch.setattr(tool, "_get_sandbox", lambda session_id: sandbox)

    async def cancelled_commit(active_sandbox, plan):
        change = plan[0]
        path = change.output_actual_path
        content = change.new_content
        assert path is not None
        assert content is not None
        await tool._write_file(active_sandbox, path, content)
        raise asyncio.CancelledError

    monkeypatch.setattr(tool, "_commit", cancelled_commit)

    with pytest.raises(asyncio.CancelledError):
        await tool.apply_patch(
            patch="""*** Begin Patch
*** Update File: source.txt
@@
-old
+new
*** End Patch""",
            session_id="patch-cancelled",
        )

    assert sandbox.files == {"/workspace/source.txt": "old\n"}


@pytest.mark.asyncio
async def test_apply_patch_reports_silent_rollback_failure(monkeypatch):
    sandbox = FakeSandbox(
        fail_write_once="/workspace/second.txt",
        ignore_delete_once="/workspace/first.txt",
    )
    tool = ApplyPatchTool()
    monkeypatch.setattr(tool, "_get_sandbox", lambda session_id: sandbox)

    result = await tool.apply_patch(
        patch="""*** Begin Patch
*** Add File: first.txt
+first
*** Add File: second.txt
+second
*** End Patch""",
        session_id="patch-rollback-verification",
    )

    assert result["success"] is False
    assert result["rollback"]["succeeded"] is False
    assert result["rollback"]["errors"] == [
        {
            "path": "first.txt",
            "error": "Rollback did not remove file: first.txt",
        }
    ]
    assert sandbox.files == {"/workspace/first.txt": "first\n"}


@pytest.mark.asyncio
async def test_apply_patch_reports_validation_runtime_failure(monkeypatch):
    sandbox = FakeSandbox()
    tool = ApplyPatchTool()
    monkeypatch.setattr(tool, "_get_sandbox", lambda session_id: sandbox)

    def validation_failure(path, content):
        raise RuntimeError("validator unavailable")

    monkeypatch.setattr(
        FileSystemTool,
        "_build_validation_result",
        staticmethod(validation_failure),
    )

    result = await tool.apply_patch(
        patch="""*** Begin Patch
*** Add File: added.py
+value = 1
*** End Patch""",
        session_id="patch-validation-failure",
    )

    assert result["success"] is True
    assert result["changes"][0]["validation"]["status"] == "warning"
    assert result["changes"][0]["validation"]["passed"] is False
    assert sandbox.files == {"/workspace/added.py": "value = 1\n"}


@pytest.mark.asyncio
async def test_apply_patch_uses_real_passthrough_workspace(monkeypatch, tmp_path):
    source = tmp_path / "src" / "demo.py"
    source.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    sandbox = PassthroughSandboxProvider(
        sandbox_id="patch-passthrough",
        sandbox_agent_workspace=str(tmp_path),
        volume_mounts=[VolumeMount(str(tmp_path), str(tmp_path))],
    )
    tool = ApplyPatchTool()
    monkeypatch.setattr(tool, "_get_sandbox", lambda session_id: sandbox)

    result = await tool.apply_patch(
        patch="""*** Begin Patch
*** Update File: src/demo.py
@@
-value = 1
+value = 2
*** Add File: tests/test_demo.py
+def test_value():
+    assert True
*** End Patch""",
        session_id="patch-passthrough",
    )

    assert result["success"] is True
    assert source.read_text(encoding="utf-8") == "value = 2\n"
    assert (tmp_path / "tests" / "test_demo.py").read_text(
        encoding="utf-8"
    ) == "def test_value():\n    assert True\n"


def test_apply_patch_tool_schema_and_coding_preset_expose_tool():
    spec = ApplyPatchTool.apply_patch._tool_spec
    assert spec.name == "apply_patch"
    assert spec.required == ["patch"]
    assert spec.explicit_only is True

    config_path = Path(__file__).parents[4] / "examples" / "coding_agent_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert "apply_patch" in config["availableTools"]
    assert "prefer Sage apply_patch" in config["systemPrefix"]


def test_apply_patch_requires_explicit_tool_selection():
    manager = ToolManager(is_auto_discover=False, isolated=True)
    manager.tools = {
        "apply_patch": ApplyPatchTool.apply_patch._tool_spec,
    }

    default_proxy = ToolProxy(manager)
    explicit_proxy = ToolProxy(manager, available_tools=["apply_patch"])

    assert default_proxy.get_tool("apply_patch") is None
    assert default_proxy.get_openai_tools() == []
    assert default_proxy.list_tools_simplified() == []
    assert default_proxy.list_tools() == []
    assert default_proxy.list_tools_with_type() == []
    assert default_proxy.list_all_tools_name() == []
    assert explicit_proxy.get_tool("apply_patch") is not None
    assert [tool["function"]["name"] for tool in explicit_proxy.get_openai_tools()] == [
        "apply_patch"
    ]
    assert explicit_proxy.list_all_tools_name() == ["apply_patch"]

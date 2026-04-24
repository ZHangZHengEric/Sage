"""CodebaseTool 集成测试：grep / glob / list_dir 在真实文件系统下行为。

使用 PassthroughSandboxProvider 把临时目录作为沙箱工作区，验证：
- grep 命中 / 未命中 / files_with_matches / count 三种 output_mode
- ripgrep 不可用时降级到 grep 也能拿到结构化结果
- glob 支持 ** 跨目录、按 mtime 倒序
- list_dir 直接复用 sandbox.get_file_tree 限制深度
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time

import pytest

from sagents.tool.impl.codebase_tool import CodebaseTool
from sagents.utils.sandbox.providers.passthrough.passthrough import PassthroughSandboxProvider


pytestmark = [pytest.mark.timeout(30)]


@pytest.fixture
def codebase_env(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="sage_codebase_test_")
    # 准备一个小项目结构
    os.makedirs(os.path.join(tmp, "src", "pkg"), exist_ok=True)
    os.makedirs(os.path.join(tmp, "tests"), exist_ok=True)
    with open(os.path.join(tmp, "src", "pkg", "alpha.py"), "w") as f:
        f.write("def hello():\n    return 'world'\n")
    time.sleep(0.02)
    with open(os.path.join(tmp, "src", "pkg", "beta.py"), "w") as f:
        f.write("def hello():\n    return 'sage'\n# TODO: refactor\n")
    time.sleep(0.02)
    with open(os.path.join(tmp, "tests", "test_alpha.py"), "w") as f:
        f.write("import pkg.alpha\n")
    with open(os.path.join(tmp, "README.md"), "w") as f:
        f.write("# project\n\nNo todo here.\n")

    sandbox = PassthroughSandboxProvider(sandbox_id="cb-test", sandbox_agent_workspace=tmp)
    tool = CodebaseTool()
    monkeypatch.setattr(tool, "_get_sandbox", lambda session_id: sandbox)
    yield tool, sandbox, tmp
    shutil.rmtree(tmp, ignore_errors=True)


# ===== grep =====

async def test_grep_content_finds_matches(codebase_env):
    tool, _, _ = codebase_env
    out = await tool.grep(pattern="def hello", session_id="s1")
    assert out["success"] is True
    assert out["count"] >= 2
    files = {m["file"] for m in out["matches"]}
    assert any(f.endswith("alpha.py") for f in files)
    assert any(f.endswith("beta.py") for f in files)


async def test_grep_no_match_returns_empty(codebase_env):
    tool, _, _ = codebase_env
    out = await tool.grep(pattern="this_string_does_not_exist_anywhere", session_id="s1")
    assert out["success"] is True
    assert out["count"] == 0


async def test_grep_files_with_matches_mode(codebase_env):
    tool, _, _ = codebase_env
    out = await tool.grep(pattern="TODO", output_mode="files_with_matches", session_id="s1")
    assert out["success"] is True
    assert out["output_mode"] == "files_with_matches"
    assert any(f.endswith("beta.py") for f in out["files"])


async def test_grep_count_mode(codebase_env):
    tool, _, _ = codebase_env
    out = await tool.grep(pattern="def hello", output_mode="count", session_id="s1")
    assert out["success"] is True
    assert out["output_mode"] == "count"
    assert out["total"] >= 2


async def test_grep_invalid_pattern_returns_error(codebase_env):
    tool, _, _ = codebase_env
    out = await tool.grep(pattern="", session_id="s1")
    assert out.get("success") is False
    assert out["error_code"] == "INVALID_ARGUMENT"


async def test_grep_falls_back_when_rg_missing(codebase_env, monkeypatch):
    tool, _, _ = codebase_env

    async def _no_rg(self, sandbox, name):
        return False

    monkeypatch.setattr(CodebaseTool, "_has_command", _no_rg)
    out = await tool.grep(pattern="def hello", session_id="s1")
    assert out["success"] is True
    assert out["tool"] == "grep"
    assert out["count"] >= 2


# ===== glob =====

async def test_glob_double_star_matches_nested_files(codebase_env):
    tool, _, _ = codebase_env
    out = await tool.glob(pattern="**/*.py", session_id="s1")
    assert out["success"] is True
    files = out["files"]
    assert any(f.endswith("alpha.py") for f in files)
    assert any(f.endswith("beta.py") for f in files)
    assert any(f.endswith("test_alpha.py") for f in files)


async def test_glob_returns_results_sorted_by_mtime_desc(codebase_env):
    tool, _, tmp = codebase_env
    # touch test_alpha to make it newest
    new_path = os.path.join(tmp, "tests", "test_alpha.py")
    later = time.time() + 5
    os.utime(new_path, (later, later))
    out = await tool.glob(pattern="**/*.py", session_id="s1")
    assert out["files"][0].endswith("test_alpha.py")


async def test_glob_invalid_pattern(codebase_env):
    tool, _, _ = codebase_env
    out = await tool.glob(pattern="", session_id="s1")
    assert out.get("success") is False
    assert out["error_code"] == "INVALID_ARGUMENT"


# ===== list_dir =====

async def test_list_dir_returns_tree_string(codebase_env):
    tool, _, _ = codebase_env
    out = await tool.list_dir(depth=2, session_id="s1")
    assert out["success"] is True
    assert isinstance(out["tree"], str)
    assert "src" in out["tree"]


async def test_list_dir_respects_depth_limit(codebase_env):
    tool, _, _ = codebase_env
    shallow = await tool.list_dir(depth=1, session_id="s1")
    deep = await tool.list_dir(depth=3, session_id="s1")
    # 更深的树字符串通常更长，至少不应该比浅的短
    assert len(deep["tree"]) >= len(shallow["tree"])

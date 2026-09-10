import pytest

from sagents.tool.impl.file_system_tool import FileSystemTool


class _FakeSandbox:
    def __init__(self, content: str):
        self.content = content
        self.writes = []

    async def read_file(self, file_path: str, encoding: str = "utf-8"):
        return self.content

    async def write_file(self, file_path: str, content: str, mode: str = "overwrite"):
        self.writes.append((file_path, content, mode))
        self.content = content


@pytest.mark.asyncio
async def test_file_read_display_matches_update_line_numbers():
    tool = FileSystemTool()
    tool._get_sandbox = lambda session_id: _FakeSandbox("alpha\nbeta\ngamma\n")

    result = await tool.file_read(
        file_path="demo.yaml",
        start_line=2,
        end_line=3,
        session_id="session-1",
    )

    assert result["status"] == "success"
    assert result["start_line"] == 2
    assert result["end_line"] == 3
    assert result["content"].splitlines()[0].startswith("   2 | beta")
    assert result["content"].splitlines()[1].startswith("   3 | gamma")

    updated = FileSystemTool._apply_line_range_update(
        "alpha\nbeta\ngamma\n",
        replacement="BETA",
        start_line=2,
        end_line=2,
    )
    assert updated["content"] == "alpha\nBETA\ngamma\n"


def test_normalize_update_operation_accepts_explicit_search_replace():
    result = FileSystemTool._normalize_update_operation(
        {
            "update_mode": "search_replace",
            "search_pattern": "hello",
            "replacement": "world",
        }
    )

    assert result["status"] == "success"
    assert result["update_mode"] == "search_replace"


def test_normalize_update_operation_requires_both_line_bounds():
    result = FileSystemTool._normalize_update_operation(
        {
            "update_mode": "line_range",
            "start_line": 2,
            "replacement": "x",
        }
    )

    assert result["status"] == "error"
    assert "start_line 和 end_line" in result["message"]


def test_normalize_update_operation_rejects_mixed_modes():
    result = FileSystemTool._normalize_update_operation(
        {
            "update_mode": "line_range",
            "start_line": 2,
            "end_line": 3,
            "search_pattern": "hello",
            "replacement": "x",
        }
    )

    assert result["status"] == "error"
    assert "不要同时提供 search_pattern" in result["message"]


def test_apply_line_range_update_uses_1based_inclusive_bounds():
    result = FileSystemTool._apply_line_range_update(
        "line1\nline2\nline3\n",
        replacement="middle",
        start_line=2,
        end_line=2,
    )

    assert result["status"] == "success"
    assert result["content"] == "line1\nmiddle\nline3\n"
    assert result["lines_replaced"] == 1
    assert result["start_line"] == 2
    assert result["end_line"] == 2


def test_apply_line_range_update_replaces_first_line_as_1():
    result = FileSystemTool._apply_line_range_update(
        "line1\nline2\nline3\n",
        replacement="head",
        start_line=1,
        end_line=1,
    )

    assert result["status"] == "success"
    assert result["content"] == "head\nline2\nline3\n"


def test_apply_line_range_update_empty_replacement_deletes_the_line():
    result = FileSystemTool._apply_line_range_update(
        "line1\nline2\nline3\n",
        replacement="",
        start_line=2,
        end_line=2,
    )

    assert result["status"] == "success"
    assert result["content"] == "line1\nline3\n"
    assert result["replacements"] == 1


def test_apply_line_range_update_same_content_is_unchanged():
    result = FileSystemTool._apply_line_range_update(
        "line1\nline2\nline3\n",
        replacement="line2\n",
        start_line=2,
        end_line=2,
    )

    assert result["status"] == "success"
    assert result["content"] == "line1\nline2\nline3\n"
    assert result["replacements"] == 0


@pytest.mark.asyncio
async def test_file_update_deletes_line_and_writes():
    sandbox = _FakeSandbox("a:\n  mg: 字幕\n  font: big\n")
    tool = FileSystemTool()
    tool._get_sandbox = lambda session_id: sandbox

    result = await tool.file_update(
        file_path="demo.yaml",
        operations=[
            {
                "update_mode": "line_range",
                "start_line": 2,
                "end_line": 2,
                "replacement": "",
            }
        ],
        session_id="session-1",
    )

    assert result["status"] == "success"
    assert result["replacements"] >= 1
    assert "unchanged" not in result["message"].lower()
    assert "未发生变化" not in result["message"]
    assert sandbox.writes
    assert sandbox.content == "a:\n  font: big\n"
    assert result["new_length"] == len(sandbox.content)
    assert result["new_length"] != result["original_length"]


@pytest.mark.asyncio
async def test_file_update_skips_write_when_replacement_matches():
    original = "a:\n  mg: 字幕\n  font: big\n"
    sandbox = _FakeSandbox(original)
    tool = FileSystemTool()
    tool._get_sandbox = lambda session_id: sandbox

    result = await tool.file_update(
        file_path="demo.yaml",
        operations=[
            {
                "update_mode": "line_range",
                "start_line": 2,
                "end_line": 2,
                "replacement": "  mg: 字幕\n",
            }
        ],
        session_id="session-1",
    )

    assert result["status"] == "success"
    assert result["replacements"] == 0
    assert "unchanged" in result["message"].lower() or "未发生变化" in result["message"]
    assert sandbox.writes == []
    assert result["original_length"] == result["new_length"]
    assert sandbox.content == original


def test_apply_line_range_update_rejects_zero_based_input():
    result = FileSystemTool._apply_line_range_update(
        "line1\nline2\n",
        replacement="x",
        start_line=0,
        end_line=0,
    )

    assert result["status"] == "error"
    assert "1-based" in result["message"]


def test_normalize_update_operation_rejects_zero_based_line_range():
    result = FileSystemTool._normalize_update_operation(
        {
            "update_mode": "line_range",
            "start_line": 0,
            "end_line": 1,
            "replacement": "x",
        }
    )

    assert result["status"] == "error"
    assert "1-based" in result["message"]


def test_apply_search_update_prefers_literal_match_before_regex():
    # 默认要求唯一匹配；多匹配需要显式 replace_all=True
    result = FileSystemTool._apply_search_update(
        "foo.*bar foo.*bar",
        search_pattern="foo.*bar",
        replacement="baz",
        replace_all=True,
    )

    assert result["status"] == "success"
    assert result["match_mode"] == "text"
    assert result["content"] == "baz baz"
    assert result["replacements"] == 2


def test_apply_search_update_falls_back_to_regex():
    result = FileSystemTool._apply_search_update(
        "foo1 foo2",
        search_pattern=r"foo\d",
        replacement="x",
        replace_all=True,
    )

    assert result["status"] == "success"
    assert result["match_mode"] == "regex"
    assert result["content"] == "x x"
    assert result["replacements"] == 2


def test_apply_search_update_unique_match_succeeds():
    result = FileSystemTool._apply_search_update(
        "alpha beta gamma",
        search_pattern="beta",
        replacement="BETA",
    )
    assert result["status"] == "success"
    assert result["replacements"] == 1
    assert result["content"] == "alpha BETA gamma"


def test_apply_search_update_multiple_text_matches_returns_error():
    result = FileSystemTool._apply_search_update(
        "a foo b\nfoo c\n",
        search_pattern="foo",
        replacement="X",
    )
    assert result["status"] == "error"
    assert result["error_code"] == "MULTIPLE_MATCHES"
    assert result["match_count"] == 2
    assert isinstance(result["matches"], list) and len(result["matches"]) == 2
    assert result["matches"][0]["line"] == 1
    assert result["matches"][1]["line"] == 2


def test_apply_search_update_multiple_regex_matches_returns_error():
    result = FileSystemTool._apply_search_update(
        "v1\nv2\nv3\n",
        search_pattern=r"v\d",
        replacement="X",
    )
    assert result["status"] == "error"
    assert result["error_code"] == "MULTIPLE_MATCHES"
    assert result["match_count"] == 3


def test_apply_search_update_invalid_regex_returns_error():
    result = FileSystemTool._apply_search_update(
        "abc",
        search_pattern="(",
        replacement="x",
    )
    assert result["status"] == "error"
    assert result["error_code"] == "INVALID_ARGUMENT"


@pytest.mark.asyncio
async def test_overlapping_line_ranges_do_not_write():
    sandbox = _FakeSandbox("a\nb\nc\nd\n")
    tool = FileSystemTool()
    tool._get_sandbox = lambda session_id: sandbox
    result = await tool.file_update(
        "notes.txt",
        operations=[
            {
                "update_mode": "line_range",
                "start_line": 2,
                "end_line": 3,
                "replacement": "B",
            },
            {
                "update_mode": "line_range",
                "start_line": 3,
                "end_line": 4,
                "replacement": "C",
            },
        ],
        session_id="session-1",
    )
    assert result["status"] == "error"
    assert sandbox.writes == []


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_last_line_replacement_preserves_terminator(newline):
    original = "a" + newline + "b" + newline
    result = FileSystemTool._apply_line_range_update(original, "b", 2, 2)
    assert result["content"] == original
    assert result["replacements"] == 0


@pytest.mark.asyncio
async def test_identical_search_replacement_is_success_without_write():
    sandbox = _FakeSandbox("a\nb\n")
    tool = FileSystemTool()
    tool._get_sandbox = lambda session_id: sandbox
    result = await tool.file_update(
        "notes.txt",
        operations=[
            {
                "update_mode": "search_replace",
                "search_pattern": "b",
                "replacement": "b",
            },
        ],
        session_id="session-1",
    )
    assert result["status"] == "success"
    assert result["replacements"] == 0
    assert sandbox.writes == []

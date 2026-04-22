from sagents.tool.impl.file_system_tool import FileSystemTool


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


def test_apply_line_range_update_uses_inclusive_bounds():
    result = FileSystemTool._apply_line_range_update(
        "line1\nline2\nline3\n",
        replacement="middle",
        start_line=1,
        end_line=1,
    )

    assert result["status"] == "success"
    assert result["content"] == "line1\nmiddle\nline3\n"
    assert result["lines_replaced"] == 1
    assert result["start_line"] == 1
    assert result["end_line"] == 1


def test_apply_search_update_prefers_literal_match_before_regex():
    result = FileSystemTool._apply_search_update(
        "foo.*bar foo.*bar",
        search_pattern="foo.*bar",
        replacement="baz",
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
    )

    assert result["status"] == "success"
    assert result["match_mode"] == "regex"
    assert result["content"] == "x x"
    assert result["replacements"] == 2

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
    # 行号上下文存在
    assert "line" in result["matches"][0]


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

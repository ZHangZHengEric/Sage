"""make_tool_error 统一错误格式测试。"""
from sagents.tool.error_codes import ToolErrorCode, make_tool_error


def test_make_tool_error_basic_shape():
    err = make_tool_error(ToolErrorCode.INVALID_ARGUMENT, "bad arg", hint="fix it")
    assert err["success"] is False
    assert err["status"] == "error"
    assert err["error_code"] == "INVALID_ARGUMENT"
    assert err["error"] == "bad arg"
    assert err["message"] == "bad arg"  # 兼容旧消费方
    assert err["hint"] == "fix it"


def test_make_tool_error_extra_fields_propagate():
    err = make_tool_error(
        ToolErrorCode.MULTIPLE_MATCHES,
        "matched 3",
        match_count=3,
        matches=[{"line": 1}],
        file_path="/a.py",
    )
    assert err["match_count"] == 3
    assert err["matches"] == [{"line": 1}]
    assert err["file_path"] == "/a.py"


def test_make_tool_error_drops_none_extras():
    err = make_tool_error(ToolErrorCode.NOT_FOUND, "missing", file_path=None)
    assert "file_path" not in err


def test_make_tool_error_falls_back_to_internal_when_code_empty():
    err = make_tool_error("", "boom")
    assert err["error_code"] == "INTERNAL_ERROR"

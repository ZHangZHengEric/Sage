from types import SimpleNamespace

from sagents.tool.argument_validation import argument_contract_error


def spec(**kwargs):
    return SimpleNamespace(
        name="send",
        parameters={"payload": {"type": "object", "properties": {"body": {"type": "string"}}, "required": ["body"]}},
        required=["payload", "user_id"],
        func=None,
        **kwargs,
    )


def test_flattened_payload_returns_shape_without_echoing_private_values():
    args = {"body": "private content"}
    error = argument_contract_error(spec(), args)
    assert error["missing_fields"] == ["payload"]
    assert error["unknown_fields"] == ["body"]
    assert error["object_fields"]["payload"]["required"] == ["body"]
    assert "private content" not in str(error)
    assert args == {"body": "private content"}
    assert argument_contract_error(spec(), {"payload": {"body": "text"}}) is None


def test_explicit_open_schema_preserves_extensions():
    assert (
        argument_contract_error(spec(input_schema={"additionalProperties": True}), {"payload": {}, "extension": 1})
        is None
    )


def test_schema_hash_changes_with_contract():
    first = argument_contract_error(spec(), {})
    changed = spec()
    changed.required = []
    second = argument_contract_error(changed, {"unknown": 1})
    assert first["schema_hash"] != second["schema_hash"]


def test_mcp_schema_with_implicit_open_properties_keeps_unknown_fields():
    assert argument_contract_error(spec(input_schema={"type": "object"}), {"payload": {}, "extension": 1}) is None


async def test_manager_rejects_bad_arguments_before_execution(monkeypatch):
    import json
    from unittest.mock import AsyncMock

    from sagents.tool.tool_manager import ToolManager
    from sagents.tool.tool_schema import ToolSpec

    manager = ToolManager(is_auto_discover=False, isolated=True)

    async def write_file(path):
        raise AssertionError("should use mocked transport")

    tool = ToolSpec(
        name="write_file",
        description="",
        description_i18n={},
        func=write_file,
        parameters={"path": {"type": "string"}},
        required=["path"],
    )
    manager.tools = {tool.name: tool}
    execute = AsyncMock(return_value='{"status":"success"}')
    monkeypatch.setattr(manager, "_execute_standard_tool_async", execute)
    error = json.loads(await manager.run_tool_async("write_file", wrong="secret"))
    assert error["error_code"] == "INVALID_ARGUMENT"
    assert error["missing_fields"] == ["path"]
    execute.assert_not_awaited()
    await manager.run_tool_async("write_file", path="example.txt")
    execute.assert_awaited_once()

from sagents.tool.tool_baseline import augment_with_baseline_tools


def test_augment_with_baseline_tools_keeps_suggestion_and_existing_baselines():
    tools = augment_with_baseline_tools(
        ["custom_tool"],
        ["custom_tool", "file_read", "file_write", "turn_status"],
    )

    assert tools == ["custom_tool", "turn_status", "file_read", "file_write"]


def test_augment_with_baseline_tools_does_not_add_unavailable_tools():
    tools = augment_with_baseline_tools(
        ["custom_tool"],
        ["custom_tool"],
    )

    assert tools == ["custom_tool"]


def test_augment_with_baseline_tools_deduplicates_existing_baseline_suggestion():
    tools = augment_with_baseline_tools(
        ["file_read", "custom_tool", "file_read"],
        ["custom_tool", "file_read", "turn_status"],
    )

    assert tools == ["file_read", "custom_tool", "turn_status"]

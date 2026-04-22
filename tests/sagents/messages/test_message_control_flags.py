from sagents.utils.message_control_flags import extract_control_flags_from_messages


def test_extract_enable_plan_from_plain_text_message():
    messages = [
        {"role": "user", "content": "<enable_plan>true</enable_plan> 帮我规划一下实现方案"}
    ]

    flags = extract_control_flags_from_messages(messages)

    assert flags == {"enable_plan": True}
    assert messages[0]["content"] == "帮我规划一下实现方案"


def test_extract_enable_plan_from_multimodal_message():
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "<enable_plan>true</enable_plan> 请先规划"},
                {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
            ],
        }
    ]

    flags = extract_control_flags_from_messages(messages)

    assert flags == {"enable_plan": True}
    assert messages[0]["content"][0]["type"] == "text"
    assert messages[0]["content"][0]["text"] == "请先规划"
    assert messages[0]["content"][1]["type"] == "image_url"


def test_extract_enable_plan_tag_only_message():
    messages = [
        {"role": "user", "content": "<enable_plan>true</enable_plan>"}
    ]

    flags = extract_control_flags_from_messages(messages)

    assert flags == {"enable_plan": True}
    assert messages[0]["content"] == ""

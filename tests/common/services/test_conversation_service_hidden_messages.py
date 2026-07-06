from common.services.conversation_service import _find_last_user_message_index


def test_find_last_user_message_skips_hidden_context_messages():
    messages = [
        {"role": "user", "content": "真正的用户输入", "message_id": "u1"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "工具注入的图片上下文"},
                {
                    "type": "image_url",
                    "image_url": {"url": "https://example.com/a.png"},
                },
            ],
            "message_id": "hidden-ctx",
            "metadata": {"hidden_from_chat": True, "tool_source": "analyze_image"},
        },
    ]

    assert _find_last_user_message_index(messages) == 0

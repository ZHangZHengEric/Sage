from common.utils.message_persistence import sanitize_messages_for_persistence


def test_sanitize_messages_removes_frozen_runtime_but_preserves_current_time():
    messages = [
        {
            "role": "user",
            "content": "hello",
            "metadata": {
                "keep": "value",
                "frozen_user_inference": {
                    "content": (
                        "<runtime_context>\n"
                        "<system_context>\n"
                        "<current_time>2026-07-05 12:00:00</current_time>\n"
                        "<private_workspace>/tmp/work</private_workspace>\n"
                        "</system_context>\n"
                        "</runtime_context>\n\n"
                        "<user_request>\nhello\n</user_request>"
                    ),
                    "metadata": {"runtime_context_injected": True},
                },
                "runtime_context_injected": True,
                "inference_view_only": True,
                "frozen_user_inference_version": 3,
            },
        }
    ]

    clean = sanitize_messages_for_persistence(messages)

    assert clean[0]["content"] == "hello"
    assert clean[0]["metadata"] == {
        "keep": "value",
        "current_time_context": "<current_time>2026-07-05 12:00:00</current_time>",
    }
    assert "frozen_user_inference" in messages[0]["metadata"]


def test_sanitize_messages_strips_runtime_context_from_user_content():
    messages = [
        {
            "role": "user",
            "content": (
                "<runtime_context>\n"
                "<system_context>\n"
                "<current_time>now</current_time>\n"
                "<workspace_files>files</workspace_files>\n"
                "</system_context>\n"
                "</runtime_context>\n\n"
                "<user_request>\nreal request\n</user_request>"
            ),
        }
    ]

    clean = sanitize_messages_for_persistence(messages)

    assert clean[0]["content"] == "real request"
    assert clean[0]["metadata"] == {
        "current_time_context": "<current_time>now</current_time>"
    }


def test_sanitize_messages_strips_multimodal_runtime_wrapper():
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "<runtime_context><system_context>"
                        "<current_time>now</current_time>"
                        "</system_context></runtime_context>\n\n"
                        "<user_request>\n"
                    ),
                },
                {"type": "text", "text": "describe this image"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,x"}},
                {"type": "text", "text": "\n</user_request>"},
            ],
        }
    ]

    clean = sanitize_messages_for_persistence(messages)

    assert clean[0]["content"] == [
        {"type": "text", "text": "describe this image"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,x"}},
    ]
    assert clean[0]["metadata"] == {
        "current_time_context": "<current_time>now</current_time>"
    }

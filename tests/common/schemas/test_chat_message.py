from common.schemas.chat import Message


def test_message_preserves_type_fields_for_runtime_context():
    message = Message(
        role="assistant",
        content="<system_triggered_run>context</system_triggered_run>",
        type="system_triggered_run",
        message_type="system_triggered_run",
    )

    payload = message.model_dump()

    assert payload["type"] == "system_triggered_run"
    assert payload["message_type"] == "system_triggered_run"


def test_message_preserves_guidance_metadata():
    message = Message(
        message_id="guidance-1",
        role="user",
        content="喝茶喝茶",
        metadata={
            "injected": True,
            "guidance_id": "guidance-1",
            "source": "guidance",
        },
    )

    payload = message.model_dump()

    assert payload["metadata"]["guidance_id"] == "guidance-1"
    assert payload["metadata"]["source"] == "guidance"

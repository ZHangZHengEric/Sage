from common.services.agui_v2_service import AguiEventTranslator


def test_translator_emits_text_lifecycle_and_usage_result() -> None:
    translator = AguiEventTranslator(thread_id="thread-1", run_id="run-1")

    events = translator.translate(
        {
            "role": "assistant",
            "type": "assistant_text",
            "message_id": "answer-1",
            "content": "hello",
        }
    )
    translator.translate(
        {
            "type": "token_usage",
            "metadata": {"token_usage": {"total_tokens": 12}},
        }
    )
    events.extend(translator.run_finished())

    assert [event["type"] for event in events] == [
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_END",
        "RUN_FINISHED",
    ]
    assert events[1]["delta"] == "hello"
    assert events[-1]["result"] == {"usage": {"total_tokens": 12}}


def test_translator_reassembles_streamed_tool_call_identity() -> None:
    translator = AguiEventTranslator(thread_id="thread-1", run_id="run-1")

    first = translator.translate(
        {
            "role": "assistant",
            "message_id": "answer-1",
            "tool_calls": [
                {
                    "index": 0,
                    "id": "call-1",
                    "function": {"name": "search", "arguments": '{"q"'},
                }
            ],
        }
    )
    second = translator.translate(
        {
            "role": "assistant",
            "message_id": "answer-1",
            "tool_calls": [{"index": 0, "function": {"arguments": ':"sage"}'}}],
        }
    )
    result = translator.translate(
        {
            "role": "tool",
            "message_id": "tool-result-1",
            "tool_call_id": "call-1",
            "content": "found",
        }
    )

    assert [event["type"] for event in first + second + result] == [
        "TOOL_CALL_START",
        "TOOL_CALL_ARGS",
        "TOOL_CALL_ARGS",
        "TOOL_CALL_END",
        "TOOL_CALL_RESULT",
    ]
    assert first[1]["delta"] == '{"q"'
    assert second[0]["delta"] == ':"sage"}'
    assert result[-1]["content"] == "found"


def test_translator_closes_reasoning_before_answer_text() -> None:
    translator = AguiEventTranslator(thread_id="thread-1", run_id="run-1")

    reasoning = translator.translate(
        {
            "role": "assistant",
            "message_id": "reasoning-1",
            "reasoning_content": "thinking",
        }
    )
    answer = translator.translate(
        {
            "role": "assistant",
            "message_id": "answer-1",
            "content": "done",
        }
    )

    assert [event["type"] for event in reasoning] == [
        "REASONING_START",
        "REASONING_MESSAGE_START",
        "REASONING_MESSAGE_CONTENT",
    ]
    assert [event["type"] for event in answer] == [
        "REASONING_MESSAGE_END",
        "REASONING_END",
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_CONTENT",
    ]


def test_translator_maps_progress_to_activity_snapshot() -> None:
    translator = AguiEventTranslator(thread_id="thread-1", run_id="run-1")

    events = translator.translate(
        {
            "type": "tool_progress",
            "tool_call_id": "call-1",
            "text": "running",
            "stream": "stdout",
            "closed": False,
        }
    )

    assert events == [
        {
            "type": "ACTIVITY_SNAPSHOT",
            "messageId": events[0]["messageId"],
            "activityType": "tool_progress",
            "content": {
                "toolCallId": "call-1",
                "text": "running",
                "stream": "stdout",
                "closed": False,
            },
            "replace": True,
        }
    ]

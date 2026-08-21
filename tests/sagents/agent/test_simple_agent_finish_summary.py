"""SimpleAgent turn_status 前置文本校验单测。

验证 turn_status 的「先说明再报告状态」契约。
"""

import asyncio
import json
from types import SimpleNamespace

from sagents.context.messages.message import (
    MessageChunk,
    MessageRole,
    MessageType,
    is_message_client_visible,
)
from sagents.context.messages.message_manager import MessageManager
from sagents.agent.simple_agent import (
    DEFAULT_REPEAT_PATTERN_MAX_HITS,
    REPEAT_PATTERN_MAX_HITS_ENV,
    SimpleAgent,
    TaskCompleteDecision,
    _get_system_prefix,
)
from sagents.utils.prompt_manager import PromptManager


class _DummyModel:
    async def astream(self, *args, **kwargs):  # pragma: no cover
        yield None


def _agent():
    return SimpleAgent(model=_DummyModel(), model_config={})


def test_repeat_pattern_max_hits_defaults_to_three(monkeypatch):
    monkeypatch.delenv(REPEAT_PATTERN_MAX_HITS_ENV, raising=False)

    assert _agent().max_repeat_pattern_hits == DEFAULT_REPEAT_PATTERN_MAX_HITS == 3


def test_repeat_pattern_max_hits_uses_env(monkeypatch):
    monkeypatch.setenv(REPEAT_PATTERN_MAX_HITS_ENV, "4")

    assert _agent().max_repeat_pattern_hits == 4


def test_repeat_pattern_max_hits_invalid_env_falls_back(monkeypatch):
    for value in ["", "abc", "0", "-2"]:
        monkeypatch.setenv(REPEAT_PATTERN_MAX_HITS_ENV, value)

        assert _agent().max_repeat_pattern_hits == DEFAULT_REPEAT_PATTERN_MAX_HITS


def _llm_chunk(*, content=None, tool_calls=None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=content, tool_calls=tool_calls)
            )
        ]
    )


def _turn_status_tool_call(
    call_id="call_ts",
    name="turn_status",
    arguments='{"status":"need_user_input","note":"waiting"}',
):
    return SimpleNamespace(
        id=call_id,
        index=0,
        type="function",
        function=SimpleNamespace(
            name=name,
            arguments=arguments,
        ),
    )


async def _collect_llm_response(agent, **kwargs):
    collected = []
    async for chunks, is_complete in agent._call_llm_and_process_response(**kwargs):
        collected.extend(chunks)
        if is_complete:
            break
    return collected


def _base_messages():
    return [
        MessageChunk(
            role=MessageRole.USER.value,
            content="你好",
            message_type=MessageType.USER_INPUT.value,
        ),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="你好，直接说需求。",
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
    ]


def _turn_status_tools_json():
    return [{"function": {"name": "turn_status"}}]


def _patch_prepared_messages(monkeypatch, agent, messages):
    async def _fake_prepare_messages_for_llm(messages_input, session_id):
        yield messages, True

    monkeypatch.setattr(
        agent, "_prepare_messages_for_llm", _fake_prepare_messages_for_llm
    )


def _patch_tool_handler(monkeypatch, agent, seen_tool_calls):
    async def _fake_handle_tool_calls(**kwargs):
        seen_tool_calls.update(kwargs["tool_calls"])
        yield (
            [
                MessageChunk(
                    role=MessageRole.TOOL.value,
                    content='{"should_end": true}',
                    tool_call_id="call_ts",
                    message_type=MessageType.TOOL_CALL_RESULT.value,
                )
            ],
            True,
        )

    monkeypatch.setattr(agent, "_handle_tool_calls", _fake_handle_tool_calls)


def _loop_session_context(max_loop_count=4):
    stored_messages = []
    msg_manager = SimpleNamespace(
        get_recent_loop_signatures=lambda: [],
        add_loop_signature=lambda signature: None,
    )
    context = SimpleNamespace(
        agent_config={"max_loop_count": max_loop_count},
        audit_status={},
        message_manager=msg_manager,
        get_language=lambda: "zh",
        stored_messages=stored_messages,
    )

    def _add_messages(messages):
        stored_messages.extend(messages if isinstance(messages, list) else [messages])

    context.add_messages = _add_messages
    return context


def test_status_only_turn_status_response_suppresses_duplicate_text(monkeypatch):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "turn_status")
    agent = _agent()
    messages = _base_messages()
    saved_content = []
    seen_tool_calls = {}
    _patch_prepared_messages(monkeypatch, agent, messages)
    _patch_tool_handler(monkeypatch, agent, seen_tool_calls)
    monkeypatch.setattr(
        "sagents.agent.simple_agent.save_agent_response_content",
        lambda content, session_id: saved_content.append(content),
    )

    def _fake_call_llm_streaming(*args, **kwargs):
        async def _gen():
            yield _llm_chunk(content="已收到。把你的目标发来。")
            yield _llm_chunk(tool_calls=[_turn_status_tool_call()])

        return _gen()

    monkeypatch.setattr(agent, "_call_llm_streaming", _fake_call_llm_streaming)

    chunks = asyncio.run(
        _collect_llm_response(
            agent,
            messages_input=messages,
            tools_json=_turn_status_tools_json(),
            tool_manager=None,
            session_id="s-status-only",
            force_tool_choice_required=True,
        )
    )

    assert "call_ts" in seen_tool_calls
    assert saved_content == []
    assert all(chunk.content != "已收到。把你的目标发来。" for chunk in chunks)
    assert any(chunk.role == MessageRole.TOOL.value for chunk in chunks)


def test_non_status_only_turn_status_response_keeps_user_visible_text(monkeypatch):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "turn_status")
    agent = _agent()
    messages = _base_messages()
    saved_content = []
    seen_tool_calls = {}
    _patch_prepared_messages(monkeypatch, agent, messages)
    _patch_tool_handler(monkeypatch, agent, seen_tool_calls)
    monkeypatch.setattr(
        "sagents.agent.simple_agent.save_agent_response_content",
        lambda content, session_id: saved_content.append(content),
    )

    def _fake_call_llm_streaming(*args, **kwargs):
        async def _gen():
            yield _llm_chunk(content="普通回复正文。")
            yield _llm_chunk(tool_calls=[_turn_status_tool_call()])

        return _gen()

    monkeypatch.setattr(agent, "_call_llm_streaming", _fake_call_llm_streaming)

    chunks = asyncio.run(
        _collect_llm_response(
            agent,
            messages_input=messages,
            tools_json=_turn_status_tools_json(),
            tool_manager=None,
            session_id="s-normal",
            force_tool_choice_required=False,
        )
    )

    assert "call_ts" in seen_tool_calls
    assert saved_content == ["普通回复正文。"]
    assert any(chunk.content == "普通回复正文。" for chunk in chunks)


def test_status_only_text_without_tool_call_is_hidden_and_requests_recovery(
    monkeypatch,
):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "turn_status")
    agent = _agent()
    messages = _base_messages()
    saved_content = []
    _patch_prepared_messages(monkeypatch, agent, messages)
    monkeypatch.setattr(
        "sagents.agent.simple_agent.save_agent_response_content",
        lambda content, session_id: saved_content.append(content),
    )

    def _fake_call_llm_streaming(*args, **kwargs):
        async def _gen():
            yield _llm_chunk(content="这句也不应该展示。")

        return _gen()

    monkeypatch.setattr(agent, "_call_llm_streaming", _fake_call_llm_streaming)

    chunks = asyncio.run(
        _collect_llm_response(
            agent,
            messages_input=messages,
            tools_json=_turn_status_tools_json(),
            tool_manager=None,
            session_id="s-status-only-no-tool",
            force_tool_choice_required=True,
        )
    )

    assert saved_content == []
    assert all(chunk.content != "这句也不应该展示。" for chunk in chunks)
    assert len(chunks) == 1
    assert chunks[0].message_type == MessageType.ASSISTANT_TEXT.value
    assert "Agent is stuck in a loop" in chunks[0].content
    assert "<questionnaire>" in chunks[0].content
    assert chunks[0].metadata["needs_user_input"] is True
    assert chunks[0].metadata["stop_reason"] == "turn_status_protocol_loop"


def test_returns_true_when_recent_assistant_text_exists():
    msgs = [
        MessageChunk(
            role=MessageRole.USER.value,
            content="跑一下",
            message_type=MessageType.USER_INPUT.value,
        ),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="任务完成，文件已生成。",
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
    ]
    assert _agent()._has_recent_assistant_summary(msgs) is True


def test_returns_false_when_no_assistant_text_since_last_user():
    msgs = [
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="老的总结",
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
        MessageChunk(
            role=MessageRole.USER.value,
            content="再来一次",
            message_type=MessageType.USER_INPUT.value,
        ),
    ]
    assert _agent()._has_recent_assistant_summary(msgs) is False


def test_user_message_acts_as_boundary():
    msgs = [
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="老总结",
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
        MessageChunk(
            role=MessageRole.USER.value,
            content="新需求",
            message_type=MessageType.USER_INPUT.value,
        ),
        MessageChunk(
            role="tool",
            content="ok",
            tool_call_id="x",
            message_type=MessageType.TOOL_CALL_RESULT.value,
        ),
    ]
    assert _agent()._has_recent_assistant_summary(msgs) is False


def test_blank_assistant_content_not_counted():
    msgs = [
        MessageChunk(
            role=MessageRole.USER.value,
            content="hi",
            message_type=MessageType.USER_INPUT.value,
        ),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="   \n",
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
    ]
    assert _agent()._has_recent_assistant_summary(msgs) is False


def test_empty_history_returns_false():
    assert _agent()._has_recent_assistant_summary([]) is False


def test_trailing_tool_result_blocks_summary():
    """末尾是 tool 消息：模型刚跑完工具，还没机会写总结，应判定无总结。

    复现实际故障：assistant 输出过渡话 + todo_write tool_calls，tool 返回后模型
    立刻只调 turn_status —— 旧规则会把那段过渡话误判为总结。
    """
    msgs = [
        MessageChunk(
            role=MessageRole.USER.value,
            content="跑测试",
            message_type=MessageType.USER_INPUT.value,
        ),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="完美！现在让我更新任务清单并生成最终报告：",
            tool_calls=[
                {
                    "id": "t1",
                    "type": "function",
                    "function": {"name": "todo_write", "arguments": "{}"},
                }
            ],
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
        MessageChunk(
            role="tool",
            content="ok",
            tool_call_id="t1",
            message_type=MessageType.TOOL_CALL_RESULT.value,
        ),
    ]
    assert _agent()._has_recent_assistant_summary(msgs) is False


def test_assistant_with_tool_calls_does_not_count_as_summary():
    """assistant 既有 content 又有 tool_calls：那段文字是过渡话不是总结。"""
    msgs = [
        MessageChunk(
            role=MessageRole.USER.value,
            content="干活",
            message_type=MessageType.USER_INPUT.value,
        ),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="好的，我先列一下 todo：",
            tool_calls=[
                {
                    "id": "t2",
                    "type": "function",
                    "function": {"name": "todo_write", "arguments": "{}"},
                }
            ],
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
    ]
    assert _agent()._has_recent_assistant_summary(msgs) is False


def test_clean_trailing_assistant_text_counts_as_summary():
    """合法形态：tool 之后模型先发一条纯文本总结，再下一次 LLM 调用 turn_status。"""
    msgs = [
        MessageChunk(
            role=MessageRole.USER.value,
            content="干活",
            message_type=MessageType.USER_INPUT.value,
        ),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="开工：",
            tool_calls=[
                {
                    "id": "t3",
                    "type": "function",
                    "function": {"name": "todo_write", "arguments": "{}"},
                }
            ],
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
        MessageChunk(
            role="tool",
            content="ok",
            tool_call_id="t3",
            message_type=MessageType.TOOL_CALL_RESULT.value,
        ),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="任务全部完成：todo 已更新，关键产物 X、Y。",
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
    ]
    assert _agent()._has_recent_assistant_summary(msgs) is True


def test_plain_text_without_tool_call_requests_turn_status_retry(monkeypatch):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "turn_status")
    chunks = [
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="任务已经完成，结果如下。",
            message_type=MessageType.ASSISTANT_TEXT.value,
        )
    ]
    tools_json = [{"function": {"name": "turn_status"}}]

    assert (
        _agent()._should_request_turn_status_after_text_response(chunks, tools_json)
        is True
    )


def test_tool_call_response_does_not_request_turn_status_retry():
    chunks = [
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content=None,
            tool_calls=[
                {
                    "id": "t1",
                    "type": "function",
                    "function": {"name": "todo_write", "arguments": "{}"},
                }
            ],
            message_type=MessageType.TOOL_CALL.value,
        )
    ]
    tools_json = [{"function": {"name": "turn_status"}}]

    assert (
        _agent()._should_request_turn_status_after_text_response(chunks, tools_json)
        is False
    )


def test_missing_turn_status_tool_does_not_request_retry():
    chunks = [
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="仅文字输出。",
            message_type=MessageType.ASSISTANT_TEXT.value,
        )
    ]

    assert _agent()._should_request_turn_status_after_text_response(chunks, []) is False


def test_committed_next_step_is_classified_by_llm_judge(monkeypatch):
    agent = _agent()
    captured = {}

    async def _fake_llm_streaming(*args, **kwargs):
        captured["step_name"] = kwargs["step_name"]
        yield _llm_chunk(
            content='{"decision":"continue","reason":"promised next action"}'
        )

    monkeypatch.setattr(agent, "_call_llm_streaming", _fake_llm_streaming)

    msg_manager = SimpleNamespace(
        context_budget_manager=SimpleNamespace(budget_info={"active_budget": 3000}),
    )
    session_context = SimpleNamespace(
        message_manager=msg_manager,
        get_language=lambda: "en",
    )
    messages = _base_messages() + [
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="Next, I will assemble the final video now.",
            message_type=MessageType.ASSISTANT_TEXT.value,
        )
    ]

    assert (
        asyncio.run(
            agent._is_task_complete(
                messages_input=messages,
                session_id="s-commit",
                tool_manager=None,
                session_context=session_context,  # pyright: ignore[reportArgumentType]
            )
        )
        is False
    )
    assert captured["step_name"] == "task_complete_judge"


def test_screenshot_style_create_file_promise_is_classified_as_continue(monkeypatch):
    agent = _agent()
    captured = {}

    async def _fake_llm_streaming(*args, **kwargs):
        captured["prompt"] = kwargs["messages"][0]["content"]
        yield _llm_chunk(content='{"decision":"continue","reason":"网页文件尚未创建"}')

    monkeypatch.setattr(agent, "_call_llm_streaming", _fake_llm_streaming)
    session_context = SimpleNamespace(
        message_manager=SimpleNamespace(
            context_budget_manager=SimpleNamespace(budget_info={"active_budget": 3000})
        ),
        get_language=lambda: "zh",
    )
    messages = _base_messages() + [
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content=(
                "让我先把回答说清楚，并直接把网页版做出来给她用。"
                "先创建网页版文件。我先把清单做成可打勾网页版，并把文件整理好。"
            ),
            message_type=MessageType.ASSISTANT_TEXT.value,
        )
    ]

    decision = asyncio.run(
        agent._get_task_complete_decision(
            messages_input=messages,
            session_id="s-screenshot-regression",
            tool_manager=None,
            session_context=session_context,  # pyright: ignore[reportArgumentType]
        )
    )

    assert decision.task_interrupted is False
    assert "我先把清单做成可打勾网页版" in captured["prompt"]
    assert "承诺后续动作" in captured["prompt"]


def test_inline_questionnaire_protocol_detection_excludes_responses():
    agent = _agent()
    request_blocks = [
        '<yiii-questionnaire>{"questions":[]}</yiii-questionnaire>',
        '<foo-questionnaire>{"questions":[]}</foo-questionnaire>',
        "```sage-questionnaire\nquestions: []\n```",
        "'''ling-questionnaire\nquestions: []\n'''",
        "<questionnaire>{}</questionnaire>",
        "&lt;movo-questionnaire&gt;{}&lt;/movo-questionnaire&gt;",
    ]

    for content in request_blocks:
        assert agent._content_has_inline_questionnaire(content) is True

    response_blocks = [
        '<yiii-questionnaire-response>{"answers":[]}</yiii-questionnaire-response>',
        "```questionnaire-response\nanswers: []\n```",
        "The docs mention movo-questionnaire but do not ask anything.",
    ]
    for content in response_blocks:
        assert agent._content_has_inline_questionnaire(content) is False


def test_ling_action_protocol_detection_requires_opening_tag():
    agent = _agent()

    assert agent._content_has_ling_action(
        '<ling-action label="继续" prompt="继续处理" />'
    )
    assert agent._content_has_ling_action(
        '&lt;ling-action label="继续" prompt="继续处理" /&gt;'
    )
    assert agent._content_has_ling_action("</ling-action>") is False
    assert agent._content_has_ling_action(
        "文档里提到了 ling-action，但没有输出协议标签。"
    ) is False
    assert agent._content_has_ling_action(
        '<other-action label="继续" prompt="继续处理" />'
    ) is False


def test_ling_action_forces_stop_without_calling_judge(monkeypatch):
    agent = _agent()

    async def _fail_llm(*args, **kwargs):
        raise AssertionError("ling-action must bypass completion judge")
        yield  # pragma: no cover

    monkeypatch.setattr(agent, "_call_llm_streaming", _fail_llm)
    session_context = SimpleNamespace(
        audit_status={},
        message_manager=SimpleNamespace(
            context_budget_manager=SimpleNamespace(budget_info={"active_budget": 3000})
        ),
        get_language=lambda: "zh",
    )
    messages = _base_messages() + [
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="",
            tool_calls=[
                {
                    "id": "incidental-read",
                    "type": "function",
                    "function": {"name": "file_read", "arguments": "{}"},
                }
            ],
            message_type=MessageType.TOOL_CALL.value,
        ),
        MessageChunk(
            role=MessageRole.TOOL.value,
            content='{"status":"success","content":"internal context"}',
            tool_call_id="incidental-read",
            message_type=MessageType.TOOL_CALL_RESULT.value,
        ),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content=(
                "当前回应已经完整。你今晚感觉怎么样？用户之后可能回复，但无需继续执行。\n"
                '<ling-action label="继续聊" prompt="继续聊聊" />'
            ),
            message_type=MessageType.ASSISTANT_TEXT.value,
        )
    ]

    decision = asyncio.run(
        agent._get_task_complete_decision(
            messages_input=messages,
            session_id="ling-action-stop",
            tool_manager=None,
            session_context=session_context,  # pyright: ignore[reportArgumentType]
        )
    )

    assert decision.task_interrupted is True
    assert decision.reason.startswith("ling-action marks a closed reply")
    assert session_context.audit_status["completion_status"] == "need_user_input"


def test_inline_questionnaire_forces_need_user_input_with_open_todo(monkeypatch):
    agent = _agent()

    async def _fail_llm(*args, **kwargs):
        raise AssertionError("inline questionnaire must bypass completion judge")
        yield  # pragma: no cover

    monkeypatch.setattr(agent, "_call_llm_streaming", _fail_llm)
    session_context = SimpleNamespace(
        audit_status={},
        message_manager=SimpleNamespace(
            context_budget_manager=SimpleNamespace(budget_info={"active_budget": 3000})
        ),
        get_language=lambda: "zh",
    )
    messages = [
        MessageChunk(
            role=MessageRole.USER.value,
            content="继续实现功能",
            message_type=MessageType.USER_INPUT.value,
        ),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="",
            tool_calls=[
                {
                    "id": "todo-open-questionnaire",
                    "type": "function",
                    "function": {"name": "todo_write", "arguments": "{}"},
                }
            ],
            message_type=MessageType.TOOL_CALL.value,
        ),
        MessageChunk(
            role=MessageRole.TOOL.value,
            content=(
                '{"tasks":[{"id":"implement","name":"实现功能",'
                '"status":"in_progress"}]}'
            ),
            tool_call_id="todo-open-questionnaire",
            message_type=MessageType.TOOL_CALL_RESULT.value,
        ),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content=(
                "需要你选择部署目标。\n"
                '<sage-questionnaire>{"title":"部署目标","questions":[]}'
                "</sage-questionnaire>"
            ),
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
    ]

    decision = asyncio.run(
        agent._get_task_complete_decision(
            messages_input=messages,
            session_id="todo-questionnaire",
            tool_manager=None,
            session_context=session_context,  # pyright: ignore[reportArgumentType]
        )
    )

    assert decision.task_interrupted is True
    assert decision.reason == "inline questionnaire requires user input"
    assert session_context.audit_status["completion_status"] == "need_user_input"


def test_trailing_question_mark_uses_protocol_aware_judge(
    monkeypatch,
):
    agent = _agent()
    captured = {}

    async def _fake_system_prompt_build(**_kwargs):
        return (
            "Whenever any user response is required, call questionnaire_async. "
            "Never replace a questionnaire with an ordinary prose question."
        )

    async def _fake_llm(*args, **kwargs):
        captured["prompt"] = kwargs["messages"][0]["content"]
        yield _llm_chunk(
            content=(
                '{"decision":"continue","reason":'
                '"questionnaire_async was required but was not called"}'
            )
        )

    monkeypatch.setattr(
        agent, "prepare_llm_system_prompt_text", _fake_system_prompt_build
    )
    monkeypatch.setattr(agent, "_call_llm_streaming", _fake_llm)
    session_context = SimpleNamespace(
        audit_status={},
        message_manager=SimpleNamespace(
            context_budget_manager=SimpleNamespace(budget_info={"active_budget": 3000})
        ),
        get_language=lambda: "zh",
    )
    messages = [
        MessageChunk(
            role=MessageRole.USER.value,
            content="继续处理任务",
            message_type=MessageType.USER_INPUT.value,
        ),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="请提供目标服务器地址？",
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
    ]

    decision = asyncio.run(
        agent._get_task_complete_decision(
            messages_input=messages,
            session_id="question-mark",
            tool_manager=None,
            session_context=session_context,  # pyright: ignore[reportArgumentType]
            tools_json=[
                {
                    "type": "function",
                    "function": {"name": "questionnaire_async"},
                }
            ],
        )
    )

    assert decision.task_interrupted is False
    assert "请提供目标服务器地址？" in captured["prompt"]
    assert '["questionnaire_async"]' in captured["prompt"]
    assert "completion_status" not in session_context.audit_status


def test_non_trailing_question_mark_still_uses_judge(monkeypatch):
    agent = _agent()
    judge_calls = []

    async def _fake_llm_streaming(*args, **kwargs):
        judge_calls.append((args, kwargs))
        yield _llm_chunk(content='{"decision":"continue","reason":"仍会继续处理"}')

    monkeypatch.setattr(agent, "_call_llm_streaming", _fake_llm_streaming)
    session_context = SimpleNamespace(
        audit_status={},
        message_manager=SimpleNamespace(
            context_budget_manager=SimpleNamespace(budget_info={"active_budget": 3000})
        ),
        get_language=lambda: "zh",
    )
    messages = [
        MessageChunk(
            role=MessageRole.USER.value,
            content="继续处理任务",
            message_type=MessageType.USER_INPUT.value,
        ),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="服务地址是什么？我会先检查默认配置。",
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
    ]

    decision = asyncio.run(
        agent._get_task_complete_decision(
            messages_input=messages,
            session_id="non-trailing-question-mark",
            tool_manager=None,
            session_context=session_context,  # pyright: ignore[reportArgumentType]
        )
    )

    assert decision.task_interrupted is False
    assert len(judge_calls) == 1
    assert "completion_status" not in session_context.audit_status


def test_tool_result_still_continues_after_older_assistant_question(monkeypatch):
    agent = _agent()
    session_context = SimpleNamespace(
        audit_status={},
        message_manager=SimpleNamespace(
            context_budget_manager=SimpleNamespace(budget_info={"active_budget": 3000})
        ),
        get_language=lambda: "zh",
    )
    messages = [
        MessageChunk(
            role=MessageRole.USER.value,
            content="检查服务状态",
            message_type=MessageType.USER_INPUT.value,
        ),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="服务地址是什么？我先尝试读取默认配置。",
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
        MessageChunk(
            role=MessageRole.TOOL.value,
            content='{"status":"running"}',
            tool_call_id="check-service",
            message_type=MessageType.TOOL_CALL_RESULT.value,
        ),
    ]

    decision = asyncio.run(
        agent._get_task_complete_decision(
            messages_input=messages,
            session_id="question-before-tool",
            tool_manager=None,
            session_context=session_context,  # pyright: ignore[reportArgumentType]
        )
    )

    assert decision.task_interrupted is False
    assert "completion_status" not in session_context.audit_status


def test_structured_judge_decision_takes_priority_over_legacy_boolean():
    agent = _agent()

    assert (
        agent._task_interrupted_from_judge_result(
            {
                "decision": "continue",
                "task_interrupted": True,
                "reason": "仍需执行",
            },
        )
        is False
    )
    assert (
        agent._task_interrupted_from_judge_result(
            {"decision": "completed", "reason": "原始目标已满足"},
        )
        is True
    )
    assert (
        agent._task_interrupted_from_judge_result(
            {"task_interrupted": True, "reason": "need user input"},
        )
        is True
    )


def test_invalid_structured_decision_fails_closed_to_continue():
    agent = _agent()

    invalid_results = [
        {"decision": "done"},
        {"decision": "done", "task_interrupted": True},
        {"decision": "done", "reason": "need user input"},
        {"decision": ""},
        {"decision": None, "task_interrupted": True},
    ]

    for result in invalid_results:
        assert agent._task_interrupted_from_judge_result(result) is False


def test_structured_need_user_input_plain_request_is_accepted(monkeypatch):
    agent = _agent()

    async def _never_must_continue(messages):
        return False

    async def _fake_llm_streaming(*args, **kwargs):
        yield _llm_chunk(
            content=('{"decision":"need_user_input","reason":"需要用户确认技术方案"}')
        )

    monkeypatch.setattr(agent, "_must_continue_by_rules", _never_must_continue)
    monkeypatch.setattr(agent, "_call_llm_streaming", _fake_llm_streaming)
    session_context = SimpleNamespace(
        message_manager=SimpleNamespace(
            context_budget_manager=SimpleNamespace(budget_info={"active_budget": 3000})
        ),
        get_language=lambda: "zh",
    )
    messages = _base_messages() + [
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="请上传视频文件或提供可公开访问的 .mp4 直链。",
            message_type=MessageType.ASSISTANT_TEXT.value,
        )
    ]

    decision = asyncio.run(
        agent._get_task_complete_decision(
            messages_input=messages,
            session_id="s-fake-user-wait",
            tool_manager=None,
            session_context=session_context,  # pyright: ignore[reportArgumentType]
        )
    )

    assert decision.task_interrupted is True


def test_structured_need_user_input_with_concrete_question_is_accepted(monkeypatch):
    agent = _agent()

    async def _never_must_continue(messages):
        return False

    async def _fake_llm_streaming(*args, **kwargs):
        yield _llm_chunk(
            content=('{"decision":"need_user_input","reason":"缺少目标服务器地址"}')
        )

    monkeypatch.setattr(agent, "_must_continue_by_rules", _never_must_continue)
    monkeypatch.setattr(agent, "_call_llm_streaming", _fake_llm_streaming)
    session_context = SimpleNamespace(
        message_manager=SimpleNamespace(
            context_budget_manager=SimpleNamespace(budget_info={"active_budget": 3000})
        ),
        get_language=lambda: "zh",
    )
    messages = _base_messages() + [
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="目标服务器地址是什么？当前上下文中没有这个信息。",
            message_type=MessageType.ASSISTANT_TEXT.value,
        )
    ]

    decision = asyncio.run(
        agent._get_task_complete_decision(
            messages_input=messages,
            session_id="s-real-user-wait",
            tool_manager=None,
            session_context=session_context,  # pyright: ignore[reportArgumentType]
        )
    )

    assert decision.task_interrupted is True


def test_task_complete_decision_captures_continue_reason(monkeypatch):
    agent = _agent()

    async def _fake_llm_streaming(*args, **kwargs):
        yield _llm_chunk(
            content='{"task_interrupted": false, "reason": "more clips pending"}'
        )

    monkeypatch.setattr(agent, "_call_llm_streaming", _fake_llm_streaming)

    msg_manager = SimpleNamespace(
        context_budget_manager=SimpleNamespace(budget_info={"active_budget": 3000}),
    )
    session_context = SimpleNamespace(
        message_manager=msg_manager,
        get_language=lambda: "en",
    )

    decision = asyncio.run(
        agent._get_task_complete_decision(
            messages_input=_base_messages()
            + [
                MessageChunk(
                    role=MessageRole.ASSISTANT.value,
                    content="Progress update.",
                    message_type=MessageType.DO_SUBTASK_RESULT.value,
                )
            ],
            session_id="s-reason",
            tool_manager=None,
            session_context=session_context,  # pyright: ignore[reportArgumentType]
        )
    )

    assert decision == TaskCompleteDecision(
        task_interrupted=False, reason="more clips pending"
    )
    assert agent._continuation_reason_from_decision(decision) == "more clips pending"
    assert (
        agent._continuation_reason_from_decision(
            TaskCompleteDecision(task_interrupted=False, reason="   ")
        )
        is None
    )
    assert (
        agent._continuation_reason_from_decision(
            TaskCompleteDecision(task_interrupted=True, reason="done")
        )
        is None
    )
    assert (
        asyncio.run(
            agent._is_task_complete(
                messages_input=_base_messages(),
                session_id="s-reason",
                tool_manager=None,
                session_context=session_context,  # pyright: ignore[reportArgumentType]
            )
        )
        is False
    )


def test_task_complete_decision_ignores_non_string_reason(monkeypatch):
    agent = _agent()

    async def _fake_llm_streaming(*args, **kwargs):
        yield _llm_chunk(content='{"task_interrupted": false, "reason": null}')

    monkeypatch.setattr(agent, "_call_llm_streaming", _fake_llm_streaming)

    msg_manager = SimpleNamespace(
        context_budget_manager=SimpleNamespace(budget_info={"active_budget": 3000}),
    )
    session_context = SimpleNamespace(
        message_manager=msg_manager,
        get_language=lambda: "en",
    )

    decision = asyncio.run(
        agent._get_task_complete_decision(
            messages_input=_base_messages()
            + [
                MessageChunk(
                    role=MessageRole.ASSISTANT.value,
                    content="Progress update.",
                    message_type=MessageType.DO_SUBTASK_RESULT.value,
                )
            ],
            session_id="s-null-reason",
            tool_manager=None,
            session_context=session_context,  # pyright: ignore[reportArgumentType]
        )
    )

    assert decision == TaskCompleteDecision(task_interrupted=False, reason="")
    assert agent._continuation_reason_from_decision(decision) is None


def test_task_complete_decision_parses_string_boolean(monkeypatch):
    agent = _agent()

    async def _fake_llm_streaming(*args, **kwargs):
        yield _llm_chunk(
            content='{"task_interrupted": "false", "reason": "more clips pending"}'
        )

    monkeypatch.setattr(agent, "_call_llm_streaming", _fake_llm_streaming)

    msg_manager = SimpleNamespace(
        context_budget_manager=SimpleNamespace(budget_info={"active_budget": 3000}),
    )
    session_context = SimpleNamespace(
        message_manager=msg_manager,
        get_language=lambda: "en",
    )

    decision = asyncio.run(
        agent._get_task_complete_decision(
            messages_input=_base_messages()
            + [
                MessageChunk(
                    role=MessageRole.ASSISTANT.value,
                    content="Progress update.",
                    message_type=MessageType.DO_SUBTASK_RESULT.value,
                )
            ],
            session_id="s-string-bool",
            tool_manager=None,
            session_context=session_context,  # pyright: ignore[reportArgumentType]
        )
    )

    assert decision == TaskCompleteDecision(
        task_interrupted=False, reason="more clips pending"
    )
    assert agent._parse_task_interrupted_value("true") is True
    assert agent._parse_task_interrupted_value("false") is False
    assert agent._parse_task_interrupted_value("yes") is False


def test_direct_request_appends_continuation_guidance_request_only(monkeypatch):
    agent = _agent()
    captured = {}
    original_messages = _base_messages()
    prepared_messages = list(original_messages)
    _patch_prepared_messages(monkeypatch, agent, prepared_messages)

    async def _fake_prepare_llm_request_messages(**kwargs):
        return list(kwargs["history_messages"])

    async def _fake_llm_streaming(*args, **kwargs):
        captured["messages"] = kwargs["messages"]
        yield _llm_chunk(content="ok")

    monkeypatch.setattr(
        agent, "prepare_llm_request_messages", _fake_prepare_llm_request_messages
    )
    monkeypatch.setattr(agent, "_call_llm_streaming", _fake_llm_streaming)

    chunks = asyncio.run(
        _collect_llm_response(
            agent,
            messages_input=original_messages,
            tools_json=[],
            tool_manager=None,
            session_id="s-guidance",
            direct_response_state={},
            continuation_reason="  more   <clips>   pending  ",
        )
    )

    assert len(original_messages) == 2
    assert len(prepared_messages) == 2
    assert captured["messages"][:-1] == prepared_messages
    guidance = captured["messages"][-1]
    assert guidance.role == MessageRole.USER.value
    assert "Continue because: more [clips] pending" in guidance.content
    assert "Do not mention it" in guidance.content
    assert all(
        "runtime_continuation_guidance" not in (chunk.content or "") for chunk in chunks
    )


class _ToolNameManager:
    def __init__(self, names):
        self._names = names

    def list_all_tools_name(self):
        return self._names


def test_system_prefix_omits_turn_status_contract_in_llm_judge_mode(monkeypatch):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "llm_judge")

    prompt = _get_system_prefix(_ToolNameManager(["dudu_generate_route_scheme"]), "en")  # pyright: ignore[reportArgumentType]

    assert "turn_status" not in prompt
    assert "Task Management Requirements" not in prompt


def test_system_prefix_includes_turn_status_contract_in_turn_status_mode(monkeypatch):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "turn_status")

    prompt = _get_system_prefix(_ToolNameManager(["todo_write"]), "en")  # pyright: ignore[reportArgumentType]

    assert "turn_status" in prompt
    assert "Task Management Requirements" in prompt
    assert "Completion and Tool-Continuation Rules" not in prompt


def test_task_completion_mode_turn_status_enables_turn_status_contract(monkeypatch):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "turn_status")

    prompt = _get_system_prefix(_ToolNameManager(["turn_status"]), "en")  # pyright: ignore[reportArgumentType]

    assert "turn_status" in prompt
    assert _agent()._turn_status_enabled() is True


def test_task_completion_mode_llm_judge_disables_turn_status_contract(monkeypatch):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "llm_judge")
    tool_manager = SimpleNamespace(list_all_tools_name=lambda: ["turn_status"])

    prompt = _get_system_prefix(tool_manager, "zh")

    assert "turn_status" not in prompt
    assert "完成与工具延续规则" not in prompt
    assert _agent()._turn_status_enabled() is False


def test_task_complete_judge_includes_base_system_and_current_tool_names(
    monkeypatch,
):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "llm_judge")
    agent = SimpleAgent(
        model=_DummyModel(),
        model_config={},
        system_prefix="unused test system",
    )
    captured = {}

    async def _never_must_continue(messages):
        return False

    async def _fake_system_prompt_build(**kwargs):
        captured["system_kwargs"] = kwargs
        return "Agent system requires questionnaire_async for every user response."

    async def _fake_llm_streaming(*args, **kwargs):
        captured["llm_messages"] = kwargs["messages"]
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content='{"task_interrupted": true, "reason": "done"}'
                    )
                )
            ]
        )

    monkeypatch.setattr(agent, "_must_continue_by_rules", _never_must_continue)
    monkeypatch.setattr(
        agent, "prepare_llm_system_prompt_text", _fake_system_prompt_build
    )
    monkeypatch.setattr(agent, "_call_llm_streaming", _fake_llm_streaming)

    msg_manager = SimpleNamespace(
        context_budget_manager=SimpleNamespace(budget_info={"active_budget": 3000}),
    )
    session_context = SimpleNamespace(
        message_manager=msg_manager,
        get_language=lambda: "en",
    )
    tool_manager = _ToolNameManager(["hidden_global_tool"])
    tools_json = [
        {"type": "function", "function": {"name": "z_tool"}},
        {"type": "function", "function": {"name": "questionnaire_async"}},
    ]
    messages = [
        MessageChunk(
            role=MessageRole.USER.value,
            content="start",
            message_type=MessageType.USER_INPUT.value,
        ),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="done",
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
    ]

    assert (
        asyncio.run(
            agent._is_task_complete(
                messages_input=messages,
                session_id="s1",
                tool_manager=tool_manager,  # pyright: ignore[reportArgumentType]
                session_context=session_context,  # pyright: ignore[reportArgumentType]
                tools_json=tools_json,
            )
        )
        is True
    )
    prompt = captured["llm_messages"][0]["content"]
    assert captured["system_kwargs"]["include_sections"] == [
        "role_definition",
        "AGENT.MD",
    ]
    assert "Agent system requires questionnaire_async" in prompt
    assert '["questionnaire_async", "z_tool"]' in prompt
    assert "hidden_global_tool" not in prompt
    assert "<active_skills>" not in prompt
    assert "<available_skills>" not in prompt
    assert "<system_context>" not in prompt
    assert "<workspace_files>" not in prompt
    assert "user: start" in prompt
    assert "assistant: done" in prompt
    assert prompt.index("## Priority rules") < prompt.index(
        "<agent_system_requirements>"
    )
    assert prompt.index("<agent_system_requirements>") < prompt.index(
        "<available_tools>"
    )
    assert prompt.index("<available_tools>") < prompt.index("user: start")


def test_task_complete_judge_marks_missing_required_questionnaire_as_continue(
    monkeypatch,
):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "llm_judge")
    agent = _agent()
    captured = {}

    async def _never_must_continue(messages):
        return False

    async def _fake_system_prompt_build(**_kwargs):
        return (
            "Whenever any user response is required, call questionnaire_async. "
            "Never replace a questionnaire with an ordinary prose question."
        )

    async def _fake_llm_streaming(*args, **kwargs):
        captured["prompt"] = kwargs["messages"][0]["content"]
        yield _llm_chunk(
            content=(
                '{"decision":"continue","reason":'
                '"questionnaire_async was required but was not called"}'
            )
        )

    monkeypatch.setattr(agent, "_must_continue_by_rules", _never_must_continue)
    monkeypatch.setattr(
        agent, "prepare_llm_system_prompt_text", _fake_system_prompt_build
    )
    monkeypatch.setattr(agent, "_call_llm_streaming", _fake_llm_streaming)

    session_context = SimpleNamespace(
        message_manager=SimpleNamespace(
            context_budget_manager=SimpleNamespace(budget_info={"active_budget": 3000})
        ),
        get_language=lambda: "en",
    )
    messages = [
        MessageChunk(
            role=MessageRole.USER.value,
            content="Continue preparing Episode 04.",
            message_type=MessageType.USER_INPUT.value,
        ),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content=(
                "Before I write the episode, I need the earlier story content "
                "and delivery format. Please provide them in the questionnaire below."
            ),
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
    ]

    decision = asyncio.run(
        agent._get_task_complete_decision(
            messages_input=messages,
            session_id="missing-questionnaire",
            tool_manager=None,
            session_context=session_context,  # pyright: ignore[reportArgumentType]
            tools_json=[
                {
                    "type": "function",
                    "function": {"name": "questionnaire_async"},
                }
            ],
        )
    )

    assert decision.task_interrupted is False
    assert "questionnaire_async" in captured["prompt"]
    assert "Plain text such as" in captured["prompt"]
    assert "Please provide them in the questionnaire below." in captured["prompt"]


def test_task_complete_judge_includes_latest_todo_plan_before_last_user(monkeypatch):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "llm_judge")
    agent = _agent()
    captured = {}

    async def _never_must_continue(messages):
        return False

    async def _fake_llm_streaming(*args, **kwargs):
        captured["prompt"] = kwargs["messages"][0]["content"]
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content='{"task_interrupted": false, "reason": "todo remains"}'
                    )
                )
            ]
        )

    monkeypatch.setattr(agent, "_must_continue_by_rules", _never_must_continue)
    monkeypatch.setattr(agent, "_call_llm_streaming", _fake_llm_streaming)
    session_context = SimpleNamespace(
        message_manager=SimpleNamespace(
            context_budget_manager=SimpleNamespace(budget_info={"active_budget": 3000})
        ),
        get_language=lambda: "en",
    )
    messages = [
        MessageChunk(
            role=MessageRole.USER.value,
            content="Build the feature",
            message_type=MessageType.USER_INPUT.value,
        ),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="",
            tool_calls=[
                {
                    "id": "todo-plan",
                    "type": "function",
                    "function": {"name": "todo_write", "arguments": "{}"},
                }
            ],
            message_type=MessageType.TOOL_CALL.value,
        ),
        MessageChunk(
            role=MessageRole.TOOL.value,
            content=(
                '{"tasks": ['
                '{"id": "design", "name": "Finish the design", '
                '"completed": true}, '
                '{"id": "architecture", "name": "Implement the high-level plan", '
                '"status": "in_progress"}, '
                '{"id": "verification", "name": "Run end-to-end verification", '
                '"status": "pending"}]}'
            ),
            tool_call_id="todo-plan",
            message_type=MessageType.TOOL_CALL_RESULT.value,
        ),
        MessageChunk(
            role=MessageRole.USER.value,
            content="Continue",
            message_type=MessageType.USER_INPUT.value,
        ),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="Working on it.",
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
    ]

    decision = asyncio.run(
        agent._get_task_complete_decision(
            messages_input=messages,
            session_id="todo-judge",
            tool_manager=None,
            session_context=session_context,  # pyright: ignore[reportArgumentType]
        )
    )

    assert decision.task_interrupted is False
    assert "<current_todo_plan>" in captured["prompt"]
    assert '"source": "latest_todo_write_result"' in captured["prompt"]
    assert "Finish the design" in captured["prompt"]
    assert '"status": "completed"' in captured["prompt"]
    assert "Implement the high-level plan" in captured["prompt"]
    assert '"status": "in_progress"' in captured["prompt"]
    assert "Run end-to-end verification" in captured["prompt"]
    assert '"status": "pending"' in captured["prompt"]
    assert "user: Build the feature" not in captured["prompt"]


def test_open_todo_code_guard_allows_only_non_completed_states(monkeypatch):
    agent = _agent()
    judge_results = iter(
        [
            '{"decision":"completed","reason":"任务已经完成"}',
            '{"decision":"continue","reason":"验证仍在进行"}',
            '{"decision":"need_user_input","reason":"缺少服务器地址"}',
            '{"decision":"blocked","reason":"外部服务拒绝访问"}',
            '{"task_interrupted":true,"reason":"任务完成"}',
        ]
    )

    async def _never_must_continue(messages):
        return False

    async def _fake_llm_streaming(*args, **kwargs):
        yield _llm_chunk(content=next(judge_results))

    monkeypatch.setattr(agent, "_must_continue_by_rules", _never_must_continue)
    monkeypatch.setattr(agent, "_call_llm_streaming", _fake_llm_streaming)
    session_context = SimpleNamespace(
        message_manager=SimpleNamespace(
            context_budget_manager=SimpleNamespace(budget_info={"active_budget": 3000})
        ),
        get_language=lambda: "zh",
    )
    messages = [
        MessageChunk(
            role=MessageRole.USER.value,
            content="实现并验证功能",
            message_type=MessageType.USER_INPUT.value,
        ),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="",
            tool_calls=[
                {
                    "id": "todo-open",
                    "type": "function",
                    "function": {"name": "todo_write", "arguments": "{}"},
                }
            ],
            message_type=MessageType.TOOL_CALL.value,
        ),
        MessageChunk(
            role=MessageRole.TOOL.value,
            content=(
                '{"tasks":[{"id":"verify","name":"运行验证","status":"in_progress"}]}'
            ),
            tool_call_id="todo-open",
            message_type=MessageType.TOOL_CALL_RESULT.value,
        ),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="当前阶段已完成。",
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
    ]

    def _judge(latest_text):
        current_messages = list(messages)
        current_messages[-1] = MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content=latest_text,
            message_type=MessageType.ASSISTANT_TEXT.value,
        )
        return asyncio.run(
            agent._get_task_complete_decision(
                messages_input=current_messages,
                session_id="todo-open-guard",
                tool_manager=None,
                session_context=session_context,  # pyright: ignore[reportArgumentType]
            )
        )

    # completed is inconsistent with an open Todo and is coerced to continue.
    rejected_completed = _judge("当前阶段已完成。")
    assert rejected_completed.task_interrupted is False
    assert "Todo still has pending/in_progress" in rejected_completed.reason
    # The other three states remain valid while Todo work is open.
    assert _judge("验证仍在进行。").task_interrupted is False
    assert (
        _judge("请提供目标服务器地址，当前上下文中没有这个信息。").task_interrupted
        is True
    )
    assert _judge("外部服务拒绝访问，当前无法继续。").task_interrupted is True
    # Open Todo requires an explicit four-state decision; legacy/missing state fails closed.
    assert _judge("任务完成。").task_interrupted is False


def test_task_complete_judge_does_not_revive_older_unfinished_todo_snapshot():
    agent = _agent()
    messages = [
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="",
            tool_calls=[
                {
                    "id": "todo-active",
                    "type": "function",
                    "function": {"name": "todo_write", "arguments": "{}"},
                }
            ],
            message_type=MessageType.TOOL_CALL.value,
        ),
        MessageChunk(
            role=MessageRole.TOOL.value,
            content=(
                '{"tasks": [{"id": "implementation", '
                '"name": "Implement feature", "status": "in_progress"}]}'
            ),
            tool_call_id="todo-active",
            message_type=MessageType.TOOL_CALL_RESULT.value,
        ),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="",
            tool_calls=[
                {
                    "id": "todo-completed",
                    "type": "function",
                    "function": {"name": "todo_write", "arguments": "{}"},
                }
            ],
            message_type=MessageType.TOOL_CALL.value,
        ),
        MessageChunk(
            role=MessageRole.TOOL.value,
            content=(
                '{"tasks": [{"id": "implementation", '
                '"name": "Implement feature", "status": "completed"}]}'
            ),
            tool_call_id="todo-completed",
            message_type=MessageType.TOOL_CALL_RESULT.value,
        ),
    ]

    todo_plan = asyncio.run(
        agent._build_task_complete_todo_plan(messages, "todo-completed")
    )

    assert todo_plan == ""


def test_task_complete_judge_keeps_every_item_in_large_active_todo_plan():
    agent = _agent()
    tasks = [
        {
            "id": f"task-{index}",
            "name": f"Plan item {index}",
            "status": "pending" if index == 44 else "completed",
        }
        for index in range(45)
    ]
    messages = [
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="",
            tool_calls=[
                {
                    "id": "todo-large",
                    "type": "function",
                    "function": {"name": "todo_write", "arguments": "{}"},
                }
            ],
            message_type=MessageType.TOOL_CALL.value,
        ),
        MessageChunk(
            role=MessageRole.TOOL.value,
            content=json.dumps({"tasks": tasks}),
            tool_call_id="todo-large",
            message_type=MessageType.TOOL_CALL_RESULT.value,
        ),
    ]

    todo_plan = asyncio.run(
        agent._build_task_complete_todo_plan(messages, "todo-large")
    )

    assert "Plan item 0" in todo_plan
    assert "Plan item 44" in todo_plan
    assert '"omitted_count"' not in todo_plan


def test_task_complete_judge_prompt_requires_evidence_for_execution_claims(
    monkeypatch,
):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "llm_judge")
    agent = _agent()
    captured = {}

    async def _never_must_continue(messages):
        return False

    async def _fake_llm_streaming(*args, **kwargs):
        captured["llm_messages"] = kwargs["messages"]
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content='{"task_interrupted": true, "reason": "done"}'
                    )
                )
            ]
        )

    monkeypatch.setattr(agent, "_must_continue_by_rules", _never_must_continue)
    monkeypatch.setattr(agent, "_call_llm_streaming", _fake_llm_streaming)

    msg_manager = SimpleNamespace(
        context_budget_manager=SimpleNamespace(budget_info={"active_budget": 3000}),
    )
    session_context = SimpleNamespace(
        message_manager=msg_manager,
        get_language=lambda: "en",
    )
    messages = [
        MessageChunk(
            role=MessageRole.USER.value,
            content="Update the config and verify it.",
            message_type=MessageType.USER_INPUT.value,
        ),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="Updated the config and verified it.",
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
    ]

    assert (
        asyncio.run(
            agent._is_task_complete(
                messages_input=messages,
                session_id="s1",
                tool_manager=None,
                session_context=session_context,  # pyright: ignore[reportArgumentType]
            )
        )
        is True
    )

    prompt = captured["llm_messages"][0]["content"]
    assert "claims about executed actions are backed by execution evidence" in prompt
    assert 'Saying "done", "handled", or "verified" is not execution evidence' in prompt
    assert (
        "The Assistant's assertion that it “needs confirmation/input” is not evidence"
        in prompt
    )


def test_task_complete_judge_does_not_treat_can_start_after_confirmation_as_user_wait(
    monkeypatch,
):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "llm_judge")
    agent = _agent()
    captured = {}

    async def _never_must_continue(messages):
        return False

    async def _fake_llm_streaming(*args, **kwargs):
        captured["llm_messages"] = kwargs["messages"]
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content=(
                            '{"task_interrupted": false, '
                            '"reason": "continue production"}'
                        )
                    )
                )
            ]
        )

    monkeypatch.setattr(agent, "_must_continue_by_rules", _never_must_continue)
    monkeypatch.setattr(agent, "_call_llm_streaming", _fake_llm_streaming)

    msg_manager = SimpleNamespace(
        context_budget_manager=SimpleNamespace(budget_info={"active_budget": 3000}),
    )
    session_context = SimpleNamespace(
        message_manager=msg_manager,
        get_language=lambda: "en",
    )
    messages = [
        MessageChunk(
            role=MessageRole.USER.value,
            content="OK 开始制作",
            message_type=MessageType.USER_INPUT.value,
        ),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content=(
                "Production readiness is checked. "
                "No production clips have been generated yet. "
                "I can start that production pass now."
            ),
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
    ]

    assert (
        asyncio.run(
            agent._is_task_complete(
                messages_input=messages,
                session_id="s1",
                tool_manager=None,
                session_context=session_context,  # pyright: ignore[reportArgumentType]
            )
        )
        is False
    )

    prompt = captured["llm_messages"][0]["content"]
    assert (
        "Do not infer that user confirmation is needed merely because the "
        "Assistant uses a declarative sentence"
    ) in prompt
    assert (
        "If the recent user message already confirmed starting, continuing, "
        "or proceeding with the plan"
    ) in prompt


def test_task_complete_judge_confirmation_rules_are_synced_across_prompt_variants():
    prompt_manager = PromptManager()
    expectations = [
        (
            "SimpleAgent",
            "zh",
            "不要仅因为 Assistant 使用了",
            "如果最近用户已经明确确认开始、继续、按计划执行",
        ),
        (
            "SimpleAgent",
            "en",
            "Do not infer that user confirmation is needed merely because",
            "If the recent user message already confirmed starting",
        ),
        (
            "SimpleAgent",
            "pt",
            "Não infira que confirmação do usuário é necessária apenas porque",
            "Se a mensagem recente do usuário já confirmou começar",
        ),
        (
            "SimpleReactAgent",
            "zh",
            "不要仅因为 Assistant 使用了",
            "如果最近用户已经明确确认开始、继续、按计划执行",
        ),
        (
            "SimpleReactAgent",
            "en",
            "Do not infer that user confirmation is needed merely because",
            "If the recent user message already confirmed starting",
        ),
        (
            "SimpleReactAgent",
            "pt",
            "Não infira que confirmação do usuário é necessária apenas porque",
            "Se a mensagem recente do usuário já confirmou começar",
        ),
    ]

    for agent, language, interrupt_rule, continue_rule in expectations:
        prompt = prompt_manager.get_agent_prompt(
            agent, "task_complete_template", language=language
        )
        assert interrupt_rule in prompt
        assert continue_rule in prompt


def test_task_complete_judge_closes_optional_followups_and_incidental_tools():
    prompt_manager = PromptManager()
    expectations = {
        "zh": (
            "用户之后可能回复",
            "<ling-action ... />",
            "成功但附带性的读取、搜索或记忆调用",
            "原始需求中哪一项尚未满足",
            "不得凭空想象后续工作",
        ),
        "en": (
            "The user may reply later",
            "<ling-action ... />",
            "successful incidental read, search, or memory call",
            "exact unmet part of the original request",
            "Do not invent future work",
        ),
        "pt": (
            "O usuário pode responder depois",
            "<ling-action ... />",
            "chamada de memória incidental bem-sucedida",
            "parte exata da solicitação original ainda não atendida",
            "Não invente trabalho futuro",
        ),
    }

    for language, required_fragments in expectations.items():
        prompt = prompt_manager.get_agent_prompt(
            "SimpleAgent", "task_complete_template", language=language
        )
        for fragment in required_fragments:
            assert fragment in prompt


def test_task_complete_judge_pending_question_rules_are_synced_across_prompt_variants():
    prompt_manager = PromptManager()
    expectations = [
        (
            "SimpleAgent",
            "zh",
            "\u5fc5\u987b\u6839\u636e Assistant **\u5df2\u7ecf\u4ea4\u4ed8**\u7ed9\u7528\u6237\u7684\u53ef\u56de\u7b54\u5185\u5bb9\u5224\u65ad",
            "\u4e0b\u9762\u8fdb\u5165\u57fa\u7840\u8981\u6c42\u786e\u8ba4\u9636\u6bb5",
        ),
        (
            "SimpleAgent",
            "en",
            "Judge only from answerable content the Assistant has **already delivered**",
            "Now entering requirements confirmation",
        ),
        (
            "SimpleAgent",
            "pt",
            "Julgue apenas pelo conte\u00fado respond\u00edvel que o Assistente **j\u00e1 entregou**",
            "Agora entrando na confirma\u00e7\u00e3o dos requisitos",
        ),
        (
            "SimpleReactAgent",
            "zh",
            "\u5fc5\u987b\u6839\u636e Assistant **\u5df2\u7ecf\u4ea4\u4ed8**\u7ed9\u7528\u6237\u7684\u53ef\u56de\u7b54\u5185\u5bb9\u5224\u65ad",
            "\u4e0b\u9762\u8fdb\u5165\u57fa\u7840\u8981\u6c42\u786e\u8ba4\u9636\u6bb5",
        ),
        (
            "SimpleReactAgent",
            "en",
            "Judge only from answerable content the Assistant has **already delivered**",
            "Now entering requirements confirmation",
        ),
        (
            "SimpleReactAgent",
            "pt",
            "Julgue apenas pelo conte\u00fado respond\u00edvel que o Assistente **j\u00e1 entregou**",
            "Agora entrando na confirma\u00e7\u00e3o dos requisitos",
        ),
    ]

    for agent, language, delivered_rule, pending_example in expectations:
        prompt = prompt_manager.get_agent_prompt(
            agent, "task_complete_template", language=language
        )
        assert delivered_rule in prompt
        assert pending_example in prompt


def test_task_complete_judge_required_user_input_tool_rules_are_synced():
    prompt_manager = PromptManager()
    expectations = [
        ("SimpleAgent", "zh", "<agent_system_requirements>", "成功调用"),
        ("SimpleAgent", "en", "<agent_system_requirements>", "successful call"),
        ("SimpleAgent", "pt", "<agent_system_requirements>", "chamada bem-sucedida"),
    ]

    for agent, language, context_tag, success_rule in expectations:
        prompt = prompt_manager.get_agent_prompt(
            agent, "task_complete_template", language=language
        )
        assert context_tag in prompt
        assert "<available_tools>" in prompt
        assert success_rule in prompt


def test_task_complete_judge_preserves_latest_assistant_waiting_for_user_tail(
    monkeypatch,
):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "llm_judge")
    agent = _agent()
    captured = {}

    async def _never_must_continue(messages):
        return False

    async def _fake_llm_streaming(*args, **kwargs):
        captured["llm_messages"] = kwargs["messages"]
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content=(
                            '{"task_interrupted": true, "reason": "need user input"}'
                        )
                    )
                )
            ]
        )

    monkeypatch.setattr(agent, "_must_continue_by_rules", _never_must_continue)
    monkeypatch.setattr(agent, "_call_llm_streaming", _fake_llm_streaming)

    msg_manager = SimpleNamespace(
        context_budget_manager=SimpleNamespace(budget_info={"active_budget": 100}),
    )
    session_context = SimpleNamespace(
        message_manager=msg_manager,
        get_language=lambda: "en",
    )
    latest_reply = (
        "I prepared the current phase result. "
        + "detail " * 450
        + "Please provide the output dimensions. "
        + "Once you answer, I will continue."
    )
    messages = [
        MessageChunk(
            role=MessageRole.USER.value,
            content="Replace the video product and adjust scene changes.",
            message_type=MessageType.USER_INPUT.value,
        ),
        MessageChunk(
            role=MessageRole.TOOL.value,
            content="T" * 5000,
            message_type=MessageType.TOOL_CALL_RESULT.value,
            tool_call_id="call_tool",
        ),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content=latest_reply,
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
    ]

    assert (
        asyncio.run(
            agent._is_task_complete(
                messages_input=messages,
                session_id="s1",
                tool_manager=None,
                session_context=session_context,  # pyright: ignore[reportArgumentType]
            )
        )
        is True
    )

    prompt = captured["llm_messages"][0]["content"]
    assert "Please provide the output dimensions." in prompt
    assert "Once you answer, I will continue." in prompt
    assert "assistant content omitted" not in prompt
    assert "[truncated, original chars:" not in prompt


def test_task_complete_judge_missing_evidence_reason_forces_continue(monkeypatch):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "llm_judge")
    agent = _agent()

    async def _never_must_continue(messages):
        return False

    async def _fake_llm_streaming(*args, **kwargs):
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content=(
                            '{"task_interrupted": true, '
                            '"reason": "missing execution evidence"}'
                        )
                    )
                )
            ]
        )

    monkeypatch.setattr(agent, "_must_continue_by_rules", _never_must_continue)
    monkeypatch.setattr(agent, "_call_llm_streaming", _fake_llm_streaming)

    msg_manager = SimpleNamespace(
        context_budget_manager=SimpleNamespace(budget_info={"active_budget": 3000}),
    )
    session_context = SimpleNamespace(
        message_manager=msg_manager,
        get_language=lambda: "en",
    )
    messages = [
        MessageChunk(
            role=MessageRole.USER.value,
            content="Run the tests.",
            message_type=MessageType.USER_INPUT.value,
        ),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="Tests passed.",
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
    ]

    assert (
        asyncio.run(
            agent._is_task_complete(
                messages_input=messages,
                session_id="s1",
                tool_manager=None,
                session_context=session_context,  # pyright: ignore[reportArgumentType]
            )
        )
        is False
    )


def test_task_complete_judge_redacts_multimodal_image_payloads(monkeypatch):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "llm_judge")
    agent = _agent()
    captured = {}

    async def _never_must_continue(messages):
        return False

    async def _fake_system_text(**kwargs):
        return "system prompt"

    async def _fake_llm_streaming(*args, **kwargs):
        captured["llm_messages"] = kwargs["messages"]
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content='{"task_interrupted": true, "reason": "done"}'
                    )
                )
            ]
        )

    monkeypatch.setattr(agent, "_must_continue_by_rules", _never_must_continue)
    monkeypatch.setattr(agent, "prepare_llm_system_prompt_text", _fake_system_text)
    monkeypatch.setattr(agent, "_call_llm_streaming", _fake_llm_streaming)

    msg_manager = SimpleNamespace(
        context_budget_manager=SimpleNamespace(budget_info={"active_budget": 3000}),
    )
    session_context = SimpleNamespace(
        message_manager=msg_manager,
        get_language=lambda: "en",
    )
    image_payload = "data:image/png;base64," + ("a" * 10000)
    messages = [
        MessageChunk(
            role=MessageRole.USER.value,
            content=[
                {"type": "text", "text": "please inspect this image"},
                {"type": "image_url", "image_url": {"url": image_payload}},
            ],
            message_type=MessageType.USER_INPUT.value,
        ),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="done",
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
    ]

    assert (
        asyncio.run(
            agent._is_task_complete(
                messages_input=messages,
                session_id="s1",
                tool_manager=None,
                session_context=session_context,  # pyright: ignore[reportArgumentType]
            )
        )
        is True
    )

    prompt = captured["llm_messages"][0]["content"]
    assert image_payload not in prompt
    assert "data:image/png;base64" not in prompt
    assert "[image attached]" in prompt


def test_task_complete_judge_keeps_tool_name_and_short_result_without_arguments(
    monkeypatch,
):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "llm_judge")
    agent = _agent()
    captured = {}

    async def _never_must_continue(messages):
        return False

    async def _fake_system_text(**kwargs):
        return "system prompt"

    async def _fake_llm_streaming(*args, **kwargs):
        captured["llm_messages"] = kwargs["messages"]
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content='{"task_interrupted": true, "reason": "done"}'
                    )
                )
            ]
        )

    monkeypatch.setattr(agent, "_must_continue_by_rules", _never_must_continue)
    monkeypatch.setattr(agent, "prepare_llm_system_prompt_text", _fake_system_text)
    monkeypatch.setattr(agent, "_call_llm_streaming", _fake_llm_streaming)

    msg_manager = SimpleNamespace(
        context_budget_manager=SimpleNamespace(budget_info={"active_budget": 3000}),
    )
    session_context = SimpleNamespace(
        message_manager=msg_manager,
        get_language=lambda: "en",
    )
    long_result = "RESULT_PREVIEW " + ("x" * 900)
    messages = [
        MessageChunk(
            role=MessageRole.USER.value,
            content="Patch app.py",
            message_type=MessageType.USER_INPUT.value,
        ),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content=None,
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "file_update",
                        "arguments": '{"path":"/secret/app.py"}',
                    },
                }
            ],
            message_type=MessageType.TOOL_CALL.value,
        ),
        MessageChunk(
            role=MessageRole.TOOL.value,
            content=long_result,
            tool_call_id="call_1",
            message_type=MessageType.TOOL_CALL_RESULT.value,
        ),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="Patched app.py and verified it.",
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
    ]

    assert (
        asyncio.run(
            agent._is_task_complete(
                messages_input=messages,
                session_id="s1",
                tool_manager=None,
                session_context=session_context,  # pyright: ignore[reportArgumentType]
            )
        )
        is True
    )

    prompt = captured["llm_messages"][0]["content"]
    assert "[tools called: file_update]" in prompt
    assert "[tool result from file_update: RESULT_PREVIEW" in prompt
    assert "[tool result truncated, original chars:" in prompt
    assert '{"path":"/secret/app.py"}' not in prompt
    assert "x" * 700 not in prompt


def test_task_complete_judge_supports_object_tool_calls(monkeypatch):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "llm_judge")
    agent = _agent()
    captured = {}

    async def _never_must_continue(messages):
        return False

    async def _fake_system_text(**kwargs):
        return "system prompt"

    async def _fake_llm_streaming(*args, **kwargs):
        captured["llm_messages"] = kwargs["messages"]
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content='{"task_interrupted": false, "reason": "continue"}'
                    )
                )
            ]
        )

    monkeypatch.setattr(agent, "_must_continue_by_rules", _never_must_continue)
    monkeypatch.setattr(agent, "prepare_llm_system_prompt_text", _fake_system_text)
    monkeypatch.setattr(agent, "_call_llm_streaming", _fake_llm_streaming)

    msg_manager = SimpleNamespace(
        context_budget_manager=SimpleNamespace(budget_info={"active_budget": 3000}),
    )
    session_context = SimpleNamespace(
        message_manager=msg_manager,
        get_language=lambda: "en",
    )
    object_tool_call = SimpleNamespace(
        id="call_obj",
        type="function",
        function=SimpleNamespace(
            name="file_read",
            arguments='{"path":"/secret/input.md"}',
        ),
    )
    messages = [
        MessageChunk(
            role=MessageRole.USER.value,
            content="Read the file and summarize it.",
            message_type=MessageType.USER_INPUT.value,
        ),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content=None,
            tool_calls=[object_tool_call],  # pyright: ignore[reportArgumentType]
            message_type=MessageType.TOOL_CALL.value,
        ),
        MessageChunk(
            role=MessageRole.TOOL.value,
            content="file content preview",
            tool_call_id="call_obj",
            message_type=MessageType.TOOL_CALL_RESULT.value,
        ),
    ]

    assert (
        asyncio.run(
            agent._is_task_complete(
                messages_input=messages,
                session_id="s1",
                tool_manager=None,
                session_context=session_context,  # pyright: ignore[reportArgumentType]
            )
        )
        is False
    )

    prompt = captured["llm_messages"][0]["content"]
    assert "[tools called: file_read]" in prompt
    assert "[tool result from file_read: file content preview]" in prompt
    assert '{"path":"/secret/input.md"}' not in prompt


def test_llm_judge_skips_completion_check_after_direct_tool_activity(monkeypatch):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "llm_judge")
    agent = _agent()
    direct_calls = []
    judge_calls = []

    async def _fake_call_llm_and_process_response(**kwargs):
        direct_calls.append(kwargs)
        if len(direct_calls) == 1:
            kwargs["direct_response_state"]["had_tool_calls"] = True
            yield (
                [
                    MessageChunk(
                        role=MessageRole.TOOL.value,
                        content='{"ok": true}',
                        tool_call_id="call_tool",
                        message_type=MessageType.TOOL_CALL_RESULT.value,
                    ),
                    MessageChunk(
                        role=MessageRole.ASSISTANT.value,
                        content="我会继续处理工具结果。",
                        message_type=MessageType.DO_SUBTASK_RESULT.value,
                    ),
                ],
                False,
            )
            return
        yield (
            [
                MessageChunk(
                    role=MessageRole.ASSISTANT.value,
                    content="已经完成。",
                    message_type=MessageType.ASSISTANT_TEXT.value,
                )
            ],
            False,
        )

    async def _fake_get_task_complete_decision(*args, **kwargs):
        judge_calls.append((args, kwargs))
        return TaskCompleteDecision(task_interrupted=True)

    monkeypatch.setattr(agent, "_should_abort_due_to_session", lambda *args: False)
    monkeypatch.setattr(
        agent, "_call_llm_and_process_response", _fake_call_llm_and_process_response
    )
    monkeypatch.setattr(
        agent, "_get_task_complete_decision", _fake_get_task_complete_decision
    )

    async def _collect():
        chunks = []
        async for yielded_chunks in agent._execute_loop(
            messages_input=_base_messages(),
            tools_json=[],
            tool_manager=None,
            session_id="s1",
            session_context=_loop_session_context(),  # pyright: ignore[reportArgumentType]
        ):
            chunks.extend(yielded_chunks)
        return chunks

    chunks = asyncio.run(_collect())

    assert len(direct_calls) == 2
    assert len(judge_calls) == 1
    assert chunks[-1].content == "已经完成。"


def test_llm_judge_continuation_guidance_is_one_shot(monkeypatch):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "llm_judge")
    agent = _agent()
    direct_calls = []
    judge_calls = []

    async def _fake_call_llm_and_process_response(**kwargs):
        direct_calls.append(kwargs)
        if len(direct_calls) == 1:
            yield (
                [
                    MessageChunk(
                        role=MessageRole.ASSISTANT.value,
                        content="progress update",
                        message_type=MessageType.DO_SUBTASK_RESULT.value,
                    )
                ],
                False,
            )
            return
        if len(direct_calls) == 2:
            kwargs["direct_response_state"]["had_tool_calls"] = True
            yield (
                [
                    MessageChunk(
                        role=MessageRole.TOOL.value,
                        content='{"ok": true}',
                        tool_call_id="call_tool",
                        message_type=MessageType.TOOL_CALL_RESULT.value,
                    )
                ],
                False,
            )
            return
        yield (
            [
                MessageChunk(
                    role=MessageRole.ASSISTANT.value,
                    content="done",
                    message_type=MessageType.ASSISTANT_TEXT.value,
                )
            ],
            False,
        )

    async def _fake_get_task_complete_decision(*args, **kwargs):
        judge_calls.append((args, kwargs))
        if len(judge_calls) == 1:
            return TaskCompleteDecision(
                task_interrupted=False,
                reason="more clips pending",
            )
        return TaskCompleteDecision(
            task_interrupted=True,
            reason="done",
        )

    monkeypatch.setattr(agent, "_should_abort_due_to_session", lambda *args: False)
    monkeypatch.setattr(
        agent, "_call_llm_and_process_response", _fake_call_llm_and_process_response
    )
    monkeypatch.setattr(
        agent, "_get_task_complete_decision", _fake_get_task_complete_decision
    )

    async def _collect():
        chunks = []
        async for yielded_chunks in agent._execute_loop(
            messages_input=_base_messages(),
            tools_json=[],
            tool_manager=None,
            session_id="s1",
            session_context=_loop_session_context(),  # pyright: ignore[reportArgumentType]
        ):
            chunks.extend(yielded_chunks)
        return chunks

    chunks = asyncio.run(_collect())

    assert len(direct_calls) == 3
    assert [call["continuation_reason"] for call in direct_calls] == [
        None,
        "more clips pending",
        None,
    ]
    assert [chunk.content for chunk in chunks if chunk.content] == [
        "progress update",
        '{"ok": true}',
        "done",
    ]


def test_llm_judge_uses_direct_response_state_not_collected_chunks(monkeypatch):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "llm_judge")
    agent = _agent()
    judge_calls = []

    async def _fake_call_llm_and_process_response(**kwargs):
        yield (
            [
                MessageChunk(
                    role=MessageRole.TOOL.value,
                    content='{"ok": true}',
                    tool_call_id="compress_tool",
                    message_type=MessageType.TOOL_CALL_RESULT.value,
                ),
                MessageChunk(
                    role=MessageRole.ASSISTANT.value,
                    content="已经完成。",
                    message_type=MessageType.ASSISTANT_TEXT.value,
                ),
            ],
            False,
        )

    async def _fake_get_task_complete_decision(*args, **kwargs):
        judge_calls.append((args, kwargs))
        return TaskCompleteDecision(task_interrupted=True)

    monkeypatch.setattr(agent, "_should_abort_due_to_session", lambda *args: False)
    monkeypatch.setattr(
        agent, "_call_llm_and_process_response", _fake_call_llm_and_process_response
    )
    monkeypatch.setattr(
        agent, "_get_task_complete_decision", _fake_get_task_complete_decision
    )

    async def _collect():
        chunks = []
        async for yielded_chunks in agent._execute_loop(
            messages_input=_base_messages(),
            tools_json=[],
            tool_manager=None,
            session_id="s1",
            session_context=_loop_session_context(),  # pyright: ignore[reportArgumentType]
        ):
            chunks.extend(yielded_chunks)
        return chunks

    chunks = asyncio.run(_collect())

    assert len(judge_calls) == 1
    assert chunks[-1].content == "已经完成。"


def test_llm_judge_stops_after_three_plain_text_direct_responses(monkeypatch):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "llm_judge")
    agent = _agent()
    direct_calls = []
    judge_calls = []

    async def _fake_call_llm_and_process_response(**kwargs):
        direct_calls.append(kwargs)
        yield (
            [
                MessageChunk(
                    role=MessageRole.ASSISTANT.value,
                    content=f"纯文本回答 {len(direct_calls)}",
                    message_type=MessageType.ASSISTANT_TEXT.value,
                )
            ],
            False,
        )

    async def _fake_get_task_complete_decision(*args, **kwargs):
        judge_calls.append((args, kwargs))
        return TaskCompleteDecision(task_interrupted=False)

    monkeypatch.setattr(agent, "_should_abort_due_to_session", lambda *args: False)
    monkeypatch.setattr(
        agent, "_call_llm_and_process_response", _fake_call_llm_and_process_response
    )
    monkeypatch.setattr(
        agent, "_get_task_complete_decision", _fake_get_task_complete_decision
    )

    session_context = _loop_session_context()

    async def _collect():
        chunks = []
        async for yielded_chunks in agent._execute_loop(
            messages_input=_base_messages(),
            tools_json=[],
            tool_manager=None,
            session_id="s1",
            session_context=session_context,  # pyright: ignore[reportArgumentType]
        ):
            chunks.extend(yielded_chunks)
        return chunks

    chunks = asyncio.run(_collect())

    assert len(direct_calls) == 3
    assert len(judge_calls) == 2
    assert [call["force_tool_choice_required"] for call in direct_calls] == [
        False,
        True,
        True,
    ]
    assert [chunk.content for chunk in chunks[:3]] == [
        "纯文本回答 1",
        "纯文本回答 2",
        "纯文本回答 3",
    ]
    assert len(chunks) == 4
    assert "Agent 已陷入循环" in chunks[-1].content
    assert "<questionnaire>" in chunks[-1].content
    assert chunks[-1].metadata["stop_reason"] == "plain_text_no_progress"
    assert session_context.audit_status["completion_status"] == "need_user_input"


def test_third_plain_text_questionnaire_still_sets_need_user_input(monkeypatch):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "llm_judge")
    agent = _agent()
    direct_calls = []
    judge_calls = []
    original_get_task_complete_decision = agent._get_task_complete_decision

    async def _fake_call_llm_and_process_response(**kwargs):
        direct_calls.append(kwargs)
        content = f"纯文本回答 {len(direct_calls)}"
        if len(direct_calls) == 3:
            content = (
                "请选择部署目标。\n"
                '<sage-questionnaire>{"questions":[]}</sage-questionnaire>'
            )
        yield (
            [
                MessageChunk(
                    role=MessageRole.ASSISTANT.value,
                    content=content,
                    message_type=MessageType.ASSISTANT_TEXT.value,
                )
            ],
            False,
        )

    async def _fake_get_task_complete_decision(*args, **kwargs):
        judge_calls.append((args, kwargs))
        if len(judge_calls) < 3:
            return TaskCompleteDecision(task_interrupted=False)
        return await original_get_task_complete_decision(*args, **kwargs)

    monkeypatch.setattr(agent, "_should_abort_due_to_session", lambda *args: False)
    monkeypatch.setattr(
        agent, "_call_llm_and_process_response", _fake_call_llm_and_process_response
    )
    monkeypatch.setattr(
        agent, "_get_task_complete_decision", _fake_get_task_complete_decision
    )
    session_context = _loop_session_context()

    async def _collect():
        chunks = []
        async for yielded_chunks in agent._execute_loop(
            messages_input=_base_messages(),
            tools_json=[],
            tool_manager=None,
            session_id="s1",
            session_context=session_context,  # pyright: ignore[reportArgumentType]
        ):
            chunks.extend(yielded_chunks)
        return chunks

    chunks = asyncio.run(_collect())

    assert len(direct_calls) == 3
    assert len(judge_calls) == 3
    assert session_context.audit_status["completion_status"] == "need_user_input"
    assert "<sage-questionnaire>" in str(chunks[-1].content)


def test_llm_judge_forces_required_after_incomplete_plain_text(monkeypatch):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "llm_judge")
    agent = _agent()
    direct_calls = []
    judge_calls = []

    async def _fake_call_llm_and_process_response(**kwargs):
        direct_calls.append(kwargs)
        if len(direct_calls) == 1:
            yield (
                [
                    MessageChunk(
                        role=MessageRole.ASSISTANT.value,
                        content="纯文本回答",
                        message_type=MessageType.ASSISTANT_TEXT.value,
                    )
                ],
                False,
            )
            return
        kwargs["direct_response_state"]["had_tool_calls"] = True
        yield (
            [
                MessageChunk(
                    role=MessageRole.TOOL.value,
                    content='{"ok": true}',
                    tool_call_id="call_tool",
                    message_type=MessageType.TOOL_CALL_RESULT.value,
                )
            ],
            False,
        )

    async def _fake_get_task_complete_decision(*args, **kwargs):
        judge_calls.append((args, kwargs))
        return TaskCompleteDecision(task_interrupted=False)

    monkeypatch.setattr(agent, "_should_abort_due_to_session", lambda *args: False)
    monkeypatch.setattr(
        agent, "_call_llm_and_process_response", _fake_call_llm_and_process_response
    )
    monkeypatch.setattr(
        agent, "_get_task_complete_decision", _fake_get_task_complete_decision
    )

    async def _collect():
        chunks = []
        async for yielded_chunks in agent._execute_loop(
            messages_input=_base_messages(),
            tools_json=[{"function": {"name": "todo_write"}}],
            tool_manager=None,
            session_id="s1",
            session_context=_loop_session_context(max_loop_count=2),  # pyright: ignore[reportArgumentType]
        ):
            chunks.extend(yielded_chunks)
        return chunks

    chunks = asyncio.run(_collect())

    assert len(direct_calls) == 2
    assert len(judge_calls) == 1
    assert [call["force_tool_choice_required"] for call in direct_calls] == [
        False,
        True,
    ]
    visible_contents = [chunk.content for chunk in chunks if chunk.content]
    assert visible_contents[:2] == [
        "纯文本回答",
        '{"ok": true}',
    ]
    questionnaire = chunks[-1]
    assert "当前 Agent 已达到本轮最大循环次数（2）并陷入执行循环" in questionnaire.content
    assert "```questionnaire" in questionnaire.content
    assert "title: Agent 已陷入循环" in questionnaire.content
    assert "text: 是否继续当前任务？" in questionnaire.content
    assert "options:\n  - 继续" in questionnaire.content
    assert "default: 继续" in questionnaire.content
    assert "movo-questionnaire" not in questionnaire.content
    assert questionnaire.metadata["runtime_notice"] == "max_loop_questionnaire"
    assert questionnaire.metadata["stop_reason"] == "max_loop_count"
    assert questionnaire.metadata["needs_user_input"] is True


def test_max_loop_questionnaire_uses_session_language():
    agent = _agent()

    english = agent._build_max_loop_questionnaire(
        max_loop_count=50,
        language="en-US",
    )
    portuguese = agent._build_max_loop_questionnaire(
        max_loop_count=50,
        language="pt-BR",
    )

    assert "maximum loop count for this turn (50)" in english.content
    assert "Agent is stuck in a loop" in english.content
    assert "text: Continue the current task?" in english.content
    assert "options:\n  - Continue" in english.content
    assert "numero maximo de ciclos desta rodada (50)" in portuguese.content
    assert "O Agent entrou em um ciclo" in portuguese.content
    assert "text: Continuar a tarefa atual?" in portuguese.content
    assert "options:\n  - Continuar" in portuguese.content
    assert "```questionnaire" in english.content
    assert "```movo-questionnaire" not in english.content


def test_llm_judge_completed_plain_text_does_not_force_required(monkeypatch):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "llm_judge")
    agent = _agent()
    direct_calls = []
    judge_calls = []

    async def _fake_call_llm_and_process_response(**kwargs):
        direct_calls.append(kwargs)
        yield (
            [
                MessageChunk(
                    role=MessageRole.ASSISTANT.value,
                    content="已经完成。",
                    message_type=MessageType.ASSISTANT_TEXT.value,
                )
            ],
            False,
        )

    async def _fake_get_task_complete_decision(*args, **kwargs):
        judge_calls.append((args, kwargs))
        return TaskCompleteDecision(task_interrupted=True)

    monkeypatch.setattr(agent, "_should_abort_due_to_session", lambda *args: False)
    monkeypatch.setattr(
        agent, "_call_llm_and_process_response", _fake_call_llm_and_process_response
    )
    monkeypatch.setattr(
        agent, "_get_task_complete_decision", _fake_get_task_complete_decision
    )

    async def _collect():
        chunks = []
        async for yielded_chunks in agent._execute_loop(
            messages_input=_base_messages(),
            tools_json=[{"function": {"name": "todo_write"}}],
            tool_manager=None,
            session_id="s1",
            session_context=_loop_session_context(),  # pyright: ignore[reportArgumentType]
        ):
            chunks.extend(yielded_chunks)
        return chunks

    chunks = asyncio.run(_collect())

    assert len(direct_calls) == 1
    assert len(judge_calls) == 1
    assert direct_calls[0]["force_tool_choice_required"] is False
    assert [chunk.content for chunk in chunks] == ["已经完成。"]


def test_llm_judge_need_user_input_plain_request_stops_execution(monkeypatch):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "llm_judge")
    agent = _agent()
    direct_calls = []

    async def _fake_call_llm_and_process_response(**kwargs):
        direct_calls.append(kwargs)
        yield (
            [
                MessageChunk(
                    role=MessageRole.ASSISTANT.value,
                    content="请上传视频文件或提供可公开访问的 .mp4 直链。",
                    message_type=MessageType.ASSISTANT_TEXT.value,
                )
            ],
            False,
        )

    async def _fake_llm_streaming(*args, **kwargs):
        assert kwargs["step_name"] == "task_complete_judge"
        yield _llm_chunk(
            content=('{"decision":"need_user_input","reason":"缺少可读取的视频素材"}')
        )

    async def _open_todo_plan(*args, **kwargs):
        return (
            '<current_todo_plan>{"authoritative":true,'
            '"tasks":[{"id":"analyze","status":"in_progress"}]}'
            "</current_todo_plan>"
        )

    monkeypatch.setattr(agent, "_should_abort_due_to_session", lambda *args: False)
    monkeypatch.setattr(
        agent, "_call_llm_and_process_response", _fake_call_llm_and_process_response
    )
    monkeypatch.setattr(agent, "_call_llm_streaming", _fake_llm_streaming)
    monkeypatch.setattr(agent, "_build_task_complete_todo_plan", _open_todo_plan)
    session_context = _loop_session_context()
    session_context.message_manager.context_budget_manager = SimpleNamespace(
        budget_info={"active_budget": 3000}
    )

    async def _collect():
        chunks = []
        async for yielded_chunks in agent._execute_loop(
            messages_input=_base_messages(),
            tools_json=[],
            tool_manager=None,
            session_id="s1",
            session_context=session_context,  # pyright: ignore[reportArgumentType]
        ):
            chunks.extend(yielded_chunks)
        return chunks

    chunks = asyncio.run(_collect())

    assert len(direct_calls) == 1
    assert [chunk.content for chunk in chunks] == [
        "请上传视频文件或提供可公开访问的 .mp4 直链。"
    ]


def test_llm_judge_tool_activity_resets_required_after_plain_text(monkeypatch):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "llm_judge")
    agent = _agent()
    direct_calls = []
    judge_calls = []

    async def _fake_call_llm_and_process_response(**kwargs):
        direct_calls.append(kwargs)
        if len(direct_calls) == 1:
            yield (
                [
                    MessageChunk(
                        role=MessageRole.ASSISTANT.value,
                        content="纯文本回答",
                        message_type=MessageType.ASSISTANT_TEXT.value,
                    )
                ],
                False,
            )
            return
        if len(direct_calls) == 2:
            kwargs["direct_response_state"]["had_tool_calls"] = True
            yield (
                [
                    MessageChunk(
                        role=MessageRole.TOOL.value,
                        content='{"ok": true}',
                        tool_call_id="call_tool",
                        message_type=MessageType.TOOL_CALL_RESULT.value,
                    )
                ],
                False,
            )
            return
        yield (
            [
                MessageChunk(
                    role=MessageRole.ASSISTANT.value,
                    content="完成收尾。",
                    message_type=MessageType.ASSISTANT_TEXT.value,
                )
            ],
            False,
        )

    async def _fake_get_task_complete_decision(*args, **kwargs):
        judge_calls.append((args, kwargs))
        return TaskCompleteDecision(task_interrupted=len(judge_calls) >= 2)

    monkeypatch.setattr(agent, "_should_abort_due_to_session", lambda *args: False)
    monkeypatch.setattr(
        agent, "_call_llm_and_process_response", _fake_call_llm_and_process_response
    )
    monkeypatch.setattr(
        agent, "_get_task_complete_decision", _fake_get_task_complete_decision
    )

    async def _collect():
        chunks = []
        async for yielded_chunks in agent._execute_loop(
            messages_input=_base_messages(),
            tools_json=[{"function": {"name": "todo_write"}}],
            tool_manager=None,
            session_id="s1",
            session_context=_loop_session_context(),  # pyright: ignore[reportArgumentType]
        ):
            chunks.extend(yielded_chunks)
        return chunks

    chunks = asyncio.run(_collect())

    assert len(direct_calls) == 3
    assert len(judge_calls) == 2
    assert [call["force_tool_choice_required"] for call in direct_calls] == [
        False,
        True,
        False,
    ]
    assert [chunk.content for chunk in chunks if chunk.content] == [
        "纯文本回答",
        '{"ok": true}',
        "完成收尾。",
    ]


def test_direct_tool_call_response_records_tool_activity_state(monkeypatch):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "llm_judge")
    agent = _agent()
    messages = _base_messages()
    seen_tool_calls = {}
    direct_response_state = {"had_tool_calls": False}
    _patch_prepared_messages(monkeypatch, agent, messages)
    _patch_tool_handler(monkeypatch, agent, seen_tool_calls)

    def _fake_call_llm_streaming(*args, **kwargs):
        async def _gen():
            yield _llm_chunk(
                tool_calls=[
                    _turn_status_tool_call(
                        name="todo_write",
                        arguments='{"todos":[]}',
                    )
                ]
            )

        return _gen()

    monkeypatch.setattr(agent, "_call_llm_streaming", _fake_call_llm_streaming)

    chunks = asyncio.run(
        _collect_llm_response(
            agent,
            messages_input=messages,
            tools_json=[{"function": {"name": "todo_write"}}],
            tool_manager=None,
            session_id="s-direct-tool",
            direct_response_state=direct_response_state,
        )
    )

    assert "call_ts" in seen_tool_calls
    assert direct_response_state["had_tool_calls"] is True
    assert any(chunk.role == MessageRole.TOOL.value for chunk in chunks)


def test_turn_status_tools_only_filters_action_tools():
    tools_json = [
        {"function": {"name": "todo_write"}},
        {"function": {"name": "turn_status"}},
    ]

    assert _agent()._turn_status_tools_only(tools_json) == [
        {"function": {"name": "turn_status"}}
    ]


def test_complete_on_no_tool_call_mode_disables_turn_status_contract(monkeypatch):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "no_tool_call")
    tool_manager = SimpleNamespace(list_all_tools_name=lambda: ["turn_status"])

    prompt = _get_system_prefix(tool_manager, "zh")

    assert "turn_status" not in prompt
    assert "no_tool_call" not in prompt
    assert "完成与工具延续规则" in prompt
    assert "直接给出最终回答" in prompt
    assert _agent()._turn_status_enabled() is False


def test_complete_on_no_tool_call_mode_filters_turn_status_tools(monkeypatch):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "no_tool_call")
    tools_json = [
        {"function": {"name": "todo_write"}},
        {"function": {"name": "turn_status"}},
    ]

    assert _agent()._filter_tools_for_completion_mode(tools_json) == [
        {"function": {"name": "todo_write"}}
    ]


def test_llm_judge_mode_filters_turn_status_tools(monkeypatch):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "llm_judge")
    tools_json = [
        {"function": {"name": "todo_write"}},
        {"function": {"name": "turn_status"}},
    ]

    assert _agent()._filter_tools_for_completion_mode(tools_json) == [
        {"function": {"name": "todo_write"}}
    ]


def test_complete_on_no_tool_call_mode_marks_plain_text_response_complete(monkeypatch):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "no_tool_call")
    agent = _agent()
    messages = _base_messages()
    completions = []
    captured_configs = []
    _patch_prepared_messages(monkeypatch, agent, messages)
    monkeypatch.setattr(
        "sagents.agent.simple_agent.save_agent_response_content",
        lambda content, session_id: None,
    )

    def _fake_call_llm_streaming(*args, **kwargs):
        captured_configs.append(kwargs.get("model_config_override") or {})

        async def _gen():
            yield _llm_chunk(content="已经完成。")

        return _gen()

    monkeypatch.setattr(agent, "_call_llm_streaming", _fake_call_llm_streaming)

    async def _collect():
        chunks = []
        async for yielded_chunks, is_complete in agent._call_llm_and_process_response(
            messages_input=messages,
            tools_json=[{"function": {"name": "turn_status"}}],
            tool_manager=None,
            session_id="s1",
        ):
            chunks.extend(yielded_chunks)
            completions.append(is_complete)
            if is_complete:
                break
        return chunks

    chunks = asyncio.run(_collect())

    assert any(chunk.content == "已经完成。" for chunk in chunks)
    assert completions[-1] is True
    assert "tools" not in captured_configs[0]


def test_coerce_invalid_status_only_returns_continue_work_with_metadata():
    """status-only 补轮里改写违规工具：保留原 id、记录原始工具名、note 走 i18n。"""
    import json

    invalid_calls = {
        "call_X": {
            "id": "call_X",
            "type": "function",
            "function": {"name": "todo_write", "arguments": "{}"},
        },
        "call_Y": {
            "id": "call_Y",
            "type": "function",
            "function": {"name": "load_skill", "arguments": "{}"},
        },
    }
    new_calls, coerced_id, original_names = (
        _agent()._coerce_invalid_status_only_tool_calls(invalid_calls, language="zh")
    )

    assert coerced_id == "call_X"
    assert set(original_names) == {"todo_write", "load_skill"}
    assert list(new_calls.keys()) == ["call_X"]
    fn = new_calls["call_X"]["function"]
    assert fn["name"] == "turn_status"
    args = json.loads(fn["arguments"])
    assert args["status"] == "continue_work"
    # 中文文案 + 原始工具名注入到 note
    assert "todo_write" in args["note"] and "load_skill" in args["note"]
    assert "turn_status" in args["note"]


def test_turn_status_from_tool_call_reads_continue_work():
    tool_call = {
        "function": {
            "name": "turn_status",
            "arguments": '{"status": "continue_work", "note": "more"}',
        }
    }

    assert _agent()._turn_status_from_tool_call(tool_call) == "continue_work"


def test_env_force_required_does_not_affect_normal_tools(monkeypatch):
    monkeypatch.setenv("SAGE_FORCE_TOOL_CHOICE_REQUIRED", "true")

    assert (
        _agent()._resolve_tool_choice(
            tools_json=[{"function": {"name": "todo_read"}}],
            force_tool_choice_required=False,
            force_tool_choice_auto=False,
        )
        is None
    )


def test_normal_path_omits_tool_choice_without_env_or_escape(monkeypatch):
    monkeypatch.delenv("SAGE_FORCE_TOOL_CHOICE_REQUIRED", raising=False)

    assert (
        _agent()._resolve_tool_choice(
            tools_json=[{"function": {"name": "todo_read"}}],
            force_tool_choice_required=False,
            force_tool_choice_auto=False,
        )
        is None
    )


def test_required_tool_choice_is_omitted_without_tools():
    assert (
        _agent()._resolve_tool_choice(
            tools_json=[],
            force_tool_choice_required=True,
            force_tool_choice_auto=False,
        )
        is None
    )


def test_escape_auto_overrides_env_required_once(monkeypatch):
    monkeypatch.setenv("SAGE_FORCE_TOOL_CHOICE_REQUIRED", "true")

    assert (
        _agent()._resolve_tool_choice(
            tools_json=[{"function": {"name": "todo_read"}}],
            force_tool_choice_required=False,
            force_tool_choice_auto=True,
        )
        == "auto"
    )


def test_required_protocol_turn_overrides_escape_auto(monkeypatch):
    monkeypatch.setenv("SAGE_FORCE_TOOL_CHOICE_REQUIRED", "true")

    assert (
        _agent()._resolve_tool_choice(
            tools_json=[{"function": {"name": "turn_status"}}],
            force_tool_choice_required=True,
            force_tool_choice_auto=True,
        )
        == "required"
    )


def test_env_force_required_only_applies_to_turn_status_only(monkeypatch):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "turn_status")
    monkeypatch.setenv("SAGE_FORCE_TOOL_CHOICE_REQUIRED", "true")

    assert (
        _agent()._resolve_tool_choice(
            tools_json=[{"function": {"name": "turn_status"}}],
            force_tool_choice_required=False,
            force_tool_choice_auto=False,
        )
        == "required"
    )


def test_env_force_required_ignored_outside_turn_status_mode(monkeypatch):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "no_tool_call")
    monkeypatch.setenv("SAGE_FORCE_TOOL_CHOICE_REQUIRED", "true")

    assert (
        _agent()._resolve_tool_choice(
            tools_json=[{"function": {"name": "turn_status"}}],
            force_tool_choice_required=False,
            force_tool_choice_auto=False,
        )
        is None
    )


def test_turn_status_rejection_requests_required_escape():
    chunks = [
        MessageChunk(
            role=MessageRole.TOOL.value,
            content="turn_status call rejected",
            tool_call_id="call_1",
            message_type=MessageType.TOOL_CALL_RESULT.value,
            metadata={"turn_status_rejected": True},
        )
    ]

    assert _agent()._should_escape_required_next_turn(chunks, pattern=None) is True


def test_repeat_pattern_requests_required_escape():
    chunks = [
        MessageChunk(
            role=MessageRole.TOOL.value,
            content="same result",
            tool_call_id="call_1",
            message_type=MessageType.TOOL_CALL_RESULT.value,
        )
    ]

    assert (
        _agent()._should_escape_required_next_turn(
            chunks,
            pattern={"period": 1, "cycles": 2, "span": 2},
        )
        is True
    )


def test_repeat_pattern_self_correction_is_internal_context(monkeypatch):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "no_tool_call")
    agent = _agent()
    agent.max_repeat_pattern_hits = 2
    direct_calls = []

    def _same_tool_result():
        return MessageChunk(
            role=MessageRole.TOOL.value,
            content='{"ok": false, "reason": "same"}',
            tool_call_id="call_same",
            message_type=MessageType.TOOL_CALL_RESULT.value,
        )

    async def _fake_call_llm_and_process_response(**kwargs):
        direct_calls.append(kwargs)
        if len(direct_calls) <= 2:
            yield ([_same_tool_result()], False)
            return

        assert any(
            isinstance(chunk.content, str)
            and chunk.content.startswith("自检：检测到执行出现重复循环模式")
            for chunk in kwargs["messages_input"]
        )
        yield (
            [
                MessageChunk(
                    role=MessageRole.ASSISTANT.value,
                    content="已经换路径继续。",
                    message_type=MessageType.ASSISTANT_TEXT.value,
                )
            ],
            True,
        )

    monkeypatch.setattr(agent, "_should_abort_due_to_session", lambda *args: False)
    monkeypatch.setattr(
        agent, "_call_llm_and_process_response", _fake_call_llm_and_process_response
    )

    session_context = _loop_session_context()

    async def _collect():
        chunks = []
        async for yielded_chunks in agent._execute_loop(
            messages_input=_base_messages(),
            tools_json=[],
            tool_manager=None,
            session_id="s-repeat-internal",
            session_context=session_context,  # pyright: ignore[reportArgumentType]
        ):
            session_context.add_messages(yielded_chunks)
            chunks.extend(yielded_chunks)
        return chunks

    chunks = asyncio.run(_collect())

    assert len(direct_calls) == 3
    correction_chunks = [
        chunk
        for chunk in session_context.stored_messages
        if (chunk.metadata or {}).get("runtime_diagnostic_source")
        == "repeat_pattern_correction"
    ]
    assert len(correction_chunks) == 1
    assert correction_chunks[0].metadata["hidden_from_chat"] is True
    assert correction_chunks[0].metadata["hide_from_chat"] is True
    assert correction_chunks[0].metadata["sse_visible"] is False
    assert correction_chunks[0].metadata["llm_scope"] == "next_request"
    assert correction_chunks[0].metadata["llm_state"] == "pending"
    visible_chunks = [chunk for chunk in chunks if is_message_client_visible(chunk)]
    assert [chunk.content for chunk in visible_chunks] == [
        '{"ok": false, "reason": "same"}',
        '{"ok": false, "reason": "same"}',
        "已经换路径继续。",
    ]


def test_repeat_pattern_break_after_tool_emits_recovery_questionnaire(monkeypatch):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "no_tool_call")
    agent = _agent()
    agent.max_repeat_pattern_hits = 1
    direct_calls = []

    async def _fake_call_llm_and_process_response(**kwargs):
        direct_calls.append(kwargs)
        yield (
            [
                MessageChunk(
                    role=MessageRole.TOOL.value,
                    content='{"ok": false, "reason": "same"}',
                    tool_call_id="call_same",
                    message_type=MessageType.TOOL_CALL_RESULT.value,
                )
            ],
            False,
        )

    monkeypatch.setattr(agent, "_should_abort_due_to_session", lambda *args: False)
    monkeypatch.setattr(
        agent, "_call_llm_and_process_response", _fake_call_llm_and_process_response
    )

    async def _collect():
        chunks = []
        async for yielded_chunks in agent._execute_loop(
            messages_input=_base_messages(),
            tools_json=[],
            tool_manager=None,
            session_id="s-repeat-break",
            session_context=_loop_session_context(),  # pyright: ignore[reportArgumentType]
        ):
            chunks.extend(yielded_chunks)
        return chunks

    chunks = asyncio.run(_collect())

    assert len(direct_calls) == 2
    assert [chunk.role for chunk in chunks] == ["tool", "tool", "assistant"]
    questionnaire = chunks[-1]
    assert "<questionnaire>" in questionnaire.content
    assert "movo-questionnaire" not in questionnaire.content
    assert '"id": "loop_recovery_action"' in questionnaire.content
    assert "Agent 已陷入循环" in questionnaire.content
    assert "请说明你希望我接下来如何处理" in questionnaire.content
    assert '"type": "free_text"' in questionnaire.content
    assert '"options"' not in questionnaire.content
    assert questionnaire.metadata["needs_user_input"] is True
    assert questionnaire.metadata["runtime_notice"] == ("repeat_pattern_questionnaire")
    assert questionnaire.metadata["stop_reason"] == "repeat_pattern"


def test_repeat_pattern_break_after_assistant_text_emits_recovery_questionnaire(
    monkeypatch,
):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "no_tool_call")
    agent = _agent()
    agent.max_repeat_pattern_hits = 1
    direct_calls = []

    async def _fake_call_llm_and_process_response(**kwargs):
        direct_calls.append(kwargs)
        yield (
            [
                MessageChunk(
                    role=MessageRole.ASSISTANT.value,
                    content="仍在尝试相同路径。",
                    message_type=MessageType.ASSISTANT_TEXT.value,
                )
            ],
            False,
        )

    monkeypatch.setattr(agent, "_should_abort_due_to_session", lambda *args: False)
    monkeypatch.setattr(
        agent, "_call_llm_and_process_response", _fake_call_llm_and_process_response
    )
    session_context = _loop_session_context()

    async def _collect():
        chunks = []
        async for yielded_chunks in agent._execute_loop(
            messages_input=_base_messages(),
            tools_json=[],
            tool_manager=None,
            session_id="s-repeat-assistant-break",
            session_context=session_context,  # pyright: ignore[reportArgumentType]
        ):
            chunks.extend(yielded_chunks)
        return chunks

    chunks = asyncio.run(_collect())

    assert len(direct_calls) == 2
    assert [chunk.role for chunk in chunks] == ["assistant", "assistant", "assistant"]
    questionnaire = chunks[-1]
    assert "Agent 已陷入循环" in questionnaire.content
    assert "<questionnaire>" in questionnaire.content
    assert questionnaire.metadata["stop_reason"] == "repeat_pattern"
    assert session_context.audit_status["completion_status"] == "need_user_input"


def test_consecutive_execution_error_emits_recovery_questionnaire(monkeypatch):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "no_tool_call")
    agent = _agent()
    direct_calls = []

    async def _fake_call_llm_and_process_response(**kwargs):
        direct_calls.append(kwargs)
        yield (
            [
                MessageChunk(
                    role=MessageRole.ASSISTANT.value,
                    content="工具参数错误：缺少 path",
                    message_type=MessageType.AGENT_EXECUTION_ERROR.value,
                )
            ],
            False,
        )

    monkeypatch.setattr(agent, "_should_abort_due_to_session", lambda *args: False)
    monkeypatch.setattr(
        agent, "_call_llm_and_process_response", _fake_call_llm_and_process_response
    )
    session_context = _loop_session_context()

    async def _collect():
        chunks = []
        async for yielded_chunks in agent._execute_loop(
            messages_input=_base_messages(),
            tools_json=[],
            tool_manager=None,
            session_id="s-consecutive-error-break",
            session_context=session_context,  # pyright: ignore[reportArgumentType]
        ):
            chunks.extend(yielded_chunks)
        return chunks

    chunks = asyncio.run(_collect())

    assert len(direct_calls) == 2
    questionnaire = chunks[-1]
    assert questionnaire.message_type == MessageType.ASSISTANT_TEXT.value
    assert "Agent 已陷入循环" in questionnaire.content
    assert "<questionnaire>" in questionnaire.content
    assert questionnaire.metadata["stop_reason"] == "consecutive_execution_error"
    assert questionnaire.metadata["error_category"] == "INVALID_ARGS"
    assert questionnaire.metadata["consecutive_error_hits"] == 2
    assert session_context.audit_status["completion_status"] == "need_user_input"


def test_repeat_recovery_questionnaire_stays_unchanged_in_llm_history():
    questionnaire = _agent()._build_repeat_recovery_questionnaire(
        pattern={"mode": "tool_call", "period": 2, "cycles": 2},
    )

    inference = MessageManager.build_inference_view([questionnaire])

    assert "<questionnaire>" in questionnaire.content
    assert len(inference) == 1
    assert inference[0].content == questionnaire.content
    assert "Agent is stuck in a loop" in inference[0].content
    assert "Please describe how you want me to proceed" in inference[0].content


def test_repeat_recovery_questionnaire_uses_session_language():
    agent = _agent()
    pattern = {"mode": "tool_call", "period": 2, "cycles": 2}

    chinese = agent._build_repeat_recovery_questionnaire(
        pattern=pattern,
        language="zh-CN",
    )
    portuguese = agent._build_repeat_recovery_questionnaire(
        pattern=pattern,
        language="pt-BR",
    )

    assert "Agent 已陷入循环" in chinese.content
    assert "补充新的策略、约束或停止要求" in chinese.content
    assert "O Agent entrou em um ciclo" in portuguese.content
    assert "Descreva como voce deseja que eu prossiga" in portuguese.content
    assert '"type": "free_text"' in portuguese.content
    assert '"answer_title": "Respostas do questionario"' in portuguese.content


def test_repeat_recovery_response_accepts_only_sage_frontend_namespaces():
    def user_message(tag: str) -> MessageChunk:
        return MessageChunk(
            role=MessageRole.USER.value,
            content=(
                f"<{tag}-response>"
                '{"answers":[{"question_id":"loop_recovery_action","answer":"继续"}]}'
                f"</{tag}-response>"
            ),
            message_type=MessageType.USER_INPUT.value,
        )

    assert _agent()._latest_user_is_repeat_recovery_response(
        [user_message("questionnaire")]
    ) is True
    assert _agent()._latest_user_is_repeat_recovery_response(
        [user_message("sage-questionnaire")]
    ) is True
    assert _agent()._latest_user_is_repeat_recovery_response(
        [user_message("movo-questionnaire")]
    ) is False
    extra_tag = user_message("questionnaire")
    extra_tag.content = (
        '<questionnaire-response-extra>{"answers":['
        '{"question_id":"loop_recovery_action"}]}'
        "</questionnaire-response-extra>"
    )
    assert _agent()._latest_user_is_repeat_recovery_response([extra_tag]) is False

    malformed = user_message("questionnaire")
    malformed.content = (
        '<questionnaire-response>{"question_id":"loop_recovery_action"}'
        "</questionnaire-response>"
    )
    assert _agent()._latest_user_is_repeat_recovery_response([malformed]) is False


def test_historical_repeat_signature_requests_required_escape():
    agent = _agent()
    chunks = [
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content=None,
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "todo_read",
                        "arguments": '{"session_id":"s1"}',
                    },
                }
            ],
            message_type=MessageType.TOOL_CALL.value,
        ),
        MessageChunk(
            role=MessageRole.TOOL.value,
            content="当前未完成任务清单:\n- [进行中] t12",
            tool_call_id="call_1",
            message_type=MessageType.TOOL_CALL_RESULT.value,
            metadata={"tool_name": "todo_read"},
        ),
    ]
    historical_signature = agent._build_loop_signature(chunks)
    current_signature = agent._build_loop_signature(chunks)

    pattern = agent._detect_repeat_pattern([historical_signature, current_signature])

    assert pattern == {"period": 1, "cycles": 2, "span": 2}
    assert agent._should_escape_required_next_turn(chunks, pattern=pattern) is True


def test_normal_tool_result_does_not_request_required_escape():
    chunks = [
        MessageChunk(
            role=MessageRole.TOOL.value,
            content='{"success":true}',
            tool_call_id="call_1",
            message_type=MessageType.TOOL_CALL_RESULT.value,
        )
    ]

    assert _agent()._should_escape_required_next_turn(chunks, pattern=None) is False

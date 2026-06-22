"""SimpleAgent turn_status 前置文本校验单测。

验证 turn_status 的「先说明再报告状态」契约。
"""

import asyncio
from types import SimpleNamespace

from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.agent.simple_agent import SimpleAgent, _get_system_prefix


class _DummyModel:
    async def astream(self, *args, **kwargs):  # pragma: no cover
        yield None


def _agent():
    return SimpleAgent(model=_DummyModel(), model_config={})


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
    msg_manager = SimpleNamespace(
        get_recent_loop_signatures=lambda: [],
        add_loop_signature=lambda signature: None,
    )
    return SimpleNamespace(
        agent_config={"max_loop_count": max_loop_count},
        audit_status={},
        message_manager=msg_manager,
        get_language=lambda: "zh",
    )


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


def test_status_only_text_without_tool_call_is_hidden_and_errors(monkeypatch):
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
    assert chunks[0].message_type == MessageType.AGENT_EXECUTION_ERROR.value
    assert "模型未按协议调用 turn_status" in chunks[0].content


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


def test_task_completion_mode_turn_status_enables_turn_status_contract(monkeypatch):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "turn_status")

    prompt = _get_system_prefix(_ToolNameManager(["turn_status"]), "en")  # pyright: ignore[reportArgumentType]

    assert "turn_status" in prompt
    assert _agent()._turn_status_enabled() is True


def test_task_completion_mode_llm_judge_disables_turn_status_contract(monkeypatch):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "llm_judge")
    tool_manager = SimpleNamespace(list_all_tools_name=lambda: ["turn_status"])

    assert "turn_status" not in _get_system_prefix(tool_manager, "zh")
    assert _agent()._turn_status_enabled() is False


def test_task_complete_judge_uses_composed_system_prefix_in_llm_judge_mode(
    monkeypatch,
):
    monkeypatch.setenv("SAGE_TASK_COMPLETION_MODE", "llm_judge")
    agent = _agent()
    captured = {}

    async def _never_must_continue(messages):
        return False

    async def _fake_system_messages(**kwargs):
        captured["custom_prefix"] = kwargs["custom_prefix"]
        return [MessageChunk(role="system", content=kwargs["custom_prefix"])]

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
    monkeypatch.setattr(agent, "prepare_unified_system_messages", _fake_system_messages)
    monkeypatch.setattr(agent, "_call_llm_streaming", _fake_llm_streaming)

    msg_manager = SimpleNamespace(
        context_budget_manager=SimpleNamespace(budget_info={"active_budget": 3000}),
    )
    session_context = SimpleNamespace(
        message_manager=msg_manager,
        get_language=lambda: "en",
    )
    tool_manager = _ToolNameManager(["dudu_generate_route_scheme"])
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
            )
        )
        is True
    )
    assert "turn_status" not in captured["custom_prefix"]
    assert "找不到prompt" not in captured["llm_messages"][0]["content"]


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

    async def _fake_is_task_complete(*args, **kwargs):
        judge_calls.append((args, kwargs))
        return True

    monkeypatch.setattr(agent, "_should_abort_due_to_session", lambda *args: False)
    monkeypatch.setattr(
        agent, "_call_llm_and_process_response", _fake_call_llm_and_process_response
    )
    monkeypatch.setattr(agent, "_is_task_complete", _fake_is_task_complete)

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

    async def _fake_is_task_complete(*args, **kwargs):
        judge_calls.append((args, kwargs))
        return True

    monkeypatch.setattr(agent, "_should_abort_due_to_session", lambda *args: False)
    monkeypatch.setattr(
        agent, "_call_llm_and_process_response", _fake_call_llm_and_process_response
    )
    monkeypatch.setattr(agent, "_is_task_complete", _fake_is_task_complete)

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

    assert seen_tool_calls
    assert direct_response_state["had_tool_calls"] is True


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

    assert "turn_status" not in _get_system_prefix(tool_manager, "zh")
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

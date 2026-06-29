import asyncio
import json
from types import SimpleNamespace

from sagents.agent.memory_recall_agent import MemoryRecallAgent
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType


def _llm_chunk(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content))]
    )


def test_memory_recall_error_does_not_emit_orphan_tool_message():
    chunks = asyncio.run(_collect_memory_recall_error_chunks())

    assert len(chunks) == 1
    assert chunks[0].role == MessageRole.ASSISTANT.value
    assert chunks[0].message_type == MessageType.ERROR.value
    assert chunks[0].tool_call_id is None
    assert json.loads(chunks[0].content)["error"] == "context_length_exceeded"


async def _collect_memory_recall_error_chunks():
    agent = MemoryRecallAgent(model=None)

    async def raise_token_error(*_args, **_kwargs):
        raise RuntimeError("context_length_exceeded")

    agent._generate_search_query = raise_token_error  # pyright: ignore[reportAttributeAccessIssue]
    chunks = []

    async for chunk in agent._recall_memories_stream(
        messages_input=[MessageChunk(role=MessageRole.USER.value, content="hello")],
        session_context=None,  # pyright: ignore[reportArgumentType]
    ):
        chunks.extend(chunk)

    return chunks


def test_memory_recall_query_generation_redacts_base64_image_content():
    async def _run():
        agent = MemoryRecallAgent(model=None)
        base64_payload = "a" * 50000
        data_url = f"data:image/png;base64,{base64_payload}"
        captured = {}

        async def fake_get_search_query(llm_request_messages, session_id):
            captured["messages"] = llm_request_messages
            return "video_maker candidate_stories"

        agent._get_search_query = fake_get_search_query  # pyright: ignore[reportAttributeAccessIssue]

        session_context = SimpleNamespace(
            session_id="session-memory-large-user",
            get_language=lambda: "zh",
        )

        query = await agent._generate_search_query(
            messages=[
                {
                    "role": MessageRole.USER.value,
                    "content": [
                        {
                            "type": "text",
                            "text": "video_maker candidate_stories 参考这张图生成故事",
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url},
                        },
                    ],
                }
            ],
            session_context=session_context,  # pyright: ignore[reportArgumentType]
        )

        assert [msg.role for msg in captured["messages"]] == [
            MessageRole.SYSTEM.value,
            MessageRole.USER.value,
        ]
        system_prompt = captured["messages"][0].content
        prompt = captured["messages"][1].content
        assert query == "video_maker candidate_stories"
        assert "记忆召回专家" in system_prompt
        assert "runtime_context" not in prompt
        assert "workspace_files" not in prompt
        assert "video_maker candidate_stories" in prompt
        assert base64_payload not in prompt
        assert "data:image/png;base64" not in prompt
        assert "<redacted data URL; base64_len=50000>" in prompt

    asyncio.run(_run())


def test_memory_recall_query_generation_uses_dedicated_system_prompt_only():
    async def _run():
        agent = MemoryRecallAgent(
            model=None,
            system_prefix="# plan-writer-agent Prompt\n不要出现在 memory recall 请求里",
        )
        captured = {}

        async def fake_get_search_query(llm_request_messages, session_id):
            captured["messages"] = llm_request_messages
            return "AERLUX video_plan recipe"

        agent._get_search_query = fake_get_search_query  # pyright: ignore[reportAttributeAccessIssue]
        session_context = SimpleNamespace(
            session_id="session-memory-dedicated-system",
            get_language=lambda: "zh",
        )

        query = await agent._generate_search_query(
            messages=[
                {
                    "role": MessageRole.USER.value,
                    "content": "更新 AERLUX video-02 video_plan.md，参考 recipe.md",
                }
            ],
            session_context=session_context,  # pyright: ignore[reportArgumentType]
        )

        request_text = "\n".join(str(msg.content) for msg in captured["messages"])
        assert query == "AERLUX video_plan recipe"
        assert "记忆召回专家" in str(captured["messages"][0].content)
        assert "plan-writer-agent" not in request_text
        assert "runtime_context" not in request_text
        assert "workspace_files" not in request_text

    asyncio.run(_run())


def test_memory_recall_prompt_marks_latest_user_request():
    prompt_text = MemoryRecallAgent._format_recall_messages_for_prompt(
        [
            {"role": MessageRole.USER.value, "content": "先保存小托福想法"},
            {
                "role": MessageRole.ASSISTANT.value,
                "content": "已经保存完成。",
            },
            {"role": MessageRole.USER.value, "content": "继续下一个新模型的学习"},
        ]
    )

    assert "user: 先保存小托福想法" in prompt_text
    assert "assistant: 已经保存完成。" in prompt_text
    assert "latest_user_request: 继续下一个新模型的学习" in prompt_text


def test_memory_recall_query_generation_accepts_query_array_from_model(monkeypatch):
    async def _run():
        agent = MemoryRecallAgent(model=None)

        async def fake_call_llm_streaming(*_args, **_kwargs):
            yield _llm_chunk(
                json.dumps(
                    {
                        "query": [
                            "通知提醒",
                            "提醒功能",
                            "闹钟",
                            "定时任务",
                        ]
                    },
                    ensure_ascii=False,
                )
            )

        monkeypatch.setattr(agent, "_call_llm_streaming", fake_call_llm_streaming)

        query = await agent._get_search_query(
            [
                MessageChunk(
                    role=MessageRole.USER.value,
                    content="只返回 JSON",
                    message_type=MessageType.GUIDE.value,
                )
            ],
            "session-memory-query-list",
        )

        assert query == "通知提醒 提醒功能 闹钟 定时任务"

    asyncio.run(_run())


def test_memory_recall_query_generation_searches_nonstandard_json(monkeypatch):
    async def _run(content, expected):
        agent = MemoryRecallAgent(model=None)

        async def fake_call_llm_streaming(*_args, **_kwargs):
            yield _llm_chunk(content)

        monkeypatch.setattr(agent, "_call_llm_streaming", fake_call_llm_streaming)

        query = await agent._get_search_query(
            [MessageChunk(role=MessageRole.USER.value, content="只返回 JSON")],
            "session-memory-nonstandard-json",
        )

        assert query == expected

    asyncio.run(_run('["提醒功能", "定时任务"]', "提醒功能 定时任务"))
    asyncio.run(
        _run(
            '{"keywords": ["通知提醒", "消息推送"], "reason": "用户在测提醒"}',
            "通知提醒 消息推送",
        )
    )


def test_memory_recall_query_context_keeps_recent_ten_turns_and_assistant_context():
    agent = MemoryRecallAgent(model=None)
    messages = [
        MessageChunk(role=MessageRole.USER.value, content="负六轮：最旧的问题"),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="负六轮旧回答，不应该进入最近 query 上下文",
            message_type=MessageType.FINAL_ANSWER.value,
        ),
        MessageChunk(role=MessageRole.USER.value, content="负五轮：仍然太旧"),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="负五轮回答，不应该进入最近 query 上下文",
            message_type=MessageType.FINAL_ANSWER.value,
        ),
        MessageChunk(
            role=MessageRole.USER.value, content="负四轮：刚好在 10 turn 窗口内"
        ),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="负四轮回答：应该保留。",
            message_type=MessageType.FINAL_ANSWER.value,
        ),
        MessageChunk(role=MessageRole.USER.value, content="负三轮：项目 A"),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="负三轮回答：项目 A 已处理。",
            message_type=MessageType.FINAL_ANSWER.value,
        ),
        MessageChunk(role=MessageRole.USER.value, content="负二轮：项目 B"),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="负二轮回答：项目 B 已处理。",
            message_type=MessageType.FINAL_ANSWER.value,
        ),
        MessageChunk(role=MessageRole.USER.value, content="负一轮：项目 C"),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="负一轮回答：项目 C 已处理。",
            message_type=MessageType.FINAL_ANSWER.value,
        ),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="主动消息：提醒用户继续思维模型学习。",
            message_type="system_triggered_run",
        ),
        MessageChunk(role=MessageRole.USER.value, content="第一轮：解释 provider 配置"),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="第一轮回答：provider 配置会被记录。",
            message_type=MessageType.FINAL_ANSWER.value,
        ),
        MessageChunk(role=MessageRole.USER.value, content="第二轮：温度字段为 null"),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content=None,
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "search_memory",
                        "arguments": '{"query":"noisy internal tool query"}',
                    },
                }
            ],
            message_type=MessageType.TOOL_CALL.value,
        ),
        MessageChunk(
            role=MessageRole.TOOL.value,
            content='{"long_term_memory":["noisy tool result"]}',
            tool_call_id="call_1",
            message_type=MessageType.TOOL_CALL_RESULT.value,
        ),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="温度为 null 时最终请求会省略 temperature。",
            message_type=MessageType.FINAL_ANSWER.value,
        ),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="这条补充说明也应该保留，而不是只保留最后一条 assistant。",
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
        MessageChunk(role=MessageRole.USER.value, content="第三轮：检查工具推荐"),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="第三轮回答：工具推荐只应该服务当前请求。",
            message_type=MessageType.FINAL_ANSWER.value,
        ),
        MessageChunk(role=MessageRole.USER.value, content="第四轮：继续下一个模型"),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="第四轮回答：应该根据学习状态找下一个模型。",
            message_type=MessageType.FINAL_ANSWER.value,
        ),
        MessageChunk(role=MessageRole.USER.value, content="第五轮：保存了一个想法"),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="第五轮回答：保存想法已经完成。",
            message_type=MessageType.FINAL_ANSWER.value,
        ),
        MessageChunk(
            role=MessageRole.USER.value, content="现在 memory recall 拿哪些消息？"
        ),
    ]
    message_manager = SimpleNamespace(
        messages=messages, session_id="session-query-context"
    )

    compact = agent._extract_query_context_messages(message_manager)

    assert [(msg.role, msg.content) for msg in compact] == [
        (MessageRole.USER.value, "负四轮：刚好在 10 turn 窗口内"),
        (MessageRole.ASSISTANT.value, "负四轮回答：应该保留。"),
        (MessageRole.USER.value, "负三轮：项目 A"),
        (MessageRole.ASSISTANT.value, "负三轮回答：项目 A 已处理。"),
        (MessageRole.USER.value, "负二轮：项目 B"),
        (MessageRole.ASSISTANT.value, "负二轮回答：项目 B 已处理。"),
        (MessageRole.USER.value, "负一轮：项目 C"),
        (MessageRole.ASSISTANT.value, "负一轮回答：项目 C 已处理。"),
        (
            MessageRole.ASSISTANT.value,
            "主动消息：提醒用户继续思维模型学习。",
        ),
        (MessageRole.USER.value, "第一轮：解释 provider 配置"),
        (MessageRole.ASSISTANT.value, "第一轮回答：provider 配置会被记录。"),
        (MessageRole.USER.value, "第二轮：温度字段为 null"),
        (
            MessageRole.ASSISTANT.value,
            "温度为 null 时最终请求会省略 temperature。",
        ),
        (
            MessageRole.ASSISTANT.value,
            "这条补充说明也应该保留，而不是只保留最后一条 assistant。",
        ),
        (MessageRole.USER.value, "第三轮：检查工具推荐"),
        (MessageRole.ASSISTANT.value, "第三轮回答：工具推荐只应该服务当前请求。"),
        (MessageRole.USER.value, "第四轮：继续下一个模型"),
        (MessageRole.ASSISTANT.value, "第四轮回答：应该根据学习状态找下一个模型。"),
        (MessageRole.USER.value, "第五轮：保存了一个想法"),
        (MessageRole.ASSISTANT.value, "第五轮回答：保存想法已经完成。"),
        (MessageRole.USER.value, "现在 memory recall 拿哪些消息？"),
    ]


def test_memory_recall_query_context_uses_text_only_multimodal_messages():
    agent = MemoryRecallAgent(model=None)
    messages = [
        MessageChunk(
            role=MessageRole.USER.value,
            content=[
                {"type": "text", "text": "看这张图里的 provider 配置"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,abc123"},
                },
            ],
        )
    ]
    message_manager = SimpleNamespace(messages=messages, session_id="session-text-only")

    compact = agent._extract_query_context_messages(message_manager)

    assert len(compact) == 1
    assert compact[0].content == "看这张图里的 provider 配置"


def test_memory_recall_query_context_keeps_assistant_only_context():
    agent = MemoryRecallAgent(model=None)
    messages = [
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="<system_triggered_run>提醒用户继续思维模型学习</system_triggered_run>",
            message_type="system_triggered_run",
        ),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="Ling 主动补充：下一个待学模型是思想实验。",
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
    ]
    message_manager = SimpleNamespace(
        messages=messages, session_id="session-assistant-only"
    )

    compact = agent._extract_query_context_messages(message_manager)

    assert [(msg.role, msg.content) for msg in compact] == [
        (
            MessageRole.ASSISTANT.value,
            "<system_triggered_run>提醒用户继续思维模型学习</system_triggered_run>",
        ),
        (
            MessageRole.ASSISTANT.value,
            "Ling 主动补充：下一个待学模型是思想实验。",
        ),
    ]

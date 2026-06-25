import asyncio
import json
from types import SimpleNamespace

from sagents.agent.memory_recall_agent import MemoryRecallAgent
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType


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


def test_memory_recall_query_context_keeps_user_and_final_assistant_text_only():
    agent = MemoryRecallAgent(model=None)
    messages = [
        MessageChunk(role=MessageRole.USER.value, content="负一轮：最旧的问题"),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="负一轮旧回答，不应该进入最近 query 上下文",
            message_type=MessageType.FINAL_ANSWER.value,
        ),
        MessageChunk(role=MessageRole.USER.value, content="第零轮：很旧的问题"),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="第零轮回答：刚好仍在 4 turn 窗口内。",
            message_type=MessageType.FINAL_ANSWER.value,
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
        MessageChunk(role=MessageRole.USER.value, content="现在 memory recall 拿哪些消息？"),
    ]
    message_manager = SimpleNamespace(messages=messages, session_id="session-query-context")

    compact = agent._extract_query_context_messages(message_manager)

    assert [(msg.role, msg.content) for msg in compact] == [
        (MessageRole.USER.value, "第零轮：很旧的问题"),
        (MessageRole.ASSISTANT.value, "第零轮回答：刚好仍在 4 turn 窗口内。"),
        (MessageRole.USER.value, "第一轮：解释 provider 配置"),
        (MessageRole.ASSISTANT.value, "第一轮回答：provider 配置会被记录。"),
        (MessageRole.USER.value, "第二轮：温度字段为 null"),
        (
            MessageRole.ASSISTANT.value,
            "温度为 null 时最终请求会省略 temperature。",
        ),
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

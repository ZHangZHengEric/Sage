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

        async def fake_prepare_llm_request_messages(**kwargs):
            return kwargs["extra_messages"]

        agent._get_search_query = fake_get_search_query  # pyright: ignore[reportAttributeAccessIssue]
        agent.prepare_llm_request_messages = fake_prepare_llm_request_messages  # pyright: ignore[reportMethodAssign]

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

        prompt = captured["messages"][0].content
        assert query == "video_maker candidate_stories"
        assert "video_maker candidate_stories" in prompt
        assert base64_payload not in prompt
        assert "data:image/png;base64" not in prompt
        assert "<redacted data URL; base64_len=50000>" in prompt

    asyncio.run(_run())

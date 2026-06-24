import asyncio
from types import SimpleNamespace

from sagents.context.messages.message import MessageType
from sagents.session_runtime import Session


def test_token_usage_chunk_has_top_level_session_id():
    session = Session.__new__(Session)
    session_context = SimpleNamespace(
        get_tokens_usage_info=lambda: {
            "total_info": {"total_tokens": 7},
            "per_step_info": [],
            "models": [],
        },
        agent_config={"llmConfig": {"model": "test-model"}},
    )

    chunks = asyncio.run(
        session._emit_token_usage_if_any(session_context, "child-session")
    )

    assert len(chunks) == 1
    assert chunks[0].type == MessageType.TOKEN_USAGE.value
    assert chunks[0].session_id == "child-session"
    assert chunks[0].metadata["session_id"] == "child-session"

import asyncio
from types import SimpleNamespace

from sagents.utils.subtask_summary import (
    compact_subtask_history,
    split_history_chunks,
    summarize_subtask_history,
)


def test_compact_subtask_history_preserves_important_lines():
    history = "\n".join(
        [
            "start",
            "/tmp/project/output.mp4 created",
            *(f"middle {idx}" for idx in range(200)),
            "Status: success",
            "Result: finished",
        ]
    )

    digest = compact_subtask_history(history, max_chars=1200)

    assert "/tmp/project/output.mp4" in digest
    assert "Status: success" in digest
    assert "中间内容已压缩" in digest


def test_split_history_chunks_uses_large_line_preserving_chunks():
    history = "\n".join(f"message {idx}" for idx in range(20))

    chunks = split_history_chunks(history, chunk_chars=50)

    assert len(chunks) > 1
    assert all(len(chunk) <= 60 for chunk in chunks)
    assert "message 0" in chunks[0]
    assert "message 19" in chunks[-1]


class _FakeAgent:
    def __init__(self):
        self.prompts = []

    def _call_llm_streaming(self, *, messages, session_id, step_name):
        self.prompts.append(
            {
                "messages": messages,
                "session_id": session_id,
                "step_name": step_name,
            }
        )

        async def _stream():
            content = f"summary for {step_name}"
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=content))]
            )

        return _stream()


def test_summarize_subtask_history_rolls_up_large_histories():
    agent = _FakeAgent()
    history = "\n".join(f"step {idx}: wrote /tmp/file-{idx}.txt" for idx in range(1500))

    result = asyncio.run(
        summarize_subtask_history(
            agent=agent,
            session_id="child-session",
            summary_session_id="parent-session",
            history_str=history,
            language="en",
            task_description="Prepare clips for scene one",
            subject_label="Team member",
            step_name="member_summary",
        )
    )

    assert len(agent.prompts) > 1
    assert "Prepare clips for scene one" in agent.prompts[0]["messages"][0]["content"]
    assert "截至上一块的融合总结" in agent.prompts[1]["messages"][0]["content"]
    assert "child-session" in result
    assert "Team member execution summary" in result


def test_summarize_subtask_history_falls_back_to_digest_without_agent():
    result = asyncio.run(
        summarize_subtask_history(
            agent=None,
            session_id="child-session",
            summary_session_id="parent-session",
            history_str="created /tmp/result.txt",
            language="en",
            task_description="Create a render result",
        )
    )

    assert "Create a render result" in result
    assert "/tmp/result.txt" in result

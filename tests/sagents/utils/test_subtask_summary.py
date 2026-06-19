import asyncio
from types import SimpleNamespace

import httpx

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
        self.model = object()
        self.model_config = {"model": "fake-summary-model", "max_model_len": 1000}


def _fake_summary_completion(captured):
    async def _call(*args, **kwargs):
        captured.append(kwargs)
        step_name = kwargs["extra_body"]["_step_name"]

        async def _stream():
            content = f"summary for {step_name}"
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=content))]
            )

        return _stream()

    return _call


def test_summarize_subtask_history_rolls_up_large_histories(monkeypatch):
    agent = _FakeAgent()
    captured = []
    monkeypatch.setattr(
        "sagents.utils.subtask_summary.create_chat_completion_with_fallback",
        _fake_summary_completion(captured),
    )
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

    assert len(captured) > 1
    assert captured[0]["model"] == "fake-summary-model"
    assert "max_model_len" not in captured[0]
    assert "Prepare clips for scene one" in captured[0]["messages"][0]["content"]
    assert "截至上一块的融合总结" in captured[1]["messages"][0]["content"]
    assert "child-session" in result
    assert "Team member execution summary" in result
    assert captured[0]["extra_body"]["chat_template_kwargs"] == {
        "enable_thinking": False
    }
    assert captured[0]["extra_body"]["enable_thinking"] is False
    assert captured[0]["extra_body"]["thinking"] == {"type": "disabled"}


def test_summarize_subtask_history_retries_before_stream_yields(monkeypatch):
    agent = _FakeAgent()
    attempts = []

    async def fake_completion(*args, **kwargs):
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise httpx.ReadTimeout("before first byte")

        async def _stream():
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="retry summary"))]
            )

        return _stream()

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(
        "sagents.utils.subtask_summary.create_chat_completion_with_fallback",
        fake_completion,
    )
    monkeypatch.setattr("sagents.utils.subtask_summary.asyncio.sleep", no_sleep)

    result = asyncio.run(
        summarize_subtask_history(
            agent=agent,
            session_id="child-session",
            summary_session_id="parent-session",
            history_str="created /tmp/result.txt",
            language="en",
            task_description="Create a render result",
        )
    )

    assert len(attempts) == 2
    assert "retry summary" in result


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

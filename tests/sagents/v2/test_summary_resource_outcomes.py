import json

from sagents.v2.context import ContextReductionScope
from sagents.v2.context.progress_summary import task_snapshot
from sagents.v2.context.summary import SummarizationRequest
from sagents.v2.contracts.items import ImageBlock, TextBlock
from sagents.v2.model import ModelMessage, ModelToolCall


def snapshot(messages, previous=None):
    return task_snapshot(
        SummarizationRequest(
            scope=ContextReductionScope(context_key="x", session_id="x", run_id="x"),
            messages=tuple(messages),
            previous_summary=previous,
            target_tokens=1024,
        )
    )


def pair(call_id, item, run, status, project="p"):
    return (
        ModelMessage(
            role="assistant",
            tool_calls=(
                ModelToolCall(
                    tool_call_id=call_id,
                    name="project_get_item",
                    arguments={"item_id": item, "project_id": project, "run_id": run},
                ),
            ),
        ),
        ModelMessage(
            role="tool",
            tool_call_id=call_id,
            content=(TextBlock(text=json.dumps({"status": status})),),
        ),
    )


def test_resource_versions_and_projects_do_not_overwrite_each_other_but_retries_do():
    first = snapshot(
        [
            *pair("1", "A", "v1", "failed"),
            *pair("2", "B", "v1", "succeeded"),
            *pair("3", "A", "v2", "succeeded"),
            *pair("4", "A", "v1", "succeeded", project="other"),
        ]
    )
    outcomes = first["tool_outcomes"]
    assert len(outcomes) == 4
    assert sum(v["status"] == "failed" for v in outcomes.values()) == 1
    retried = snapshot(pair("5", "A", "v1", "succeeded"), json.dumps(first))[
        "tool_outcomes"
    ]
    assert len(retried) == 4 and all(
        v["status"] == "completed" for v in retried.values()
    )


def test_long_path_prefixes_do_not_collide_and_image_followups_are_not_user_requirements():
    source = [
        ModelMessage(role="user", content=(TextBlock(text="actual user request"),))
    ]
    for n in range(2):
        source.extend(
            (
                ModelMessage(
                    role="assistant",
                    tool_calls=(
                        ModelToolCall(
                            tool_call_id=str(n),
                            name="file_read",
                            arguments={"file_path": "/long/" + "a" * 400 + str(n)},
                        ),
                    ),
                ),
                ModelMessage(
                    role="tool", tool_call_id=str(n), content=(TextBlock(text="ok"),)
                ),
            )
        )
    source.append(
        ModelMessage(
            role="user",
            content=(
                ImageBlock(uri="https://example.invalid/image", mime_type="image/png"),
            ),
            metadata={"tool_context": True},
        )
    )
    result = snapshot(source)
    assert len(result["tool_outcomes"]) == 2
    assert result["user_requirements"] == ["actual user request"]


def test_unknown_selectors_remain_distinct_and_pending_is_not_completion():
    messages = []
    for index, payload in enumerate(({"status": "running"}, {"exit_code": 2})):
        messages.extend(
            (
                ModelMessage(
                    role="assistant",
                    tool_calls=(
                        ModelToolCall(
                            tool_call_id=str(index),
                            name="custom_tool",
                            arguments={"resource": index},
                        ),
                    ),
                ),
                ModelMessage(
                    role="tool",
                    tool_call_id=str(index),
                    content=(TextBlock(text=json.dumps(payload)),),
                ),
            )
        )
    outcomes = snapshot(messages)["tool_outcomes"]
    assert len(outcomes) == 2
    assert {fact["status"] for fact in outcomes.values()} == {"running", "failed"}

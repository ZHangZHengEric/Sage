"""Wire-level regression coverage for thinking binding and durable replay."""

import copy

import pytest

from sagents.v2.contracts.items import TextBlock
from sagents.v2.model import (
    AnthropicMessagesConfig,
    AnthropicMessagesModelProvider,
    ModelMessage,
)
from tests.sagents.v2.test_builtin_model_protocols_matrix import (
    CAPABILITIES,
    FakeHTTPClient,
    request,
)


async def captured_turn(**config):
    transformations = [
        {
            "type": "thinking_dropped",
            "path": "messages.1.content.0",
            "reason": "prefix_binding_mismatch",
        }
    ]
    blocks = [
        {"type": "text", "text": "Before thinking"},
        {"type": "thinking", "thinking": "reason", "signature": "signed"},
        {"type": "redacted_thinking", "data": "opaque"},
        {
            "type": "tool_use",
            "id": "question",
            "name": "lookup",
            "input": {"q": "question"},
        },
    ]
    client = FakeHTTPClient(
        (
            {
                "type": "message_start",
                "message": {"id": "response", "input_transformations": transformations},
            },
            *(
                {"type": "content_block_start", "index": index, "content_block": block}
                for index, block in enumerate(blocks)
            ),
            {"type": "message_stop"},
        )
    )
    provider = AnthropicMessagesModelProvider(
        AnthropicMessagesConfig(model="test", capabilities=CAPABILITIES, **config),
        client=client,
    )
    events = [event async for event in provider.stream(request())]
    response = events[-1].response
    assistant = ModelMessage(
        role="assistant",
        tool_calls=response.tool_calls,
        provider_state=response.provider_state,
    )
    reply = ModelMessage(
        role="tool", tool_call_id="question", content=(TextBlock(text="answer"),)
    )
    return provider, response, assistant, reply, blocks, transformations


@pytest.mark.asyncio
async def test_order_and_transformations_survive_restart():
    (
        provider,
        response,
        assistant,
        reply,
        blocks,
        transformations,
    ) = await captured_turn()
    restarted = AnthropicMessagesModelProvider(
        provider.config, client=FakeHTTPClient(())
    )
    wire = restarted.diagnostic_request(
        request(run_id="new-run", messages=(*request().messages, assistant, reply))
    )
    assert wire["messages"][-2]["content"] == blocks
    assert response.provider_metadata["input_transformations"] == transformations


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    ["compression", "questionnaire", "sandbox", "system", "tools", "child_agent"],
)
async def test_changed_prefix_drops_only_thinking(change):
    provider, _, assistant, reply, _, _ = await captured_turn()
    messages = list(request().messages)
    changes = {}
    if change in {"sandbox", "system", "child_agent"}:
        messages[0] = ModelMessage(role="system", content=(TextBlock(text=change),))
    elif change == "compression":
        messages = [
            messages[0],
            ModelMessage(role="user", content=(TextBlock(text="summary"),)),
        ]
    elif change == "questionnaire":
        messages[1] = ModelMessage(
            role="user", content=(TextBlock(text="original user text"),)
        )
    else:
        changes["tools"] = ()
    original = copy.deepcopy(assistant.provider_state)
    wire = provider.diagnostic_request(
        request(messages=(*messages, assistant, reply), **changes)
    )
    assert [block["type"] for block in wire["messages"][-2]["content"]] == [
        "text",
        "tool_use",
    ]
    assert wire["messages"][-1]["content"][0]["tool_use_id"] == "question"
    assert assistant.provider_state == original
    # A separate agent's request cannot poison the first agent's history.
    unchanged = provider.diagnostic_request(
        request(messages=(*request().messages, assistant, reply))
    )
    assert unchanged["messages"][-2]["content"][1]["signature"] == "signed"


@pytest.mark.asyncio
async def test_beta_merges_and_server_controls_legacy_or_changed_history():
    provider, _, assistant, reply, blocks, _ = await captured_turn(
        reasoning_effort="high",
        thinking_prefix_mismatch_behavior="drop_block",
        extra_headers={
            "Anthropic-Beta": "other-beta,thinking-binding-controls-2026-08-01"
        },
        extra_body={"thinking": {"display": "omitted"}},
    )
    wire = provider.diagnostic_request(
        request(
            messages=(
                ModelMessage(role="user", content=(TextBlock(text="summary"),)),
                assistant,
                reply,
            )
        )
    )
    assert wire["thinking"] == {
        "type": "adaptive",
        "display": "omitted",
        "block_binding": {"prefix_mismatch_behavior": "drop_block"},
    }
    assert wire["messages"][1]["content"] == blocks
    assert provider.raw_client.calls[0][2]["headers"] == {
        "anthropic-beta": "other-beta,thinking-binding-controls-2026-08-01"
    }
    assert provider.config.extra_body == {"thinking": {"display": "omitted"}}


def test_partial_extra_body_thinking_merges_with_native_defaults():
    provider = AnthropicMessagesModelProvider(
        AnthropicMessagesConfig(
            model="test",
            capabilities=CAPABILITIES,
            reasoning_effort="high",
            extra_headers={"anthropic-beta": "existing"},
            extra_body={
                "thinking": {
                    "block_binding": {"prefix_mismatch_behavior": "drop_block"}
                }
            },
        ),
        client=FakeHTTPClient(()),
    )
    payload = provider.diagnostic_request(request())
    assert payload["thinking"]["type"] == "adaptive"
    assert payload["thinking"]["display"] == "summarized"
    assert (
        payload["thinking"]["block_binding"]["prefix_mismatch_behavior"] == "drop_block"
    )
    assert (
        provider.request_headers()["anthropic-beta"]
        == "existing,thinking-binding-controls-2026-08-01"
    )


@pytest.mark.asyncio
async def test_first_mismatch_removes_all_later_thinking():
    provider, _, assistant, reply, _, _ = await captured_turn()
    first_messages = (*request().messages, assistant, reply)
    events = [
        event async for event in provider.stream(request(messages=first_messages))
    ]
    second = ModelMessage(
        role="assistant", provider_state=events[-1].response.provider_state
    )
    # A compaction changes the first response's prefix; neither signed response
    # can survive, but both tool calls and results must remain.
    wire = provider.diagnostic_request(
        request(messages=(*first_messages[1:], second, reply))
    )
    assert not any(
        block["type"] in {"thinking", "redacted_thinking"}
        for message in wire["messages"]
        for block in message["content"]
    )
    assert (
        sum(
            block["type"] == "tool_use"
            for message in wire["messages"]
            for block in message["content"]
        )
        == 3
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("adjacent_assistants", [False, True])
async def test_cleaned_prefix_preserves_new_thinking_across_multiple_turns(
    adjacent_assistants,
):
    provider, _, old, reply, _, _ = await captured_turn()
    history = (
        ModelMessage(role="system", content=(TextBlock(text="changed system"),)),
        *request().messages[1:],
        old,
        *((reply,) if not adjacent_assistants else ()),
    )
    original_state = copy.deepcopy(old.provider_state)
    for turn in range(3):
        events = [event async for event in provider.stream(request(messages=history))]
        response = events[-1].response
        sent = copy.deepcopy(provider.raw_client.calls[-1][2]["json"])
        assert response.provider_state["anthropic_messages"]["payload"][
            "prefix_digest"
        ] == provider._prefix_digest(sent, sent["messages"])
        new = ModelMessage(role="assistant", provider_state=response.provider_state)
        history = (*history, new, *((reply,) if not adjacent_assistants else ()))
        # Restarting the provider must not lose the cleaned-prefix baseline.
        provider = AnthropicMessagesModelProvider(
            provider.config, client=provider.raw_client
        )
        replay = provider.diagnostic_request(request(messages=history))
        thinking = [
            block
            for message in replay["messages"]
            for block in message["content"]
            if block["type"] in {"thinking", "redacted_thinking"}
        ]
        assert len(thinking) == 2 * (turn + 1)
        assert old.provider_state == original_state


@pytest.mark.parametrize("binding_source", ["config", "extra_body"])
@pytest.mark.parametrize(
    "strategy,expected_effort",
    [
        ({}, "low"),
        (
            {
                "reasoning_disable_strategy": "thinking_type_disabled",
                "supported_reasoning_efforts": ["high", "medium"],
            },
            "medium",
        ),
        (
            {"reasoning_disable_strategy": "omit", "supported_reasoning_efforts": []},
            None,
        ),
    ],
)
def test_minimum_with_binding_uses_adaptive_and_lowest_supported_effort(
    binding_source, strategy, expected_effort
):
    binding = {"prefix_mismatch_behavior": "drop_block"}
    extra = {"thinking": {"display": "omitted"}}
    options = {}
    if binding_source == "config":
        options["thinking_prefix_mismatch_behavior"] = "drop_block"
    else:
        extra["thinking"]["block_binding"] = binding
    provider = AnthropicMessagesModelProvider(
        AnthropicMessagesConfig(
            model="test",
            capabilities=CAPABILITIES,
            reasoning_effort="high",
            invocation_strategy=strategy,
            default_temperature=0.2,
            default_top_p=0.9,
            extra_body=extra,
            **options,
        ),
        client=FakeHTTPClient(()),
    )
    original = provider.config.model_dump()
    primary = provider.diagnostic_request(request())
    minimum = provider.diagnostic_request(request(reasoning_mode="minimum"))
    assert minimum["thinking"] == {
        "type": "adaptive",
        "display": "omitted",
        "block_binding": binding,
    }
    assert minimum.get("output_config", {}).get("effort") == expected_effort
    assert "temperature" not in minimum
    assert "top_p" not in minimum
    assert provider.diagnostic_request(request()) == primary
    assert provider.config.model_dump() == original


@pytest.mark.asyncio
@pytest.mark.parametrize("initial_citations", [None, []])
async def test_nullable_citations_stream_and_replay(initial_citations):
    citation = {
        "type": "char_location",
        "cited_text": "source",
        "document_index": 0,
        "start_char_index": 0,
        "end_char_index": 6,
    }
    client = FakeHTTPClient(
        (
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "text",
                    "text": "",
                    "citations": initial_citations,
                },
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "answer"},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "citations_delta", "citation": citation},
            },
            {"type": "message_stop"},
        )
    )
    provider = AnthropicMessagesModelProvider(
        AnthropicMessagesConfig(model="test", capabilities=CAPABILITIES), client=client
    )
    events = [event async for event in provider.stream(request())]
    response = events[-1].response
    assert response.text == "answer"
    replay = provider.diagnostic_request(
        request(
            messages=(
                *request().messages,
                ModelMessage(role="assistant", provider_state=response.provider_state),
            )
        )
    )
    assert replay["messages"][-1]["content"] == [
        {"type": "text", "text": "answer", "citations": [citation]}
    ]


@pytest.mark.parametrize("limit", ["count", "single", "body"])
async def test_over_budget_images_become_text_references(limit, tmp_path):
    from sagents.v2.contracts.items import ImageBlock

    from types import SimpleNamespace

    from sagents.v2.runtime.artifact.workspace_images import bind_image_workspace
    from tests.sagents.v2.test_local_workspace_sandbox_matrix import authorization, provision

    images = (
        ImageBlock(uri="data:image/png;base64," + "YWFh" * 300, mime_type="image/png"),
        ImageBlock(uri="data:image/png;base64,YmJi", mime_type="image/png"),
    )
    limits = {
        "count": {"max_inline_images": 1},
        "single": {"max_inline_image_bytes": 100},
        "body": {"max_request_bytes": 1_000},
    }
    client = FakeHTTPClient(({"type": "message_stop"},))
    provider = AnthropicMessagesModelProvider(
        AnthropicMessagesConfig(model="test", capabilities=CAPABILITIES, **limits[limit]),
        client=client,
    )
    req = request(messages=tuple(ModelMessage(role="user", content=(image,)) for image in images), tools=())
    issuer, handle = await provision(tmp_path, process_enabled=False)
    with bind_image_workspace(SimpleNamespace(sandbox=handle, grant_issuer=issuer)):
        [event async for event in provider.stream(req)]
    content = client.calls[0][2]["json"]["messages"][0]["content"]
    assert [block["type"] for block in content] == ["text", "image"]
    assert content[1]["source"]["data"] == "YmJi"
    relative = content[0]["text"].removeprefix("[Workspace image: ").removesuffix("]")
    assert relative.startswith(".sage-model-images/")
    path = handle.filesystem.normalize_path(relative)
    intent, grant = authorization(issuer, handle, "read", path=path)
    assert await handle.filesystem.read_bytes(path, intent=intent, grant=grant) == b"a" * 900
    assert len(list((tmp_path / ".sage-model-images").glob("*.png"))) == 1
    assert tuple(message.content[0] for message in req.messages) == images


async def test_messages_413_retries_once_with_smaller_body_then_stops(tmp_path):
    import httpx

    from sagents.v2.contracts.errors import SageV2Error
    from sagents.v2.contracts.items import ImageBlock

    from types import SimpleNamespace

    from sagents.v2.runtime.artifact.workspace_images import bind_image_workspace
    from tests.sagents.v2.test_local_workspace_sandbox_matrix import provision

    issuer, handle = await provision(tmp_path, process_enabled=False)
    bodies = []

    def rejected(req):
        bodies.append(req.content)
        return httpx.Response(413, json={"error": {"type": "request_too_large"}})

    async with httpx.AsyncClient(
        base_url="https://example.com", transport=httpx.MockTransport(rejected),
    ) as client:
        provider = AnthropicMessagesModelProvider(
            AnthropicMessagesConfig(model="test", capabilities=CAPABILITIES),
            client=client,
        )
        image = ImageBlock(uri="data:image/png;base64," + "YWFh" * 300, mime_type="image/png")
        req = request(messages=(ModelMessage(role="user", content=(image,)),), tools=())
        with bind_image_workspace(SimpleNamespace(sandbox=handle, grant_issuer=issuer)):
            with pytest.raises(SageV2Error) as exc:
                [event async for event in provider.stream(req)]
    assert exc.value.info.code == "model.request_too_large"
    assert len(bodies) == 2 and len(bodies[1]) < len(bodies[0])
    assert b'"type":"image"' in bodies[0]
    assert b'"type":"image"' not in bodies[1]


async def test_non_media_body_over_limit_never_reaches_http():
    from sagents.v2.contracts.errors import SageV2Error

    client = FakeHTTPClient(())
    provider = AnthropicMessagesModelProvider(
        AnthropicMessagesConfig(model="test", capabilities=CAPABILITIES, max_request_bytes=500),
        client=client,
    )
    req = request(messages=(ModelMessage(role="user", content=(TextBlock(text="图" * 300),)),), tools=())
    with pytest.raises(SageV2Error) as exc:
        [event async for event in provider.stream(req)]
    assert exc.value.info.code == "model.request_too_large"
    assert exc.value.info.metadata["request_bytes"] > 900
    assert not client.calls


@pytest.mark.parametrize("resume", [False, True])
async def test_agent_loop_binds_workspace_for_model_image_fallback(tmp_path, resume):
    from types import SimpleNamespace

    from sagents.v2.contracts.items import ImageBlock
    from sagents.v2.contracts.commands import PauseRun, ResumeRun
    from tests.sagents.v2.test_agent_loop_matrix import AgentLoopCheckpointState, CONTEXT, setup_loop
    from tests.sagents.v2.test_local_workspace_sandbox_matrix import provision

    client = FakeHTTPClient((
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "text", "text": "Finished."}},
        {"type": "message_stop"},
    ))
    provider = AnthropicMessagesModelProvider(
        AnthropicMessagesConfig(model="test", capabilities=CAPABILITIES, max_inline_images=0),
        client=client,
    )
    image = ImageBlock(uri="data:image/png;base64,YmJi", mime_type="image/png")

    class ImageModel:
        capabilities = provider.capabilities

        def stream(self, req):
            messages = (*req.messages, ModelMessage(role="user", content=(image,)))
            return provider.stream(req.model_copy(update={"messages": messages}))

    issuer, handle = await provision(tmp_path, process_enabled=False)
    runtime, run, loop, _ = await setup_loop(ImageModel(), tools=())
    loop.tool_result_runtime = SimpleNamespace(sandbox=handle, grant_issuer=issuer)
    if resume:
        running = await runtime.start_execution(
            run_id=run.run_id, expected_revision=0, context=CONTEXT,
            idempotency_key="start-execution",
        )
        await runtime.pause_run(PauseRun(
            run_id=run.run_id, expected_revision=running.revision, idempotency_key="pause",
        ), CONTEXT)
        state = AgentLoopCheckpointState(
            turn_id="turn_1", step_number=1,
            messages=await loop.context_assembler.initial_ledger(
                await runtime.session_store.get_start_command(run.run_id), run_id=run.run_id,
            ),
        )
        suspended = await loop._suspend_at_safe_point(
            await runtime.get_run(run.run_id), state, CONTEXT,
        )
        suspension = await runtime.session_store.get_suspension(suspended.suspension_id)
        await runtime.resume_run(ResumeRun(
            run_id=run.run_id, expected_revision=suspended.revision, idempotency_key="resume",
            suspension_id=suspension.suspension_id,
            expected_suspension_revision=suspension.expected_revision,
        ), CONTEXT)
        result = await loop.resume(run.run_id, CONTEXT)
    else:
        result = await loop.execute(run.run_id, CONTEXT)
    assert result.state.value == "completed"
    assert list((tmp_path / ".sage-model-images").glob("*.png"))[0].read_bytes() == b"bbb"

"""Delegating to another agent, as a Tool call.

The A2A bridge turns a peer's Agent Card into Tools and one Tool call into one
``SendMessage``. These tests pin the two halves of that translation that a
caller can actually be hurt by: what the model is told it can do, and what
happens to a delegation whose answer never arrives.
"""

from __future__ import annotations

import asyncio

import pytest

from sagents.v2.contracts.errors import ErrorCategory, SageV2Error
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.tool import A2AAgentConfig, A2AToolPlugin, ToolCall
from sagents.v2.tool.plugins.a2a import CALL_DEPTH_KEY

CONTEXT = RequestContext(
    actor=ActorRef(principal_id="user_1", principal_type=PrincipalType.USER)
)

CARD = {
    "name": "Researcher",
    "description": "Reads the web.",
    "skills": [
        {"id": "research", "name": "Research", "description": "Answers questions."}
    ],
    "supportedInterfaces": [
        {
            "url": "https://peer.example.com/a2a/v1",
            "protocolBinding": "JSONRPC",
            "protocolVersion": "1.0",
        }
    ],
}


def completed(text: str = "the answer", state: str = "TASK_STATE_COMPLETED") -> dict:
    return {
        "jsonrpc": "2.0",
        "id": "1",
        "result": {
            "task": {
                "id": "task-1",
                "contextId": "ctx-1",
                "status": {"state": state},
                "history": [
                    {"role": "ROLE_USER", "parts": [{"text": "the question"}]},
                    {"role": "ROLE_AGENT", "parts": [{"text": text}]},
                ],
            }
        },
    }


class FakePeer:
    """A peer that answers however the test says, and records what it was sent."""

    def __init__(self, card: dict | None = None, answer: object = None) -> None:
        self._card = CARD if card is None else card
        self._answer = answer if answer is not None else completed()
        self.sent: list[tuple[str, dict]] = []

    async def card(self, config):
        if isinstance(self._card, Exception):
            raise self._card
        return self._card

    async def send(self, config, endpoint, payload):
        self.sent.append((endpoint, payload))
        if isinstance(self._answer, Exception):
            raise self._answer
        return self._answer


def peer(url: str = "https://peer.example.com", **options) -> A2AAgentConfig:
    return A2AAgentConfig(name="researcher", url=url, **options)


def make_call(name: str, arguments: dict, *, key: str = "idem-1") -> ToolCall:
    return ToolCall(
        tool_call_id="call-1",
        tool_name=name,
        arguments=arguments,
        operation_id="op-1",
        idempotency_key=key,
        owner_run_id="run-1",
    )


async def one_tool(transport, **options) -> tuple[A2AToolPlugin, str]:
    plugin = A2AToolPlugin((peer(),), transport=transport, **options)
    definitions = await plugin.list_tools(run_id="run-1")
    return plugin, definitions[0].name


async def test_a_card_skill_becomes_a_tool_that_names_its_peer():
    """The model picks between Tools by reading them, and "research" is not enough.

    Asking the wrong organisation a question is not undone by retrying, so who
    is being addressed belongs in the description rather than only in the
    prefix of a name the model may not parse.
    """

    plugin, name = await one_tool(FakePeer())

    assert name == "a2a_researcher_research"
    definition = await plugin.get_tool(name, run_id="run-1")
    assert "researcher" in definition.description
    assert "Answers questions." in definition.description
    assert definition.requires_approval is True


async def test_a_delegation_announces_the_hop_it_creates():
    """A peer cannot see it is already inside a delegation unless it is told."""

    transport = FakePeer()
    plugin, name = await one_tool(transport, call_depth=2)

    await plugin.execute(make_call(name, {"message": "what is the news"}), CONTEXT)

    _endpoint, payload = transport.sent[0]
    assert payload["params"]["message"]["metadata"][CALL_DEPTH_KEY] == 3


async def test_the_message_id_is_the_call_s_idempotency_key():
    """A2A dedupes on messageId, which is the one end-to-end guarantee here.

    Minting a fresh id per attempt would throw it away: a retried delegation
    would run twice on the peer with nothing able to notice.
    """

    transport = FakePeer()
    plugin, name = await one_tool(transport)

    await plugin.execute(
        make_call(name, {"message": "hello"}, key="idem-abc"), CONTEXT
    )

    assert transport.sent[0][1]["params"]["message"]["messageId"] == "idem-abc"


async def test_the_answer_and_the_ids_to_continue_it_come_back_together():
    """Continuation is a fact in the transcript, not hidden state in the plugin."""

    plugin, name = await one_tool(FakePeer())

    result = await plugin.execute(make_call(name, {"message": "hi"}), CONTEXT)

    assert result.error is None
    assert isinstance(result.content[0], TextBlock)
    assert result.content[0].text == "the answer"
    assert result.content[1].value["contextId"] == "ctx-1"
    assert result.metadata["a2a_context_id"] == "ctx-1"


async def test_a_context_id_is_forwarded_so_a_conversation_continues():
    transport = FakePeer()
    plugin, name = await one_tool(transport)

    await plugin.execute(
        make_call(name, {"message": "and then?", "context_id": "ctx-1"}), CONTEXT
    )

    assert transport.sent[0][1]["params"]["message"]["contextId"] == "ctx-1"


async def test_a_peer_that_stopped_to_ask_says_so_in_the_answer():
    """Otherwise the model reports a half-finished delegation as the result."""

    transport = FakePeer(
        answer=completed("which year?", state="TASK_STATE_INPUT_REQUIRED")
    )
    plugin, name = await one_tool(transport)

    result = await plugin.execute(make_call(name, {"message": "hi"}), CONTEXT)

    assert result.error is None
    assert "needs more information" in result.content[0].text
    assert "which year?" in result.content[0].text
    assert result.metadata["a2a_task_state"] == "TASK_STATE_INPUT_REQUIRED"


async def test_a_refusal_from_the_peer_is_a_tool_error_not_a_dead_run():
    """The peer decided. That is an answer the model can react to."""

    transport = FakePeer(
        answer={
            "jsonrpc": "2.0",
            "id": "1",
            "error": {"code": -32602, "message": "messageId is required"},
        }
    )
    plugin, name = await one_tool(transport)

    result = await plugin.execute(make_call(name, {"message": "hi"}), CONTEXT)

    assert result.error is not None
    assert result.error.code == "a2a.peer_error"
    assert result.error.safe_to_resume is True
    assert "messageId is required" in result.content[0].text


async def test_a_lost_answer_is_reported_as_an_uncertain_side_effect():
    """The peer may have done the work anyway; a retry must not be automatic."""

    transport = FakePeer(answer=ConnectionError("connection reset"))
    plugin, name = await one_tool(transport)

    with pytest.raises(SageV2Error) as raised:
        await plugin.execute(make_call(name, {"message": "hi"}), CONTEXT)

    assert raised.value.info.code == "a2a.result_not_received"
    assert raised.value.info.category is ErrorCategory.UNCERTAIN_SIDE_EFFECT
    assert raised.value.info.safe_to_resume is False


async def test_a_lost_answer_is_not_retried_under_the_same_key():
    """Replaying the call would be the second chance the failure warned about."""

    transport = FakePeer(answer=ConnectionError("connection reset"))
    plugin, name = await one_tool(transport)
    with pytest.raises(SageV2Error):
        await plugin.execute(make_call(name, {"message": "hi"}), CONTEXT)

    with pytest.raises(SageV2Error):
        await plugin.execute(make_call(name, {"message": "hi"}), CONTEXT)

    assert len(transport.sent) == 1


async def test_the_same_call_twice_sends_one_message():
    transport = FakePeer()
    plugin, name = await one_tool(transport)
    call = make_call(name, {"message": "hi"})

    first = await plugin.execute(call, CONTEXT)
    second = await plugin.execute(call, CONTEXT)

    assert first is second
    assert len(transport.sent) == 1


async def test_concurrent_calls_on_one_key_share_a_single_delegation():
    started = asyncio.Event()
    release = asyncio.Event()

    class SlowPeer(FakePeer):
        async def send(self, config, endpoint, payload):
            self.sent.append((endpoint, payload))
            started.set()
            await release.wait()
            return completed()

    transport = SlowPeer()
    plugin, name = await one_tool(transport)
    call = make_call(name, {"message": "hi"})

    first = asyncio.create_task(plugin.execute(call, CONTEXT))
    await started.wait()
    second = asyncio.create_task(plugin.execute(call, CONTEXT))
    await asyncio.sleep(0)
    release.set()

    assert (await first) is (await second)
    assert len(transport.sent) == 1


async def test_a_card_cannot_redirect_the_credential_to_another_host():
    """The tenant vouched for one host, and that is where their key may go.

    A card names its own endpoint so a peer can move, but honouring a move to
    a different host would let anyone who can edit the card harvest the
    credential this client attaches to every call.
    """

    transport = FakePeer(
        card={
            **CARD,
            "supportedInterfaces": [
                {
                    "url": "https://attacker.example.net/a2a/v1",
                    "protocolBinding": "JSONRPC",
                }
            ],
        }
    )
    plugin, name = await one_tool(transport)

    await plugin.execute(make_call(name, {"message": "hi"}), CONTEXT)

    assert transport.sent[0][0] == "https://peer.example.com"


async def test_a_card_may_move_its_endpoint_within_the_configured_host():
    transport = FakePeer()
    plugin, name = await one_tool(transport)

    await plugin.execute(make_call(name, {"message": "hi"}), CONTEXT)

    assert transport.sent[0][0] == "https://peer.example.com/a2a/v1"


async def test_an_unreachable_optional_peer_costs_its_tools_and_nothing_else():
    """Discovery is a read, so failing it cannot have left anything behind."""

    plugin = A2AToolPlugin(
        (peer(),), transport=FakePeer(card=ConnectionError("no route"))
    )

    definitions = await plugin.list_tools(run_id="run-1")

    assert definitions == ()
    errors = plugin.discovery_errors()
    assert errors["researcher"].code == "a2a.discovery_failed"
    assert errors["researcher"].retryable is True


async def test_a_required_peer_that_cannot_be_read_fails_the_composition():
    plugin = A2AToolPlugin(
        (peer(required=True),), transport=FakePeer(card=ConnectionError("no route"))
    )

    with pytest.raises(SageV2Error) as raised:
        await plugin.list_tools(run_id="run-1")

    assert raised.value.info.code == "a2a.discovery_failed"


async def test_a_delegation_with_no_message_is_rejected_before_it_is_sent():
    transport = FakePeer()
    plugin, name = await one_tool(transport)

    with pytest.raises(SageV2Error) as raised:
        await plugin.execute(make_call(name, {"context_id": "ctx-1"}), CONTEXT)

    assert raised.value.info.code == "tool.arguments_invalid"
    assert raised.value.info.metadata["side_effect_state"] == "not_applied"
    assert transport.sent == []


async def test_rotating_the_peer_s_key_changes_the_cache_identity():
    """The fingerprint must move with the credential without ever exposing it."""

    first = A2AToolPlugin.servers_fingerprint((peer(api_key="one"),))
    second = A2AToolPlugin.servers_fingerprint((peer(api_key="two"),))

    assert first != second
    assert "one" not in first and "two" not in second


async def test_a_released_run_forgets_its_calls():
    transport = FakePeer()
    plugin, name = await one_tool(transport)
    call = make_call(name, {"message": "hi"})
    await plugin.execute(call, CONTEXT)

    await plugin.release_run("run-1")
    await plugin.execute(call, CONTEXT)

    assert len(transport.sent) == 2

"""AstrBot transport contracts without importing its optional host runtime."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from integrations.astrbot_plugin_sage.bridge import MessageSource, SageBridge
from integrations.astrbot_plugin_sage.client import BridgeError, SageClient
from integrations.astrbot_plugin_sage.config import BridgeConfig


class MemoryStore:
    def __init__(self):
        self.values = {}

    async def get_kv_data(self, key, default=None):
        return json.loads(json.dumps(self.values.get(key, default)))

    async def put_kv_data(self, key, value):
        self.values[key] = json.loads(json.dumps(value))


def config(**updates):
    return BridgeConfig.model_validate(
        {
            "enabled": True,
            "server_url": "http://sage:8090",
            "wait_seconds": 0,
            "bindings": [
                {
                    "platform_id": "lark-team-a",
                    "api_key_env": "SAGE_TEAM_A_KEY",
                    "allowed_sender_ids": ["alice", "bob"],
                }
            ],
            **updates,
        }
    )


def source(**updates):
    return MessageSource(
        **{
            "platform_id": "lark-team-a",
            "origin": "lark-team-a:GroupMessage:group-1",
            "sender_id": "alice",
            "message_id": "message-1",
            **updates,
        }
    )


def task(context_id, *, task_id="run-1", state="TASK_STATE_COMPLETED", text="hello"):
    return {
        "id": task_id,
        "contextId": context_id,
        "status": {"state": state},
        "history": [
            {"role": "ROLE_USER", "parts": [{"text": "private input"}]},
            {"role": "ROLE_AGENT", "parts": [{"text": text}]},
        ],
    }


@pytest.fixture(autouse=True)
def credential(monkeypatch):
    monkeypatch.setenv("SAGE_TEAM_A_KEY", "sage_a2a.team-a.secret")


def test_configuration_rejects_ambiguous_routes_and_unsafe_urls():
    binding = config().bindings[0].model_dump()
    for values in (
        {"bindings": [binding, binding]},
        {"server_url": "https://user:password@sage.example"},
        {"server_url": "file:///etc/passwd"},
        {"server_url": "https://sage.example?api_key=secret"},
        {"bindings": [{**binding, "allowed_sender_ids": []}]},
    ):
        with pytest.raises(ValidationError):
            config(**values)


async def test_authorization_precedes_storage_and_network():
    def unexpected(request):
        pytest.fail("unauthorized message reached Sage")

    store = MemoryStore()
    async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected)) as http:
        bridge = SageBridge(config(), SageClient(http, config()), store)
        with pytest.raises(BridgeError, match="未授权"):
            await bridge.handle(source(sender_id="mallory"), [{"text": "hi"}])
    assert not store.values


async def test_tenants_senders_and_origins_have_separate_persistent_contexts():
    messages = []
    tasks = {}

    def reply(request):
        body = json.loads(request.content)
        if body["method"] == "GetTask":
            result = tasks[body["params"]["id"]]
        else:
            message = body["params"]["message"]
            messages.append((request.headers["authorization"], message))
            created = task(message["contextId"], task_id=f"run-{len(messages)}")
            tasks[created["id"]] = created
            result = {"task": created}
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": result,
            },
        )

    store = MemoryStore()
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as http:
        bridge = SageBridge(config(), SageClient(http, config()), store)
        assert (await bridge.handle(source(), [{"text": "one"}])).text == "hello"
        # A fresh plugin object reuses the durable context, not process memory.
        bridge = SageBridge(config(), SageClient(http, config()), store)
        await bridge.handle(source(message_id="message-2"), [{"text": "two"}])
        await bridge.handle(source(sender_id="bob"), [{"text": "three"}])
        await bridge.handle(
            source(origin="lark-team-a:GroupMessage:group-2"), [{"text": "four"}]
        )
    contexts = [message["contextId"] for _, message in messages]
    assert contexts[0] == contexts[1]
    assert len(set(contexts)) == 3
    assert all(auth == "Bearer sage_a2a.team-a.secret" for auth, _ in messages)


async def test_uncertain_submission_recovers_with_the_same_idempotency_key():
    sent = []

    def reply(request):
        body = json.loads(request.content)
        message = body["params"]["message"]
        sent.append(message)
        if len(sent) == 1:
            raise httpx.ReadTimeout("lost response", request=request)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {"task": task(message["contextId"])},
            },
        )

    store = MemoryStore()
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as http:
        bridge = SageBridge(config(), SageClient(http, config()), store)
        with pytest.raises(BridgeError):
            await bridge.handle(source(), [{"text": "write a note"}])
        bridge = SageBridge(config(), SageClient(http, config()), store)
        result = await bridge.handle(source(message_id="status-1"), command="status")
    assert result.text == "hello"
    assert sent[0] == sent[1]


async def test_active_task_blocks_new_input_and_can_be_cancelled():
    methods = []
    context_id = ""

    def reply(request):
        nonlocal context_id
        body = json.loads(request.content)
        methods.append(body["method"])
        if body["method"] == "SendMessage":
            context_id = body["params"]["message"]["contextId"]
        state = (
            "TASK_STATE_CANCELED"
            if body["method"] == "CancelTask"
            else "TASK_STATE_WORKING"
        )
        result = task(context_id, state=state)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {"task": result}
                if body["method"] == "SendMessage"
                else result,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as http:
        bridge = SageBridge(config(), SageClient(http, config()), MemoryStore())
        await bridge.handle(source(), [{"text": "one"}])
        assert (
            "执行"
            in (
                await bridge.handle(source(message_id="message-2"), [{"text": "two"}])
            ).text
        )
        assert (
            "取消"
            in (
                await bridge.handle(source(message_id="cancel-1"), command="cancel")
            ).text
        )
    assert methods.count("SendMessage") == 1
    assert methods[-1] == "CancelTask"


async def test_concurrent_submissions_do_not_start_two_runs_in_one_conversation():
    requests = []

    async def reply(request):
        body = json.loads(request.content)
        requests.append(body)
        if body["method"] == "SendMessage":
            await asyncio.sleep(0)
            context_id = body["params"]["message"]["contextId"]
        else:
            context_id = requests[0]["params"]["message"]["contextId"]
        result = task(context_id, state="TASK_STATE_WORKING")
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {"task": result}
                if body["method"] == "SendMessage"
                else result,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as http:
        bridge = SageBridge(config(), SageClient(http, config()), MemoryStore())
        await asyncio.gather(
            bridge.handle(source(), [{"text": "one"}]),
            bridge.handle(source(message_id="message-2"), [{"text": "two"}]),
        )
    assert sum(body["method"] == "SendMessage" for body in requests) == 1


@pytest.mark.parametrize(
    "response",
    [
        {"jsonrpc": "2.0", "id": "wrong", "result": {}},
        {"jsonrpc": "2.0", "error": {"message": "sensitive server detail"}},
        {"jsonrpc": "2.0", "result": {"task": {"status": {"state": "unknown"}}}},
    ],
)
async def test_protocol_errors_do_not_expose_server_details(response):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=response)
        )
    ) as http:
        bridge = SageBridge(config(), SageClient(http, config()), MemoryStore())
        with pytest.raises(BridgeError) as raised:
            await bridge.handle(source(), [{"text": "hi"}])
    assert "sensitive" not in str(raised.value)


@pytest.mark.parametrize(
    "change",
    [
        {"contextId": "other-tenant-context"},
        {"id": ""},
        {"status": {"state": "unknown"}},
    ],
)
async def test_invalid_or_mismatched_tasks_are_rejected(change):
    def reply(request):
        body = json.loads(request.content)
        created = task(body["params"]["message"]["contextId"])
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {"task": {**created, **change}},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as http:
        bridge = SageBridge(config(), SageClient(http, config()), MemoryStore())
        with pytest.raises(BridgeError):
            await bridge.handle(source(), [{"text": "hi"}])


@pytest.mark.parametrize("status", [302, 401, 403, 500])
async def test_http_failures_do_not_follow_redirects_or_expose_response_bodies(status):
    requests = []

    def reply(request):
        requests.append(request)
        return httpx.Response(
            status,
            text="private traceback",
            headers={"location": "https://other.example"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as http:
        bridge = SageBridge(config(), SageClient(http, config()), MemoryStore())
        with pytest.raises(BridgeError) as raised:
            await bridge.handle(source(), [{"text": "hi"}])
    assert len(requests) == 1
    assert "traceback" not in str(raised.value)


async def test_missing_credential_does_not_persist_or_submit(monkeypatch):
    monkeypatch.delenv("SAGE_TEAM_A_KEY")
    store = MemoryStore()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: pytest.fail("missing credential reached Sage")
        )
    ) as http:
        bridge = SageBridge(config(), SageClient(http, config()), store)
        with pytest.raises(BridgeError, match="凭据"):
            await bridge.handle(source(), [{"text": "hi"}])
    assert not store.values


async def test_key_rotation_does_not_adopt_previous_credentials_context(monkeypatch):
    contexts = []

    def reply(request):
        body = json.loads(request.content)
        assert body["method"] == "SendMessage"
        context = body["params"]["message"]["contextId"]
        contexts.append(context)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {"task": task(context)},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as http:
        bridge = SageBridge(config(), SageClient(http, config()), MemoryStore())
        await bridge.handle(source(), [{"text": "first"}])
        monkeypatch.setenv("SAGE_TEAM_A_KEY", "sage_a2a.other-owner.secret")
        await bridge.handle(source(message_id="message-2"), [{"text": "second"}])
    assert contexts[0] != contexts[1]


@pytest.mark.parametrize("status", [200, 403])
async def test_definitively_rejected_input_does_not_block_reset(status):
    requests = []

    def reject(request):
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(
            status,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "error": {"code": -32602, "message": "private validation detail"},
            },
        )

    store = MemoryStore()
    async with httpx.AsyncClient(transport=httpx.MockTransport(reject)) as http:
        bridge = SageBridge(config(), SageClient(http, config()), store)
        with pytest.raises(BridgeError):
            await bridge.handle(source(), [{"text": "rejected input"}])
        result = await bridge.handle(source(message_id="new-1"), command="new")
        assert "新" in result.text
    assert len(requests) == 1


async def test_rejected_retry_cannot_erase_an_earlier_uncertain_submission():
    messages = []

    def reply(request):
        body = json.loads(request.content)
        message = body["params"]["message"]
        messages.append(message)
        if len(messages) == 1:
            raise httpx.ReadTimeout("accepted but response lost", request=request)
        if len(messages) == 2:
            return httpx.Response(403)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {"task": task(message["contextId"])},
            },
        )

    store = MemoryStore()
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as http:
        bridge = SageBridge(config(), SageClient(http, config()), store)
        with pytest.raises(BridgeError):
            await bridge.handle(source(), [{"text": "write a note"}])
        with pytest.raises(BridgeError):
            await bridge.handle(source(message_id="new-1"), command="new")
        saved = next(iter(store.values.values()))
        assert saved["pending"] is not None
        assert saved["pending_uncertain"] is True
        assert (
            await bridge.handle(source(message_id="status-1"), command="status")
        ).text == "hello"
    assert messages[0] == messages[1] == messages[2]


@pytest.mark.parametrize("finish_during_cancel", [False, True])
async def test_cancel_reports_terminal_status_including_completion_races(
    finish_during_cancel,
):
    methods = []
    context_id = ""
    reads = 0

    def reply(request):
        nonlocal context_id, reads
        body = json.loads(request.content)
        method = body["method"]
        methods.append(method)
        if method == "SendMessage":
            context_id = body["params"]["message"]["contextId"]
            result = {"task": task(context_id, state="TASK_STATE_WORKING")}
        elif method == "CancelTask":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "error": {"code": -32002, "message": "finished concurrently"},
                },
            )
        else:
            reads += 1
            state = (
                "TASK_STATE_WORKING"
                if finish_during_cancel and reads == 1
                else "TASK_STATE_COMPLETED"
            )
            result = task(context_id, state=state)
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": body["id"], "result": result}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as http:
        bridge = SageBridge(config(), SageClient(http, config()), MemoryStore())
        await bridge.handle(source(), [{"text": "one"}])
        assert (
            await bridge.handle(source(message_id="cancel-1"), command="cancel")
        ).text == "hello"
    assert ("CancelTask" in methods) is finish_during_cancel

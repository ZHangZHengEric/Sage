"""Real Desktop HTTP/assembly fixture; only model responses are deterministic."""

import asyncio
import json
import os
from pathlib import Path
import secrets
import socket
import sys

import uvicorn

from app.v2.desktop.backend.app import create_app
from app.v2.desktop.backend.schemas import ModelProviderPatch
from app.v2.desktop.backend.service import DesktopV2Service
from sagents.v2.model import ModelEventKind, ModelResponse, ModelStreamEvent
from sagents.v2.testing.plugins.scripted_model import ScriptedModelProvider


class ConversationModel(ScriptedModelProvider):
    def __init__(self):
        super().__init__(())
        self.turns = 0

    async def stream(self, request):
        purpose = request.metadata.get("purpose")
        if purpose == "continuation_judge":
            text = json.dumps({"decision": "completed", "reason": "test completed"})
        elif purpose:
            text = json.dumps({"tools": [], "queries": []})
        else:
            self.turns += 1
            if self.turns == 2:
                assert any(
                    message.role == "assistant"
                    and "Unified reply 1" in message.model_dump_json()
                    for message in request.messages
                ), "follow-up must include persisted first-turn history"
            text = f"Unified reply {self.turns}"
            yield ModelStreamEvent(kind=ModelEventKind.TEXT_DELTA, delta=text)
        yield ModelStreamEvent(
            kind=ModelEventKind.COMPLETED,
            response=ModelResponse(
                response_id=secrets.token_hex(8), text=text, finish_reason="stop"
            ),
        )


class TestDesktopService(DesktopV2Service):
    model = ConversationModel()

    async def _model_provider(self, provider, agent, *, enable_thinking=None):
        return self.model


async def main():
    token = secrets.token_urlsafe(24)
    root = Path(sys.argv[1])
    live_catalog = os.environ.get("SAGE_DESKTOP_LIVE_CATALOG")
    if live_catalog:
        root.chmod(0o700)
        state = json.loads(Path(live_catalog).read_text())
        providers = [
            value for value in state["model_providers"] if value.get("api_key")
        ]
        agent = state["agents"][0]
        selected = os.environ.get("SAGE_DESKTOP_LIVE_MODEL") or agent["config"].get(
            "llm_provider_id"
        )
        provider = next(value for value in providers if value["id"] == selected)
        agent["config"].update(
            {
                "llm_provider_id": provider["id"],
                "fast_llm_provider_id": provider["id"],
                "availableTools": [],
                "availableSkills": [],
            }
        )
        state["agents"] = [agent]
        state["mcp_connections"] = []
        directory = root / "runtime"
        directory.mkdir(exist_ok=True)
        catalog = directory / "desktop-catalog.json"
        catalog.write_text(json.dumps(state))
        catalog.chmod(0o600)
        service = DesktopV2Service(root)
    else:
        service = TestDesktopService(root)
        await service.list_agents("default_user")
        await service.patch_model_provider(
            "model_main",
            ModelProviderPatch(api_keys=["offline-fixture"]),
            "default_user",
        )
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    app = create_app(service=service, auth_token=token)
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    while not server.started:
        if task.done():
            await task
        await asyncio.sleep(0.01)
    print(json.dumps({"port": sock.getsockname()[1], "token": token}), flush=True)
    await task


if __name__ == "__main__":
    asyncio.run(main())

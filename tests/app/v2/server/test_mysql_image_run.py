"""The public Agent Run route attaches images through a real MySQL SessionStore."""

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from anyio.from_thread import BlockingPortal
    from app.v2.server.conversations.agui.service import ConversationService

import base64
import hashlib
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.v2.server.bootstrap import ServerHost
from app.v2.server.conversations.external_runs import selected_run
from app.v2.server.database import Database, DatabaseSettings
from app.v2.server.main import create_app
from sagents.v2.model.contracts import ModelMessage
from sagents.v2.contracts.items import ImageBlock
from sagents.v2.runtime.artifact import SessionArtifactStore
from sagents.v2.runtime.artifact.images import hydrate_image_blocks
from sagents.v2.testing.plugins import ScriptedModelProvider
from tests.app.v2.server.conftest import CompletingJudgeModel, make_settings
from tests.app.v2.server.test_a2a_resume import _step
from tests.app.v2.server.test_external_chat import setup_agent


def test_public_run_analyzes_image_with_mysql_and_reads_it_after_restart(tmp_path):
    dsn = os.environ.get("SAGE_V2_TEST_MYSQL_DSN", "").strip()
    if not dsn:
        pytest.skip("set SAGE_V2_TEST_MYSQL_DSN to run live MySQL tests")
    model = ScriptedModelProvider(
        (
            # Relative tool paths resolve inside the admitted workspace on
            # both Linux's /workspace mount and native host test runtimes.
            _step(1, "", "analyze_image", {"image_path": "frame.png"}),
            _step(2, "Image received."),
        )
    )
    settings = make_settings(tmp_path, mysql_url=dsn)
    thread_id = "image-thread-" + uuid.uuid4().hex

    def host():
        return ServerHost(
            settings,
            model_provider=CompletingJudgeModel(model),
            database=Database(
                DatabaseSettings(url=f"sqlite+aiosqlite:///{tmp_path}/host.db")
            ),
        )

    service = host()
    with TestClient(create_app(service)) as client:
        token = setup_agent(client)
        agent_id = client.headers["SAGE-AGENT-ID"]
        updated = client.put(
            f"/api/agents/{agent_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Image test", "tools": ["analyze_image"]},
        )
        assert updated.status_code == 200, updated.text
        root = service.paths.workspace_dir("image-tenant", agent_id)
        root.mkdir(parents=True, exist_ok=True)
        path = root / "frame.png"
        Image.new("RGB", (32, 32), "red").save(path)
        response = client.post(
            f"/api/agents/{agent_id}/runs",
            headers={"SAGE-TENANT-ID": "image-tenant"},
            json={
                "threadId": thread_id,
                "runId": "image-run",
                "messages": [{"id": "m", "role": "user", "content": "Inspect image"}],
            },
        )
        assert response.status_code == 200, response.text
        assert "RUN_FINISHED" in response.text
        images = [
            b
            for m in model.requests[-1].messages
            for b in m.content
            if isinstance(b, ImageBlock)
        ]
        assert len(images) == 1, [m.model_dump(mode="json") for m in model.requests[-1].messages if m.role == "tool"]
        assert images[0].uri.startswith("data:image/jpeg;base64,")
        digest = hashlib.sha256(
            base64.b64decode(images[0].uri.split(",", 1)[1])
        ).hexdigest()
        path.unlink()

    restarted = host()
    with TestClient(create_app(restarted)) as client:

        async def restore():
            details = await selected_run(
                restarted.conversations,
                tenant_id="image-tenant",
                agent_id=agent_id,
                thread_id=thread_id,
                run_id="image-run",
            )
            assert details[0]["state"] == "completed"
            return await hydrate_image_blocks(
                (
                    ModelMessage(
                        role="user",
                        content=(
                            ImageBlock(
                                uri="sage-image:" + digest,
                                mime_type="image/jpeg",
                            ),
                        ),
                    ),
                ),
                SessionArtifactStore(
                    cast('ConversationService', restarted.conversations).application.entrypoint().runtime.session_store,
                    details[1],
                ),
            )

        messages = cast('BlockingPortal', client.portal).call(restore)
        assert cast(ImageBlock, messages[0].content[0]).uri == images[0].uri

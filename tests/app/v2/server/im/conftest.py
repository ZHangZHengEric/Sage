import pytest

from app.v2.server.im.feishu import FeishuChannel
from tests.app.v2.server.conftest import make_test_service
from tests.app.v2.server.im.test_feishu import config


@pytest.fixture
def feishu_creation_probe(monkeypatch):
    """Gateway tests isolate Feishu I/O; protocol transport tests stay untouched."""

    async def probe(self):
        return None

    async def start(self, admit):
        self.state = "connected"

    async def send(self, chat, text, delivery_id):
        return "receipt-" + delivery_id

    monkeypatch.setattr(FeishuChannel, "probe", probe)
    monkeypatch.setattr(FeishuChannel, "start", start)
    monkeypatch.setattr(FeishuChannel, "send", send)


@pytest.fixture
async def im_host(tmp_path, feishu_creation_probe):
    host = make_test_service(
        tmp_path,
        log_level="warning",
    )
    await host.start()
    host.im.pause()  # Tests advance durable workers explicitly, without timing races.
    user = await host.identity.register("im-owner", "secret1")
    if isinstance(user, dict):
        user = await host.users.get_by_username("im-owner")
    catalog = await host.catalog.get(user.user_id)
    conn = await host.im.create(
        user.user_id, catalog.agents[0].id, "Private bot", config().model_dump()
    )
    yield host, conn, user
    await host.close()

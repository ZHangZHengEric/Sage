import pytest

from app.v2.server.im.feishu import FeishuChannel


@pytest.fixture
def feishu_creation_probe(monkeypatch):
    """Gateway tests isolate Feishu I/O; protocol transport tests stay untouched."""

    async def probe(self):
        return None

    monkeypatch.setattr(FeishuChannel, "probe", probe)

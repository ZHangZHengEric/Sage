from types import SimpleNamespace

import pytest

from app.desktop.core.routers import chat as chat_module
from common.core.exceptions import SageHTTPException
from common.schemas.chat import StreamRequest


def test_validate_and_prepare_request_returns_503_when_chat_client_uninitialized(
    monkeypatch,
):
    request = StreamRequest(
        messages=[{"role": "user", "content": "hi"}],  # pyright: ignore[reportArgumentType]
        session_id="session-no-client",
    )

    def _raise_uninitialized():
        raise RuntimeError("Chat client not initialized")

    monkeypatch.setattr(chat_module, "get_chat_client", _raise_uninitialized)

    with pytest.raises(SageHTTPException) as exc_info:
        chat_module.validate_and_prepare_request(request, SimpleNamespace())  # pyright: ignore[reportArgumentType]

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "模型客户端未配置或不可用"
    assert (
        exc_info.value.error_detail == "Model client is not configured or unavailable"
    )

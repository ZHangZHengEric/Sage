from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.server_v2.core.observability.context import create_request_id, request_context

Send = Callable[[dict], Awaitable[None]]


class RequestIdMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {
            key.decode().lower(): value.decode()
            for key, value in scope.get("headers", [])
        }
        request_id = (headers.get("x-request-id") or "").strip() or create_request_id()
        scope.setdefault("state", {})
        scope["state"]["request_id"] = request_id

        async def send_with_request_id(message: dict) -> None:
            if message["type"] == "http.response.start":
                raw = list(message.get("headers") or [])
                raw.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": raw}
            await send(message)

        with request_context(
            request_id,
            path=scope.get("path", ""),
            method=scope.get("method", ""),
        ):
            await self.app(scope, receive, send_with_request_id)

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from common.core.render import Response
from ..services.browser_capability import (
    get_browser_capability_coordinator,
    get_browser_tool_sync_state,
    probe_extension,
)
from ..services.browser_bridge import BrowserBridgeHub
from ..user_context import get_desktop_user_id


browser_extension_router = APIRouter(
    prefix="/api/browser-extension", tags=["Browser Extension"]
)


class ExtensionHeartbeatRequest(BaseModel):
    extension_id: str | None = None
    extension_version: str | None = None
    active_tab: dict[str, Any] | None = None
    page_context: dict[str, Any] | None = None
    capabilities: list[str] | None = None


class CommandCreateRequest(BaseModel):
    action: str = Field(..., min_length=1)
    args: dict[str, Any] | None = None


class CommandResultRequest(BaseModel):
    success: bool = True
    result: Any = None
    error: str | None = None


@browser_extension_router.get("/status")
async def extension_status(http_request: Request):
    user_id = get_desktop_user_id(http_request)
    return await Response.succ(
        message="browser.status_loaded",
        data=await get_browser_tool_sync_state(user_id),
    )


@browser_extension_router.post("/probe")
async def extension_probe(
    http_request: Request,
    timeout: float = Query(default=5.0, ge=0.5, le=30.0),
):
    """主动 ping 浏览器扩展。超时即强制标记离线，便于前端立刻刷新。"""
    user_id = get_desktop_user_id(http_request)
    return await Response.succ(
        message="browser.probe_done",
        data=await probe_extension(user_id, timeout_seconds=timeout),
    )


@browser_extension_router.post("/heartbeat")
async def extension_heartbeat(req: ExtensionHeartbeatRequest, http_request: Request):
    user_id = get_desktop_user_id(http_request)
    hub = BrowserBridgeHub.get_instance()
    await hub.heartbeat(
        user_id=user_id,
        extension_id=req.extension_id,
        extension_version=req.extension_version,
        active_tab=req.active_tab,
        page_context=req.page_context,
        capabilities=req.capabilities,
    )
    get_browser_capability_coordinator().notify_activity()
    data = await get_browser_tool_sync_state(user_id)
    return await Response.succ(message="browser.heartbeat_updated", data=data)


@browser_extension_router.post("/commands")
async def create_command(req: CommandCreateRequest, http_request: Request):
    user_id = get_desktop_user_id(http_request)
    hub = BrowserBridgeHub.get_instance()
    command = await hub.enqueue_command(
        user_id=user_id, action=req.action, args=req.args or {}
    )
    return await Response.succ(message="browser.command_created", data=command)


@browser_extension_router.get("/commands/poll")
async def poll_command(
    http_request: Request,
    timeout: float = Query(default=20.0, ge=0.0, le=120.0),
):
    user_id = get_desktop_user_id(http_request)
    hub = BrowserBridgeHub.get_instance()
    command = await hub.poll_command(user_id=user_id, timeout_seconds=timeout)
    return await Response.succ(
        message="browser.command_poll_success",
        data={"command": command},
    )


@browser_extension_router.post("/commands/{command_id}/result")
async def submit_command_result(
    command_id: str, req: CommandResultRequest, http_request: Request
):
    user_id = get_desktop_user_id(http_request)
    hub = BrowserBridgeHub.get_instance()
    result = await hub.submit_command_result(
        user_id=user_id,
        command_id=command_id,
        success=req.success,
        result=req.result,
        error=req.error,
    )
    return await Response.succ(message="browser.command_result_submitted", data=result)


@browser_extension_router.get("/commands/{command_id}/result")
async def wait_command_result(
    command_id: str,
    timeout: float = Query(default=30.0, ge=0.0, le=180.0),
):
    hub = BrowserBridgeHub.get_instance()
    result = await hub.wait_command_result(
        command_id=command_id, timeout_seconds=timeout
    )
    return await Response.succ(
        message="browser.command_result_loaded",
        data={"done": result is not None, "result": result},
    )

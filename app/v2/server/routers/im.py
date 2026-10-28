"""Authenticated IM management and platform-authenticated Feishu Webhooks."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.v2.server.im.feishu import FeishuConfig
from app.v2.server.im.repository import error
from app.v2.server.im.service import IMService
from .deps import CurrentUser, HostDep
from .render import success
from .schemas.common import ApiResponse, AUTH_ERRORS, ErrorBody
from .schemas.im import (
    IMConnectionPublic,
    IMConnectionPage,
    IMPluginPage,
    IMPairingPublic,
    IMStatusPublic,
    IMDeliveryPage,
)

router = APIRouter(
    prefix="/api/im",
    tags=["im"],
    responses={
        **AUTH_ERRORS,
        403: {"model": ErrorBody},
        404: {"model": ErrorBody},
        409: {"model": ErrorBody},
        422: {"model": ErrorBody},
    },
)


def get_im(host: HostDep) -> IMService:
    if host.im is None:
        raise HTTPException(503, "IM is not started")
    return host.im


IMDep = Annotated[IMService, Depends(get_im)]


class CreateConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str = Field(min_length=1, max_length=191)
    name: str = Field(min_length=1, max_length=128)
    config: FeishuConfig


class UpdateConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(strict=True, ge=1)
    enabled: bool = Field(strict=True)


class RetryDelivery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(strict=True, ge=1)
    allow_duplicate: bool = Field(False, strict=True)


def public(row, service):
    base = service.host.settings.public_base_url.rstrip("/")
    return {
        "id": row.id,
        "name": row.name,
        "plugin": "com.sage.im.feishu",
        "owner_user_id": row.owner_id,
        "agent_id": row.agent_id,
        "config": {key: row.config[key] for key in ("app_id", "tenant_key")},
        "credentials_configured": bool(row.config.get("credentials_ciphertext")),
        "credentials_error": service.credentials_error(row.id),
        "enabled": row.enabled,
        "revision": row.revision,
        "paired": bool(row.sender_id),
        "webhook_url": base + "/api/im/webhooks/" + row.id if base else "",
    }


@router.get("/plugins", response_model=ApiResponse[IMPluginPage])
async def plugins(user: CurrentUser):
    return success(
        {
            "items": [
                {
                    "id": "com.sage.im.feishu",
                    "name": "飞书",
                    "config_schema": FeishuConfig.model_json_schema(),
                    "capabilities": [
                        "webhook",
                        "private_text",
                        "final_reply",
                        "approval_link",
                    ],
                }
            ],
            "next_cursor": None,
        }
    )


@router.post("/connections", response_model=ApiResponse[IMConnectionPublic])
async def create(body: CreateConnection, user: CurrentUser, service: IMDep):
    try:
        row = await service.create(
            user.user_id, body.agent_id, body.name, body.config.model_dump()
        )
    except (ValueError, ValidationError):
        raise error(
            "invalid_config",
            "Invalid IM configuration",
        ) from None
    return success(public(row, service))


@router.get("/connections", response_model=ApiResponse[IMConnectionPage])
async def connections(user: CurrentUser, service: IMDep):
    return success(
        {
            "items": [
                public(row, service)
                for row in await service.store.list_connections(user.user_id)
            ],
            "next_cursor": None,
        }
    )


@router.get("/connections/{cid}", response_model=ApiResponse[IMConnectionPublic])
async def connection(cid: str, user: CurrentUser, service: IMDep):
    return success(public(await service.store.get(cid, user.user_id), service))


@router.patch("/connections/{cid}", response_model=ApiResponse[IMConnectionPublic])
async def update(cid: str, body: UpdateConnection, user: CurrentUser, service: IMDep):
    return success(
        public(
            await service.set_enabled(
                cid, user.user_id, body.revision, body.enabled
            ),
            service,
        )
    )


@router.get("/connections/{cid}/status", response_model=ApiResponse[IMStatusPublic])
async def status(cid: str, user: CurrentUser, service: IMDep):
    row = await service.store.get(cid, user.user_id)
    state = "webhook_ready" if row.sender_id else "awaiting_pairing"
    if service.credentials_error(cid):
        state = "unavailable"
    elif not row.enabled:
        state = "disabled"
    return success(
        {
            "state": state,
            "revision": row.revision,
            "paired": bool(row.sender_id),
        }
    )


@router.post("/connections/{cid}/pairings", response_model=ApiResponse[IMPairingPublic])
async def pair(cid: str, user: CurrentUser, service: IMDep):
    return success(await service.pairing(cid, user.user_id))


@router.post("/connections/{cid}/test", response_model=ApiResponse[dict[str, bool]])
async def test_connection(cid: str, user: CurrentUser, service: IMDep):
    from app.v2.server.im.contracts import DeliveryError

    row = await service.store.get(cid, user.user_id)
    await service.check_credentials(row)
    try:
        await (await service.channel(row)).probe()
    except (ValueError, DeliveryError):
        raise error("test_failed", "Feishu credential test failed") from None
    return success({"credentials_valid": True})


@router.get("/connections/{cid}/deliveries", response_model=ApiResponse[IMDeliveryPage])
async def deliveries(
    cid: str,
    user: CurrentUser,
    service: IMDep,
    after: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    unresolved: bool = False,
):
    await service.store.get(cid, user.user_id)
    rows = await service.store.deliveries(
        cid, after=after, limit=limit + 1, unresolved=unresolved
    )
    return success(
        {
            "items": [
                {
                    "id": r.id,
                    "state": r.state,
                    "attempts": r.attempts,
                    "revision": r.revision,
                    "error": r.error,
                    "receipt": r.receipt,
                }
                for r in rows[:limit]
            ],
            "next_cursor": rows[limit - 1].id if len(rows) > limit else None,
        }
    )


@router.post(
    "/deliveries/{delivery_id}/retries", response_model=ApiResponse[dict[str, bool]]
)
async def retry(
    delivery_id: int, body: RetryDelivery, user: CurrentUser, service: IMDep
):
    await service.retry_delivery(
        delivery_id,
        user.user_id,
        revision=body.revision,
        allow_duplicate=body.allow_duplicate,
    )
    return success({"queued": True})


@router.post("/webhooks/{cid}")
async def webhook(cid: str, request: Request, service: IMDep):
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 65536:
            raise HTTPException(413, "IM event too large")
    return await service.receive(cid, bytes(body), dict(request.headers))


@router.delete("/deliveries/{delivery_id}", response_model=ApiResponse[dict[str, bool]])
async def discard_delivery(
    delivery_id: int, user: CurrentUser, service: IMDep, revision: int = Query(ge=1)
):
    await service.retry_delivery(
        delivery_id, user.user_id, revision=revision, discard=True
    )
    return success({"discarded": True})


@router.delete("/connections/{cid}", response_model=ApiResponse[dict[str, bool]])
async def delete_connection(
    cid: str, user: CurrentUser, service: IMDep, revision: int = Query(ge=1)
):
    await service.delete(cid, user.user_id, revision)
    return success({"deleted": True})

"""Authenticated Desktop plugin routes. Web views never receive these credentials."""

from __future__ import annotations

import asyncio
import base64
import http.client
import ipaddress
import json
import socket
import time
from pathlib import PurePosixPath
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from .desktop_plugins import (
    ASSET_TYPES,
    MAX_PACKAGE,
    MAX_VALUE,
    PluginPackage,
    PluginConflict,
    plugin_contract_root,
    validate_package,
)


class StorageRequest(BaseModel):
    operation: Literal["get", "set", "delete"]
    key: str = Field(min_length=1, max_length=128)
    value: Any = None


class CapabilityRequest(BaseModel):
    capability: Literal["context", "file.read", "file.export", "draft", "https"]
    endpoint: str | None = Field(default=None, max_length=40)
    bearer: str | None = Field(default=None, max_length=2048)


def _https(endpoint, payload, bearer=None):
    url = urlsplit(endpoint["url"])
    host = url.hostname.encode("idna").decode("ascii")
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(
        not ipaddress.ip_address(item[4][0]).is_global
        or ipaddress.ip_address(item[4][0]).is_multicast
        for item in addresses
    ):
        raise PermissionError("External API must resolve to a public address")
    address = addresses[0][4][0]
    deadline = time.monotonic() + 8
    connection = http.client.HTTPSConnection(host, timeout=8)
    # Connect to the checked address while preserving TLS hostname and SNI.
    connection._create_connection = lambda _target, timeout, source: (
        socket.create_connection((address, 443), timeout, source)
    )
    path = (url.path or "/") + ("?" + url.query if url.query else "")
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Sage-Desktop-Plugin/1",
    }
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    try:
        connection.request(
            endpoint["method"],
            path,
            body=payload,
            headers=headers,
        )
        response = connection.getresponse()
        if time.monotonic() >= deadline:
            raise TimeoutError("External API timed out")
        if 300 <= response.status < 400:
            raise PermissionError("External API redirects are blocked")
        data = bytearray()
        while chunk := response.read1(min(4096, MAX_VALUE + 1 - len(data))):
            data.extend(chunk)
            if len(data) > MAX_VALUE:
                raise ValueError("External API response is too large")
            if time.monotonic() >= deadline:
                raise TimeoutError("External API timed out")
        return {
            "status": response.status,
            "body": data.decode("utf-8", errors="replace"),
        }
    finally:
        connection.close()


def _document(package: PluginPackage):

    assets = {
        path: {
            "type": ASSET_TYPES[PurePosixPath(path).suffix.lower()],
            "data": base64.b64encode(data).decode("ascii"),
        }
        for path, data in package.assets.items()
        if path != "manifest.json"
    }
    root = plugin_contract_root()
    for path, mime in (("sdk.js", "text/javascript"), ("theme.css", "text/css")):
        assets[f"__sage/{path}"] = {
            "type": mime,
            "data": base64.b64encode((root / path).read_bytes()).decode("ascii"),
        }
    return {"manifest": package.manifest, "assets": assets}


def plugin_router(store, owner_of):
    router = APIRouter(prefix="/api/v2/desktop-plugins")

    def success(value=None):
        return {"code": 0, "message": "success", "data": value}

    async def checked(action, *args, **kwargs):
        try:
            return await asyncio.to_thread(action, *args, **kwargs)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except PluginConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except (ValueError, OSError, http.client.HTTPException) as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("")
    async def snapshot(request: Request, client: str = ""):
        return success(await checked(store.snapshot, owner_of(request), client))

    @router.get("/events")
    async def events(request: Request, client: str):
        async def stream():
            async for value in store.snapshots(owner_of(request), client):
                yield json.dumps(value, ensure_ascii=False) + "\n"

        return StreamingResponse(
            stream(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @router.post("/opens/{client}/{open_id}")
    async def acknowledge(client: str, open_id: str, request: Request):
        await store.acknowledge(owner_of(request), client, open_id)
        return success()

    async def read_package(request: Request):
        content = bytearray()
        async for chunk in request.stream():
            if len(content) + len(chunk) > MAX_PACKAGE:
                raise HTTPException(413, "Plugin package exceeds 8 MiB")
            content.extend(chunk)
        return await checked(validate_package, bytes(content))

    @router.post("/preview")
    async def preview(request: Request):
        return success(await checked(_document, await read_package(request)))

    @router.post("/upload")
    async def upload(request: Request, client: str):
        package = await read_package(request)
        try:
            return success(await store.register(owner_of(request), client, package))
        except PluginConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/{plugin_id}/manage/{action}")
    async def manage(
        plugin_id: str,
        action: Literal[
            "enable", "disable", "pin", "unpin", "up", "down", "uninstall", "revoke"
        ],
        request: Request,
    ):
        try:
            await store.manage(owner_of(request), plugin_id, action)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        return success()

    @router.get("/{plugin_id}/{digest}/document")
    async def document(plugin_id: str, digest: str, request: Request):
        archive = await checked(store.package, owner_of(request), plugin_id, digest)
        return success(await checked(lambda: _document(validate_package(archive))))

    @router.get("/{plugin_id}/{digest}/logo")
    async def logo(plugin_id: str, digest: str, request: Request):
        owner = owner_of(request)

        def read():
            manifest, archive = store.installed_package(
                owner, plugin_id, digest=digest
            )
            if not manifest.get("logo"):
                raise FileNotFoundError("Plugin logo is not available")
            return validate_package(archive).assets[manifest["logo"]]

        return Response(await checked(read), media_type="image/png")

    @router.post("/{plugin_id}/{digest}/storage")
    async def storage(
        plugin_id: str, digest: str, body: StorageRequest, request: Request
    ):
        return success(
            await checked(
                store.storage,
                owner_of(request),
                plugin_id,
                digest,
                body.operation,
                body.key,
                body.value,
            )
        )

    @router.post("/{plugin_id}/{digest}/permission")
    async def permission(
        plugin_id: str,
        digest: str,
        body: CapabilityRequest,
        request: Request,
        grant: bool = False,
    ):
        allowed, endpoint = await checked(
            store.permission,
            owner_of(request),
            plugin_id,
            digest,
            body.capability,
            body.endpoint,
            grant=grant,
        )
        owner = owner_of(request)
        needs_token = endpoint and endpoint.get("auth") == "bearer"
        if grant and needs_token and body.bearer is not None:
            await checked(
                store.set_endpoint_token, owner, plugin_id, endpoint, body.bearer
            )
        return success(
            {
                "allowed": allowed,
                "endpoint": endpoint,
                "needsBearer": bool(
                    needs_token and not store.endpoint_token(owner, plugin_id, endpoint)
                ),
            }
        )

    @router.post("/{plugin_id}/{digest}/https/{endpoint}")
    async def https(plugin_id: str, digest: str, endpoint: str, request: Request):
        payload = bytearray()
        async for chunk in request.stream():
            if len(payload) + len(chunk) > MAX_VALUE:
                raise HTTPException(413, "External API payload is too large")
            payload.extend(chunk)
        allowed, endpoint_config = await checked(
            store.permission, owner_of(request), plugin_id, digest, "https", endpoint
        )
        if not allowed:
            raise HTTPException(403, "External API permission is required")
        bearer = store.endpoint_token(owner_of(request), plugin_id, endpoint_config)
        if endpoint_config.get("auth") == "bearer" and bearer is None:
            raise HTTPException(403, "Endpoint bearer token is required")
        return success(
            await checked(
                _https,
                endpoint_config,
                bytes(payload) if endpoint_config["method"] != "GET" else None,
                bearer,
            )
        )

    return router

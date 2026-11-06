"""Bounded A2A 1.0 JSON-RPC transport, independent of either host runtime."""

from __future__ import annotations

import json
from typing import Literal
from uuid import uuid4

import httpx
from pydantic import BaseModel, Field, ValidationError

from .config import BridgeConfig

TaskState = Literal[
    "TASK_STATE_SUBMITTED",
    "TASK_STATE_WORKING",
    "TASK_STATE_INPUT_REQUIRED",
    "TASK_STATE_COMPLETED",
    "TASK_STATE_FAILED",
    "TASK_STATE_CANCELED",
    "TASK_STATE_REJECTED",
    "TASK_STATE_AUTH_REQUIRED",
]
ACTIVE_STATES = {"TASK_STATE_SUBMITTED", "TASK_STATE_WORKING"}
_MAX_RESPONSE_BYTES = 2_097_152


class BridgeError(Exception):
    """Safe user-facing description and a non-sensitive diagnostic code."""

    def __init__(
        self, message: str, code: str = "bridge_error", *, rejected: bool = False
    ) -> None:
        super().__init__(message)
        self.code = code
        self.rejected = rejected


class TaskStatus(BaseModel):
    state: TaskState


class MessagePart(BaseModel):
    text: str = ""


class TaskMessage(BaseModel):
    role: str
    parts: list[MessagePart] = Field(default_factory=list)


class Task(BaseModel):
    id: str = Field(min_length=1)
    context_id: str = Field(alias="contextId", min_length=1)
    status: TaskStatus
    history: list[TaskMessage] = Field(default_factory=list)

    @property
    def text(self) -> str:
        for message in reversed(self.history):
            if message.role == "ROLE_AGENT":
                text = "\n".join(part.text for part in message.parts if part.text)
                if text:
                    return text
        return ""


class SageClient:
    def __init__(self, http: httpx.AsyncClient, config: BridgeConfig) -> None:
        self.http = http
        self.config = config

    async def send(self, api_key: str, message: dict) -> Task:
        result = await self._rpc(
            api_key,
            "SendMessage",
            {
                "message": message,
                "configuration": {"returnImmediately": True, "historyLength": 20},
            },
        )
        return self._task(result.get("task"), context_id=message["contextId"])

    async def get(self, api_key: str, task_id: str, context_id: str) -> Task:
        result = await self._rpc(
            api_key, "GetTask", {"id": task_id, "historyLength": 20}
        )
        return self._task(result, context_id=context_id, task_id=task_id)

    async def cancel(self, api_key: str, task_id: str, context_id: str) -> Task:
        result = await self._rpc(api_key, "CancelTask", {"id": task_id})
        return self._task(result, context_id=context_id, task_id=task_id)

    @staticmethod
    def _task(value, *, context_id: str, task_id: str | None = None) -> Task:
        try:
            task = Task.model_validate(value)
        except ValidationError:
            raise BridgeError("Sage 返回了无法识别的任务。", "invalid_task") from None
        if task.context_id != context_id or (
            task_id is not None and task.id != task_id
        ):
            raise BridgeError("Sage 返回的任务与当前会话不匹配。", "task_mismatch")
        return task

    async def _rpc(self, api_key: str, method: str, params: dict) -> dict:
        request_id = uuid4().hex
        try:
            async with self.http.stream(
                "POST",
                f"{self.config.server_url}/a2a/v1",
                headers={"Authorization": f"Bearer {api_key}", "A2A-Version": "1.0"},
                json={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params,
                },
                timeout=self.config.request_timeout_seconds,
                follow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    raise BridgeError(
                        "Sage 请求失败，请检查连接和 API Key 权限。",
                        f"http_{response.status_code}",
                        rejected=response.status_code
                        in {400, 401, 403, 404, 405, 413, 415, 422, 429},
                    )
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > _MAX_RESPONSE_BYTES:
                        raise BridgeError(
                            "Sage 回复过大，请到 Sage Web 查看。", "response_too_large"
                        )
                    content.extend(chunk)
            body = json.loads(content)
        except httpx.HTTPError:
            raise BridgeError(
                "无法确认 Sage 请求结果，请使用 /sage status 核对任务。",
                "transport_error",
            ) from None
        except (ValueError, UnicodeError):
            raise BridgeError("Sage 返回了无效响应。", "invalid_json") from None
        if (
            not isinstance(body, dict)
            or body.get("jsonrpc") != "2.0"
            or body.get("id") != request_id
        ):
            raise BridgeError(
                "Sage 未能完成请求，请到 Sage Web 查看任务。", "rpc_error"
            )
        if "error" in body:
            error = body["error"]
            code = error.get("code") if isinstance(error, dict) else None
            raise BridgeError(
                "Sage 未能完成请求，请到 Sage Web 查看任务。",
                "rpc_error",
                rejected=isinstance(code, int)
                and code in {-32600, -32601, -32602, -32001, -32004, -32006},
            )
        if not isinstance(body.get("result"), dict):
            raise BridgeError("Sage 返回了无效响应。", "invalid_result")
        return body["result"]

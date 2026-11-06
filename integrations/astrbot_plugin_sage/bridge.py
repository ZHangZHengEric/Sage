"""Tenant-bound conversations persisted through AstrBot's plugin KV store."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4
from weakref import WeakValueDictionary

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .client import ACTIVE_STATES, BridgeError, SageClient, Task
from .config import Binding, BridgeConfig


class Store(Protocol):
    async def get_kv_data(self, key: str, default=None): ...
    async def put_kv_data(self, key: str, value) -> None: ...


@dataclass(frozen=True, slots=True)
class MessageSource:
    platform_id: str
    origin: str
    sender_id: str
    message_id: str


@dataclass(frozen=True, slots=True)
class BridgeReply:
    text: str


class SessionState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context_id: str = Field(default_factory=lambda: "astrbot_" + uuid4().hex)
    task_id: str = ""
    message_id: str = ""
    pending: dict | None = None
    pending_uncertain: bool = False


class MessageReceipt(BaseModel):
    context_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)


class SageBridge:
    def __init__(self, config: BridgeConfig, client: SageClient, store: Store) -> None:
        self.config = config
        self.client = client
        self.store = store
        self._bindings = {binding.platform_id: binding for binding in config.bindings}
        self._locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()

    def binding(self, source: MessageSource) -> Binding | None:
        return self._bindings.get(source.platform_id) if self.config.enabled else None

    def authorize(self, source: MessageSource) -> Binding:
        binding = self.binding(source)
        if (
            binding is None
            or source.sender_id not in binding.allowed_sender_ids
            or (
                binding.allowed_origins and source.origin not in binding.allowed_origins
            )
        ):
            raise BridgeError(
                "当前发送人或会话未授权使用此 Sage 连接。", "unauthorized"
            )
        if not all(
            (source.platform_id, source.origin, source.sender_id, source.message_id)
        ):
            raise BridgeError("消息缺少来源标识，未提交到 Sage。", "invalid_source")
        return binding

    async def handle(
        self,
        source: MessageSource,
        parts: list[dict] | None = None,
        *,
        command: str = "",
    ) -> BridgeReply:
        binding = self.authorize(source)
        api_key = os.environ.get(binding.api_key_env, "").strip()
        if not api_key or "\n" in api_key or "\r" in api_key:
            raise BridgeError(
                "Sage 连接凭据未配置，请联系管理员。", "missing_credential"
            )
        # A key change may change the tenant or Agent, so it starts a new scope.
        scope = json.dumps(
            [
                self.config.server_url,
                source.platform_id,
                source.origin,
                source.sender_id,
                hashlib.sha256(api_key.encode()).hexdigest(),
            ],
            ensure_ascii=False,
        )
        key = "session_" + hashlib.sha256(scope.encode()).hexdigest()
        message_id = "im_" + hashlib.sha256(source.message_id.encode()).hexdigest()
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            if command not in {"", "status", "cancel", "new"}:
                raise BridgeError(
                    "支持 /sage status、/sage cancel 和 /sage new。", "invalid_command"
                )
            if not command:
                receipt = await self.store.get_kv_data(f"{key}_{message_id}", None)
                if receipt is not None:
                    try:
                        receipt = MessageReceipt.model_validate(receipt)
                    except ValidationError:
                        raise BridgeError(
                            "消息回执无法读取，请联系管理员。", "invalid_receipt"
                        ) from None
                    return self._reply(
                        await self.client.get(
                            api_key, receipt.task_id, receipt.context_id
                        )
                    )
            try:
                state = SessionState.model_validate(
                    await self.store.get_kv_data(key, {})
                )
            except ValidationError:
                raise BridgeError(
                    "会话记录无法读取，请联系管理员。", "invalid_session"
                ) from None
            task = await self._current(api_key, key, state)
            if command == "status":
                return self._reply(task)
            if command == "cancel":
                if task is None:
                    return BridgeReply("当前没有任务。")
                if task.status.state in {
                    "TASK_STATE_COMPLETED",
                    "TASK_STATE_FAILED",
                    "TASK_STATE_CANCELED",
                    "TASK_STATE_REJECTED",
                }:
                    return self._reply(task)
                try:
                    task = await self.client.cancel(api_key, task.id, state.context_id)
                except BridgeError:
                    # Completion can race with cancellation. Only a confirmed
                    # terminal snapshot resolves that conflict successfully.
                    latest = await self.client.get(api_key, task.id, state.context_id)
                    if latest.status.state in {
                        *ACTIVE_STATES,
                        "TASK_STATE_INPUT_REQUIRED",
                        "TASK_STATE_AUTH_REQUIRED",
                    }:
                        raise
                    task = latest
                return self._reply(task)
            if task is not None and task.status.state in {
                *ACTIVE_STATES,
                "TASK_STATE_INPUT_REQUIRED",
                "TASK_STATE_AUTH_REQUIRED",
            }:
                return self._reply(task)
            if command == "new":
                await self.store.put_kv_data(key, SessionState().model_dump())
                return BridgeReply("已创建新的 Sage 会话。")
            if state.message_id == message_id and task is not None:
                return self._reply(task)
            if not parts:
                raise BridgeError("请输入文本或发送图片。", "empty_message")
            state.message_id = message_id
            state.pending = {
                "messageId": message_id,
                "contextId": state.context_id,
                "role": "ROLE_USER",
                "parts": parts,
            }
            state.task_id = ""
            state.pending_uncertain = False
            # Persist before dispatch. A lost response is recovered by explicitly
            # resubmitting this exact messageId, using Sage's idempotency contract.
            await self.store.put_kv_data(key, state.model_dump())
            task = await self._submit(api_key, key, state)
        if self.config.wait_seconds and task.status.state in ACTIVE_STATES:
            try:
                async with asyncio.timeout(self.config.wait_seconds):
                    while task.status.state in ACTIVE_STATES:
                        await asyncio.sleep(self.config.poll_interval_seconds)
                        task = await self.client.get(api_key, task.id, state.context_id)
            except TimeoutError:
                pass
        # A completed older request must not publish into a conversation that
        # the user has already reset while its final poll was in flight.
        current = await self.store.get_kv_data(key, {})
        if current.get("context_id") != state.context_id:
            return BridgeReply("")
        return self._reply(task)

    async def _current(
        self, api_key: str, key: str, state: SessionState
    ) -> Task | None:
        if state.pending is not None:
            return await self._submit(api_key, key, state)
        if state.task_id:
            return await self.client.get(api_key, state.task_id, state.context_id)
        return None

    async def _submit(self, api_key: str, key: str, state: SessionState) -> Task:
        assert state.pending is not None
        was_uncertain = state.pending_uncertain
        # Persist before I/O: process termination can hide an accepted request
        # just as a transport timeout can. A later rejected retry cannot prove
        # that this earlier attempt was never accepted.
        state.pending_uncertain = True
        await self.store.put_kv_data(key, state.model_dump())
        try:
            task = await self.client.send(api_key, state.pending)
        except BridgeError as exc:
            if exc.rejected and not was_uncertain:
                state.pending = None
                state.message_id = ""
                state.pending_uncertain = False
                await self.store.put_kv_data(key, state.model_dump())
            raise
        # Keep the receipt across subsequent turns and /sage new. Otherwise a
        # delayed platform redelivery could repeat an action in a new context.
        await self.store.put_kv_data(
            f"{key}_{state.message_id}",
            MessageReceipt(
                context_id=task.context_id,
                task_id=task.id,
            ).model_dump(),
        )
        state.task_id = task.id
        state.pending = None
        state.pending_uncertain = False
        await self.store.put_kv_data(key, state.model_dump())
        return task

    @staticmethod
    def _reply(task: Task | None) -> BridgeReply:
        if task is None:
            return BridgeReply("当前没有任务。")
        state = task.status.state
        if state == "TASK_STATE_COMPLETED":
            return BridgeReply(task.text or "任务已完成，请到 Sage Web 查看结果。")
        if state in ACTIVE_STATES:
            return BridgeReply(
                "任务仍在执行，可用 /sage status 查询，或 /sage cancel 取消。"
            )
        if state in {"TASK_STATE_INPUT_REQUIRED", "TASK_STATE_AUTH_REQUIRED"}:
            return BridgeReply(
                "任务需要输入或审批，请到 Sage Web 打开当前会话处理，再用 /sage status 查询。"
            )
        if state == "TASK_STATE_CANCELED":
            return BridgeReply("任务已取消。")
        return BridgeReply("任务未完成，请到 Sage Web 查看详情。")

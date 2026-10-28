"""IM ingress and durable projection using the existing V2 Run pipeline."""

import asyncio
import time
from urllib.parse import quote, urlsplit
from uuid import uuid4

from app.v2.server.conversations.bindings import SessionBinding
from app.v2.server.runtime.policy import (
    EXECUTION_METADATA_KEY,
    ExecutionPolicy,
    intersect_policies,
)
from sagents.v2.contracts.commands import InputItem, RunConfig, StartRun
from sagents.v2.contracts.errors import ErrorCategory, SageV2Error
from sagents.v2.contracts.items import MessageItemData, TextBlock, Visibility
from sagents.v2.contracts.run_state import RunState, TERMINAL_RUN_STATES
from sagents.v2.runtime.extensions import (
    CapabilityRequirement,
    ExtensionHost,
    ExtensionRegistry,
    ExtensionScope,
    ExtensionScopeContext,
)
from sagents.v2.runtime.observability.logs import get_logger
from .contracts import GRANT_KEY, DeliveryError
from .credentials import IMCredentials
from .feishu import FeishuConfig, registration
from .orm import BindingRow, DeliveryRow, InboxRow
from .repository import IMStore, error

LOGGER = get_logger(__name__)


class IMService:
    def __init__(self, host):
        self.host = host
        self.store = IMStore(host.database)
        self.credentials = None
        self._credential_errors = {}
        self.worker = uuid4().hex
        self.scope = None
        self._channels = {}
        self._task = None
        self._paused = False
        self._tick_lock = asyncio.Lock()
        self._last_cleanup = 0

    async def start(self):
        connections = await self.store.list_connections()
        try:
            self.credentials = IMCredentials.load(
                self.host.paths.data_root, allow_create=not connections
            )
        except RuntimeError:
            LOGGER.warning("server.im.key.unavailable", "IM credential key is unavailable")
        for connection in connections:
            try:
                if self.credentials is None:
                    raise ValueError("key unavailable")
                self.credentials.open(connection.owner_id, connection.config)
            except ValueError:
                await self._disable_unavailable(connection)
        registry = ExtensionRegistry()
        registry.register(registration())
        for item in self.host._registrations:
            if any(
                offer.capability == "im.channel-factory"
                for offer in item.descriptor.provides
            ):
                registry.register(item)
        extensions = ExtensionHost(registry)
        plan = extensions.plan(
            (
                CapabilityRequirement(
                    capability="im.channel-factory", name="feishu", api_version=">=1,<2"
                ),
            )
        )
        self.scope = await extensions.open_scope(
            ExtensionScopeContext(scope=ExtensionScope.PROCESS, scope_id="server-im"),
            plan,
        )
        self._task = asyncio.create_task(self._run(), name="server-im-recovery")

    def pause(self):
        self._paused = True

    async def close(self):
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        for channel in self._channels.values():
            await channel.close()
        self._channels.clear()
        # Release only this worker's leases. A crash relies on expiry instead.
        try:
            for conn in await self.store.list_connections():
                async with self.store.locked(conn.id) as (_, current):
                    if current.lease_token == self.worker:
                        current.lease_until = 0
                        current.lease_token = ""
        except Exception:
            LOGGER.warning(
                "server.im.lease.release_failed", "IM leases will expire after shutdown"
            )
        finally:
            if self.scope is not None:
                await self.scope.close()
                self.scope = None

    async def channel(self, conn):
        if self.credentials is None or self.credentials_error(conn.id):
            raise error("credentials_unavailable", self.credentials_error(conn.id) or "IM 凭据加密密钥不可用，请恢复服务端密钥备份")
        if conn.id not in self._channels:
            factory = self.scope.providers.require("im.channel-factory", "feishu")
            try:
                parsed = self.credentials.open(conn.owner_id, conn.config)
            except ValueError:
                await self._disable_unavailable(conn)
                raise error("credentials_unavailable", self.credentials_error(conn.id)) from None
            self._channels[conn.id] = factory.create(parsed.model_dump())
        return self._channels[conn.id]

    def credentials_error(self, cid):
        return self._credential_errors.get(cid, "")

    async def _disable_unavailable(self, conn):
        self._credential_errors[conn.id] = "连接凭据无法解密，请恢复服务端密钥备份后测试凭据并重新启用"
        async with self.store.locked(conn.id) as (_, current):
            if current.enabled:
                current.enabled = False
                current.revision += 1
                current.auth_epoch += 1

    async def check_credentials(self, conn):
        try:
            vault = IMCredentials.load(self.host.paths.data_root, allow_create=False)
            vault.open(conn.owner_id, conn.config)
        except (RuntimeError, ValueError):
            await self._disable_unavailable(conn)
            raise error("credentials_unavailable", self.credentials_error(conn.id)) from None
        self.credentials = vault
        self._credential_errors.pop(conn.id, None)

    async def set_enabled(self, cid, owner, revision, enabled):
        conn = await self.store.get(cid, owner)
        if enabled:
            await self.check_credentials(conn)
        return await self.store.set_enabled(cid, owner, revision, enabled)

    async def create(self, owner_id, agent_id, name, config):
        if (
            await self.host.users.get_by_id(owner_id) is None
            or await self.host.catalog.agent_owner(agent_id) != owner_id
        ):
            raise error("agent_not_found", "Owned Agent not found")
        # P0 is a personal connection. Require a real public base for safe login
        # links; never derive it from an inbound Host/X-Forwarded-Host header.
        base = urlsplit(self.host.settings.public_base_url)
        if (
            base.scheme != "https"
            or not base.hostname
            or base.username
            or base.password
            or base.query
            or base.fragment
        ):
            raise error(
                "public_url_required",
                "Configure SAGE_SERVER_PUBLIC_URL as a public HTTPS URL",
            )
        parsed = FeishuConfig.model_validate(config)
        if len(await self.store.list_connections()) >= 200:
            raise error("capacity", "IM connection capacity reached")
        if self.credentials is None:
            raise error("credentials_unavailable", "IM 凭据加密密钥不可用，请恢复服务端密钥备份")
        stored = self.credentials.seal(owner_id, parsed)
        # Verify control before reserving the globally unique external account.
        factory = self.scope.providers.require("im.channel-factory", "feishu")
        channel = factory.create(parsed.model_dump())
        try:
            await channel.probe()
        except DeliveryError as exc:
            raise error(
                "credentials_invalid",
                "飞书凭据验证暂时不可用，请稍后重试"
                if exc.outcome == "retry"
                else "飞书应用凭据验证失败，请检查 App ID 与 App Secret 后重试",
                ErrorCategory.PROVIDER_TRANSIENT
                if exc.outcome == "retry"
                else ErrorCategory.VALIDATION,
            ) from None
        finally:
            await channel.close()
        return await self.store.create(owner_id, agent_id, name, stored)

    async def delete(self, cid, owner, revision):
        from sqlalchemy import delete

        async with self.store.locked(cid, owner=owner) as (db, conn):
            if conn.revision != revision:
                raise error(
                    "revision_conflict",
                    "Connection changed; refresh before deleting",
                    ErrorCategory.CONFLICT,
                )
            for table in (DeliveryRow, InboxRow, BindingRow):
                await db.execute(delete(table).where(table.connection_id == cid))
            await db.delete(conn)
        channel = self._channels.pop(cid, None)
        self._credential_errors.pop(cid, None)
        if channel is not None:
            await channel.close()

    async def pairing(self, cid, user):
        return await self.store.pairing(cid, user)

    async def receive(self, cid, body, headers):
        conn = await self.store.get(cid)
        try:
            event = (await self.channel(conn)).decode(body, headers)
        except ValueError:
            raise error(
                "invalid_event", "Invalid Feishu event", ErrorCategory.AUTHENTICATION
            ) from None
        if isinstance(event, dict):
            return event
        if event is not None and conn.enabled:
            await self.store.accept(cid, event)
        return {"code": 0}

    def context(self, conn):
        context = self.host.contexts.for_user(conn.owner_id)
        return context.model_copy(
            update={
                "actor": context.actor.model_copy(
                    update={"delegated_by": "im:" + conn.id}
                )
            }
        )

    async def authorize_run(self, command):
        if GRANT_KEY not in command.config.metadata:
            return True
        grant = command.config.metadata[GRANT_KEY]
        if not isinstance(grant, dict):
            return False
        try:
            conn = await self.store.get(grant["connection_id"])
            return (
                conn.enabled
                and conn.owner_id == grant["owner_id"]
                and conn.agent_id == grant["agent_id"]
                and conn.sender_id == grant["sender_id"]
                and conn.auth_epoch == grant["auth_epoch"]
                and await self.host.users.get_by_id(conn.owner_id) is not None
                and await self.host.catalog.agent_owner(conn.agent_id) == conn.owner_id
            )
        except (KeyError, SageV2Error):
            return False

    async def tick(self):
        async with self._tick_lock:
            cleanup = time.time() - self._last_cleanup > 3600
            slots = asyncio.Semaphore(8)

            async def process(conn):
                async with slots:
                    await self._process_connection(conn, cleanup)

            await asyncio.gather(
                *(process(conn) for conn in await self.store.list_connections())
            )
            if cleanup:
                self._last_cleanup = time.time()

    async def _process_connection(self, conn, cleanup):
        try:
            if not await self.store.claim(conn.id, self.worker):
                return
            rows = await self.store.inboxes(conn.id, active=True)
            # Existing Session serial admission remains authoritative;
            # do not repeatedly submit a second pending turn behind it.
            busy = {r.session_id for r in rows if r.state == "watching"}
            for row in rows:
                if (
                    row.state == "pending"
                    and row.session_id in busy
                    and not row.cancel_requested
                ):
                    continue
                try:
                    if row.state == "pending":
                        await self._start(conn, row)
                        busy.add(row.session_id)
                    else:
                        await self._watch(conn, row)
                except SageV2Error as exc:
                    await self._input_error(
                        row,
                        exc.info.code,
                        retry=exc.info.retryable
                        or exc.info.category
                        in (
                            ErrorCategory.CONFLICT,
                            ErrorCategory.RATE_LIMITED,
                            ErrorCategory.PROVIDER_TRANSIENT,
                        ),
                    )
                except Exception:
                    # Never log payloads, frozen model config or credentials.
                    LOGGER.warning(
                        "server.im.input.failed",
                        "IM input processing failed",
                        attributes={
                            "connection_id": conn.id,
                            "inbox_id": row.id,
                        },
                    )
                    await self._input_error(row, "processing_unavailable", retry=True)
            await self._send(conn)
            if cleanup:
                await self.store.cleanup(conn.id, self.worker)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.warning(
                "server.im.connection.failed",
                "IM connection processing failed",
                attributes={"connection_id": conn.id},
            )

    async def _input_error(self, row, code, *, retry):
        attempts = row.attempts + 1
        if retry and attempts < 20:
            await self.store.change_inbox(
                row,
                self.worker,
                attempts=attempts,
                next_attempt=time.time() + min(60, 2 ** min(attempts, 5)),
                error=code[:128],
            )
        else:
            await self.store.project(
                row,
                self.worker,
                "failure",
                "任务未能继续，请在 Sage 中查看或重新发送。",
                final=True,
            )
            await self.store.change_inbox(
                row,
                self.worker,
                state="failed",
                error=code[:128],
                text="",
                command=None,
            )

    async def _start(self, conn, row):
        binding = await self.store.binding(row.binding_id)
        if (
            binding is None
            or binding.generation != row.generation
            or row.auth_epoch != conn.auth_epoch
        ):
            await self.store.change_inbox(
                row, self.worker, state="superseded", text="", command=None
            )
            return
        context = self.context(conn)
        conversations = self.host.conversations
        access = conversations.session_access
        # Claim before reading any Run with the generated Session ID.
        await self.host.threads.bind(
            SessionBinding(row.session_id, conn.owner_id, conn.owner_id, conn.agent_id)
        )
        await self.host.threads.upsert(
            row.session_id, conn.owner_id, title=row.text[:80], agent_id=conn.agent_id
        )
        previous = await access.find_start_run(
            row.session_id, "im_" + row.message_key, context
        )
        if previous is not None:
            run, command = previous
            run_id = run.run_id
        else:
            if row.cancel_requested:
                await self.store.project(
                    row, self.worker, "cancelled", "任务已取消。", final=True
                )
                return
            if row.command is None:
                admitted = await conversations.admission.prepare(
                    user_id=conn.owner_id,
                    session_id=row.session_id,
                    agent_id=conn.agent_id,
                    pin_existing=True,
                )
                if not admitted.model_ready:
                    raise error(
                        "model_not_configured", "Configure a model for this Agent"
                    )
                metadata = {
                    **admitted.metadata,
                    "server_v2.workspace_user_id": conn.owner_id,
                    GRANT_KEY: {
                        "connection_id": conn.id,
                        "owner_id": conn.owner_id,
                        "agent_id": conn.agent_id,
                        "sender_id": row.sender_id,
                        "auth_epoch": row.auth_epoch,
                    },
                }
                grant = metadata[EXECUTION_METADATA_KEY]
                policy = intersect_policies(
                    ExecutionPolicy.model_validate(grant["policy"]),
                    ExecutionPolicy(shell="ask"),
                )
                metadata[EXECUTION_METADATA_KEY] = {
                    **grant,
                    "policy": policy.model_dump(),
                    "policy_hash": policy.fingerprint,
                }
                command = StartRun(
                    session_id=row.session_id,
                    agent_id=admitted.agent_id,
                    input=(
                        InputItem(role="user", content=(TextBlock(text=row.text),)),
                    ),
                    config=RunConfig(
                        enabled_tools=tuple(admitted.agent.tools)
                        + tuple(admitted.agent.external_tools),
                        enabled_skills=tuple(s.name for s in admitted.skills),
                        max_steps=admitted.max_steps,
                        metadata=metadata,
                    ),
                    resolved_spec_hash=self.host.application.composition_hash,
                    idempotency_key="im_" + row.message_key,
                )
                await self.store.change_inbox(
                    row, self.worker, command=command.model_dump(mode="json")
                )
            else:
                command = StartRun.model_validate(row.command)
            if not await self.authorize_run(command):
                raise error("grant_revoked", "IM authorization was revoked")
            run_id = await conversations.runs.start_detached_run(
                "native",
                command,
                context,
                user_id=conn.owner_id,
                session_id=row.session_id,
                label="im",
            )
        if not await self.authorize_run(command):
            raise error("grant_revoked", "IM authorization was revoked")
        await self.store.change_inbox(
            row, self.worker, state="watching", run_id=run_id, error=""
        )

    def link(self, session_id):
        return (
            self.host.settings.public_base_url.rstrip("/")
            + "/?thread="
            + quote(session_id, safe="")
        )

    async def _watch(self, conn, row):
        binding = await self.store.binding(row.binding_id)
        if binding is None or binding.generation != row.generation:
            await self.store.change_inbox(
                row, self.worker, state="superseded", text="", command=None
            )
            return
        access, runs = (
            self.host.conversations.session_access,
            self.host.conversations.runs,
        )
        context = self.context(conn)
        command = await access.get_start_command(row.run_id, context)
        if not await self.authorize_run(command):
            await self.store.change_inbox(
                row, self.worker, state="superseded", text="", command=None
            )
            return
        run = await access.get_run(row.run_id, context)
        if row.cancel_requested and run.state not in TERMINAL_RUN_STATES:
            await runs.cancel_run(
                run.run_id,
                context,
                expected_revision=run.revision,
                reason="im_user_requested",
            )
            run = await access.get_run(row.run_id, context)
        if run.state == RunState.RESUMING and not self.host.execution.driving(
            run.run_id
        ):
            await runs.continue_detached_run(
                run.run_id,
                context,
                user_id=conn.owner_id,
                session_id=row.session_id,
                label="im",
            )
        if run.state == RunState.SUSPENDED:
            suspension = await access.get_suspension(run.suspension_id, context)
            await self.store.project(
                row,
                self.worker,
                "interaction:" + suspension.suspension_id,
                "任务需要你的确认或补充，请登录 Sage 继续：\n"
                + self.link(row.session_id),
            )
        elif run.state in TERMINAL_RUN_STATES:
            result = await access.get_run_result(row.run_id, context)
            text = ""
            if run.state == RunState.COMPLETED:
                for item in reversed(result.final_items):
                    if (
                        item.visibility == Visibility.PUBLIC
                        and isinstance(item.data, MessageItemData)
                        and item.data.role == "assistant"
                    ):
                        text = "".join(
                            block.text
                            for block in item.data.content
                            if isinstance(block, TextBlock)
                        )
                        if text.strip():
                            break
                if len(text) > 20000:
                    text = text[:20000] + "\n完整结果：" + self.link(row.session_id)
                text = text or "任务已完成：" + self.link(row.session_id)
            else:
                text = (
                    "任务已取消。"
                    if run.state == RunState.CANCELLED
                    else "任务执行失败，请在 Sage 中查看：" + self.link(row.session_id)
                )
            await self.store.project(row, self.worker, "final", text, final=True)

    async def _send(self, conn):
        row = await self.store.next_delivery(conn.id, self.worker)
        if row is None:
            return
        try:
            # Recheck the live principal and Agent before disclosing any output.
            current = await self.store.get(conn.id)
            if not current.enabled or current.auth_epoch != row.auth_epoch:
                await self.store.finish_delivery(row, self.worker, "superseded")
                return
            if (
                await self.host.users.get_by_id(conn.owner_id) is None
                or await self.host.catalog.agent_owner(conn.agent_id) != conn.owner_id
            ):
                await self.store.finish_delivery(row, self.worker, "superseded")
                return
            receipt = await (await self.channel(conn)).send(
                row.chat_id, row.text, row.source_key[:32]
            )
        except DeliveryError as exc:
            state = (
                "pending"
                if exc.outcome == "retry" and row.attempts < 5
                else ("failed" if exc.outcome == "retry" else exc.outcome)
            )
            await self.store.finish_delivery(
                row,
                self.worker,
                state,
                code=exc.code,
                delay=max(exc.retry_after, min(60, 2**row.attempts)),
            )
        except BaseException as exc:
            await self.store.finish_delivery(
                row, self.worker, "unknown", code="send_interrupted"
            )
            if isinstance(exc, asyncio.CancelledError):
                raise
        else:
            await self.store.finish_delivery(
                row, self.worker, "platform_accepted", receipt=receipt
            )

    async def retry_delivery(
        self, delivery_id, owner, *, revision, allow_duplicate=False, discard=False
    ):
        async with self.host.database.session() as db:
            row = await db.get(DeliveryRow, delivery_id)
            if row is None:
                raise error("not_found", "Delivery not found")
            cid = row.connection_id
        async with self.store.locked(cid, owner=owner) as (db, _):
            row = await db.get(DeliveryRow, delivery_id)
            if row.revision != revision:
                raise error(
                    "revision_conflict",
                    "Delivery changed; refresh before deciding",
                    ErrorCategory.CONFLICT,
                )
            if discard and row.state in ("failed", "unknown"):
                row.state, row.text = "superseded", ""
                row.revision += 1
                return
            if row.state not in ("failed", "unknown") or (
                row.state == "unknown" and not allow_duplicate
            ):
                raise error(
                    "retry_conflict",
                    "Unknown delivery requires explicit duplicate-risk acceptance",
                    ErrorCategory.CONFLICT,
                )
            row.state, row.next_attempt, row.attempts, row.error = "pending", 0, 0, ""
            row.revision += 1

    async def _run(self):
        while True:
            try:
                if not self._paused:
                    await self.tick()
            except Exception:
                LOGGER.warning(
                    "server.im.recovery.unavailable", "IM recovery will retry"
                )
            await asyncio.sleep(0.5)

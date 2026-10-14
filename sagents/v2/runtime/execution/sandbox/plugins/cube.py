"""CubeSandbox VM provider with a persistent Volume per workspace identity.

CubeAPI and Cubelet may run on hosts other than Sage.  Only compute is removed
at the end of a Run; the Volume is deliberately never destroyed here.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import re
import shlex
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime

from sagents.v2.contracts.common import new_id, utc_now
from sagents.v2.runtime.execution.sandbox.admission import validate_resource_support
from sagents.v2.runtime.execution.sandbox.contracts import (
    MUTATING_FILE_OPERATIONS, FileOperation, FileStat, FileSystemMode,
    IsolationLevel, NetworkMode, ProcessCapabilities, ProcessResult,
    ResourceLimitCapabilities, SandboxCapabilities, SandboxRef,
    SandboxDurability, SandboxReleaseDisposition, SandboxReleaseReceipt, SandboxSnapshot,
    SandboxState, TerminateMode,
)
from .cube_files import cube_file_call, relative_parts


def cube_volume_name(user_id: str, agent_id: str, *, private_run_id: str | None = None) -> str:
    """Stable, bounded Cube ID; no identity or mapping table is stored by Sage."""
    if not user_id or not agent_id:
        raise ValueError("workspace user and agent are required")
    digest = hashlib.sha256(json.dumps([user_id, agent_id], ensure_ascii=False).encode()).hexdigest()
    name = f"sage-{digest}"
    if private_run_id is not None:
        if not private_run_id:
            raise ValueError("private run ID is empty")
        name += "-" + hashlib.sha256(private_run_id.encode()).hexdigest()[:24]
    return name


class CubeVolumeClient:
    """Thin SDK boundary for Volume-backed sandbox provisioning."""

    def __init__(self, *, api_url: str, template_id: str, proxy_node_ip: str,
                 api_key: str | None = None, volume_driver: str | None = None):
        if not api_url or not template_id or not proxy_node_ip:
            raise ValueError("Cube API URL, template ID and proxy node IP are required")
        from cubesandbox import Config, Sandbox, Volume
        from cubesandbox._exceptions import VolumeNotFoundError

        self.config = Config(api_url=api_url, api_key=api_key, template_id=template_id,
                             proxy_node_ip=proxy_node_ip)
        self.sandbox_class = Sandbox
        self.volume_class = Volume
        self.volume_not_found = VolumeNotFoundError
        self.template_id = template_id
        self.volume_driver = volume_driver

    def ensure_volume(self, name: str):
        try:
            return self.volume_class.connect(name, config=self.config)
        except self.volume_not_found:
            try:
                created = self.volume_class.create(
                    name, driver=self.volume_driver, config=self.config
                )
            except Exception as create_error:
                # Another Sage process may have created the deterministic ID.
                # A genuine backend failure still propagates from connect.
                try:
                    return self.volume_class.connect(name, config=self.config)
                except self.volume_not_found:
                    raise create_error
            if created.volume_id != name:
                raise RuntimeError("Cube returned an unexpected Volume ID")
            return created

    def create_sandbox(self, name: str, *, timeout: int | None = None):
        volume = self.ensure_volume(name)
        # Cube documents 0.0.0.0/0 as its full-deny egress rule.
        return self.sandbox_class.create(
            template=self.template_id,
            timeout=timeout,
            config=self.config,
            volume_mounts={"/workspace": volume},
            allow_internet_access=False,
            network={"deny_out": ["0.0.0.0/0"]},
        )


@dataclass
class _CubeRow:
    ref: SandboxRef
    spec: object
    sandbox: object
    created_at: datetime
    updated_at: datetime
    state: SandboxState = SandboxState.READY
    revision: int = 0
    attached_clients: int = 1
    process_slots: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(1))


class _CubeFiles:
    def __init__(self, provider, row):
        self.provider, self.row = provider, row

    def normalize_path(self, path):
        parts = relative_parts(path)
        return "/workspace" + ("/" + "/".join(parts) if parts else "")

    async def _call(self, operation, path, *, policy_operation=None, **kwargs):
        self.provider._authorize(self.row, policy_operation or FileOperation(operation), path, kwargs.pop("intent"), kwargs.pop("grant"))
        return await asyncio.to_thread(cube_file_call, self.row.sandbox, operation, path, **kwargs)

    async def read_bytes(self, path, *, intent, grant):
        limit = self.row.spec.filesystem.max_file_bytes or 8 * 1024 * 1024
        value = await self._call("read", path, intent=intent, grant=grant, max_bytes=limit)
        return base64.b64decode(value["data"])

    async def write_bytes(self, path, content, *, intent, grant, overwrite=True):
        try:
            operation = FileOperation(intent.operation)
        except ValueError as exc:
            raise PermissionError("write requires a create or write grant") from exc
        if operation not in {FileOperation.CREATE, FileOperation.WRITE}:
            raise PermissionError("write requires a create or write grant")
        self.provider._authorize(self.row, operation, path, intent, grant)
        wire_path = self.normalize_path(path)
        try:
            await asyncio.to_thread(cube_file_call, self.row.sandbox, "stat", wire_path)
            exists = True
        except FileNotFoundError:
            exists = False
        if operation == FileOperation.CREATE and exists:
            raise FileExistsError(path)
        if operation == FileOperation.WRITE and not exists:
            raise FileNotFoundError(path)
        if exists and not overwrite:
            raise FileExistsError(path)
        limit = self.row.spec.filesystem.max_file_bytes or 8 * 1024 * 1024
        value = await asyncio.to_thread(
            cube_file_call, self.row.sandbox, "write", wire_path,
            data=base64.b64encode(bytes(content)).decode(), max_bytes=limit,
            overwrite=operation == FileOperation.WRITE,
        )
        self.row.revision += 1
        self.row.updated_at = utc_now()
        return self.provider._file_stat(value)

    async def delete(self, path, *, intent, grant):
        await self._call("delete", path, intent=intent, grant=grant,
                         policy_operation=FileOperation.DELETE)
        self.row.revision += 1
        self.row.updated_at = utc_now()

    async def stat(self, path, *, intent, grant):
        value = await self._call("stat", path, intent=intent, grant=grant,
                                 policy_operation=FileOperation.READ)
        return self.provider._file_stat(value)

    async def list_paths(self, path, *, intent, grant):
        values = await self._call("walk", path, intent=intent, grant=grant,
                                  policy_operation=FileOperation.LIST)
        return tuple(self.provider._file_stat(item) for item in values)


class _CubeProcess:
    def __init__(self, provider, row):
        self.provider, self.row = provider, row

    @asynccontextmanager
    async def open_process(self, request, *, intent, grant):
        raise RuntimeError("Cube SDK does not provide interactive stdio processes")
        yield  # pragma: no cover

    async def run(self, request, *, intent, grant):
        self.provider._verify(self.row, "process.run", intent, grant)
        policy = self.row.spec.process
        if not policy.enabled or policy.read_only:
            raise PermissionError("process execution is disabled")
        if (intent.argv != request.argv or intent.executable != request.argv[0]
                or intent.path != request.cwd
                or intent.metadata.get("process_request_digest") != request.digest()):
            raise PermissionError("process request does not match signed intent")
        if request.stdin is not None:
            raise ValueError("Cube SDK command API does not support stdin")
        if policy.allowed_executables and request.argv[0] not in policy.allowed_executables:
            raise PermissionError("executable is not allowed")
        if request.argv[0] in {"sh", "bash"} and not policy.allow_shell:
            raise PermissionError("shell execution is disabled")
        if set(request.env) - set(policy.allowed_env_names):
            raise PermissionError("environment variable is not allowed")
        if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) or "\x00" in value
               for key, value in request.env.items()):
            raise ValueError("invalid environment variable")
        cwd = _CubeFiles(self.provider, self.row).normalize_path(request.cwd)
        timeout = min(request.timeout_seconds or 300, policy.max_wall_time_seconds or 300)
        async with self.row.process_slots:
            if self.row.state != SandboxState.READY:
                raise PermissionError("sandbox is not ready")
            started = time.monotonic()
            result = await asyncio.to_thread(
                self.row.sandbox.commands.run, shlex.join(request.argv),
                cwd=cwd, envs=request.env, timeout=timeout,
            )
        stdout, stderr = result.stdout.encode(), result.stderr.encode()
        limit = policy.max_output_bytes
        truncated = len(stdout) + len(stderr) > limit
        return ProcessResult(
            process_id=new_id("process"), argv=request.argv, exit_code=result.exit_code,
            stdout=stdout[:limit], stderr=stderr[:max(0, limit-len(stdout))],
            duration_seconds=time.monotonic()-started, truncated=truncated,
        )


class _CubeNoNetwork:
    async def request(self, request, *, intent, grant):
        raise PermissionError("network access is disabled")


class _CubeHandle:
    def __init__(self, provider, row):
        self.provider, self.ref = provider, row.ref
        self.filesystem = _CubeFiles(provider, row)
        self.process = _CubeProcess(provider, row)
        self.network = _CubeNoNetwork()
        self._closed = False

    async def status(self):
        return await self.provider.inspect(self.ref)

    async def suspend(self):
        raise RuntimeError("Cube Volume provider does not support snapshots")

    async def close(self):
        if not self._closed:
            row = self.provider._row(self.ref)
            row.attached_clients = max(0, row.attached_clients - 1)
            self._closed = True

    async def destroy(self):
        await self.provider.terminate(self.ref, TerminateMode.FORCE)
        await self.close()


class CubeVolumeSandboxProvider:
    plugin_id = "sage.sandbox.cube-volume"
    provider_id = plugin_id
    provider_version = "3.0.0"
    name = "CubeSandbox Volume provider"
    description = "Remote VM execution with a persistent Cube Volume workspace."

    def __init__(self, verification_key: bytes, *, client: CubeVolumeClient | None = None,
                 api_url: str = "", template_id: str = "", proxy_node_ip: str = "",
                 api_key: str | None = None, volume_driver: str | None = None):
        self.verification_key = verification_key
        self.client = client or CubeVolumeClient(
            api_url=api_url, template_id=template_id, proxy_node_ip=proxy_node_ip,
            api_key=api_key, volume_driver=volume_driver,
        )
        self._rows: dict[str, _CubeRow] = {}
        self._used_nonces: dict[str, datetime] = {}
        self._receipts: dict[tuple[str, str], SandboxReleaseReceipt] = {}

    async def capabilities(self):
        return SandboxCapabilities(
            isolation_level=IsolationLevel.VM, os="linux", architectures=("native",),
            filesystem_modes=frozenset({FileSystemMode.WORKSPACE}),
            network_modes=frozenset({NetworkMode.NONE}),
            process=ProcessCapabilities(available=True, supports_argv=True, supports_shell=True,
                                        supports_stdio=False),
            resources=ResourceLimitCapabilities(wall_time=True),
            supports_background_jobs=False, supports_suspend=False, supports_snapshot=False,
            supports_reconnect=False, supports_secret_injection=False,
            supported_release_dispositions=frozenset({SandboxReleaseDisposition.DETACH,
                                                       SandboxReleaseDisposition.TERMINATE}),
            supports_terminal_purge=True,
        )

    async def provision(self, spec, context, *, run_id):
        validate_resource_support(spec, await self.capabilities())
        if spec.workspace_root != "/workspace" or spec.filesystem_mode != FileSystemMode.WORKSPACE:
            raise ValueError("Cube Volume sandbox requires /workspace and workspace mode")
        if spec.network.mode != NetworkMode.NONE or spec.mounts:
            raise ValueError("Cube Volume sandbox supports only a Volume mount with no egress")
        if spec.process.read_only or spec.process.allow_background_jobs:
            raise ValueError("Cube SDK cannot enforce this process policy")
        if spec.filesystem.max_total_bytes is not None:
            raise ValueError("Cube Volume provider cannot enforce an aggregate workspace byte limit")
        if (spec.filesystem.max_file_bytes is not None
                and spec.filesystem.max_file_bytes > 8 * 1024 * 1024):
            raise ValueError("Cube Volume file API supports files up to 8 MiB")
        if spec.filesystem.protected_paths and spec.process.enabled:
            raise ValueError("writable processes cannot enforce protected file paths")
        if spec.lifecycle.durability != SandboxDurability.DURABLE_EXTERNAL:
            raise ValueError("Cube Volume workspace requires durable_external lifecycle")
        if (spec.lifecycle.max_lifetime_seconds is not None
                or spec.lifecycle.safe_pause_behavior == SandboxReleaseDisposition.SNAPSHOT_AND_TERMINATE
                or spec.lifecycle.unsafe_pause_behavior == SandboxReleaseDisposition.SNAPSHOT_AND_TERMINATE):
            raise ValueError("Cube Volume provider cannot enforce this lifecycle policy")
        agent_id = spec.metadata.get("cube_agent_id")
        private_run_id = spec.metadata.get("cube_private_run_id")
        if not isinstance(agent_id, str) or not agent_id:
            raise ValueError("trusted Cube Agent identity is required")
        if private_run_id is not None and private_run_id != run_id:
            raise ValueError("private Cube workspace must belong to this Run")
        name = cube_volume_name(
            context.actor.principal_id, agent_id, private_run_id=private_run_id
        )
        if spec.metadata.get("cube_volume_name") not in {None, name}:
            raise PermissionError("Cube Volume name does not match signed workspace identity")
        sandbox = await asyncio.to_thread(
            self.client.create_sandbox, name, timeout=spec.lifecycle.idle_ttl_seconds
        )
        now = utc_now()
        ref = SandboxRef(
            sandbox_id=sandbox.sandbox_id, provider_id=self.provider_id,
            provider_version=self.provider_version, tenant_id=context.actor.tenant_id,
            owner_run_id=run_id, spec_hash=spec.spec_hash, policy_hash=spec.policy_hash,
        )
        row = _CubeRow(ref, spec, sandbox, now, now,
                       process_slots=asyncio.Semaphore(spec.process.max_processes))
        self._rows[ref.sandbox_id] = row
        return _CubeHandle(self, row)

    async def attach(self, ref, context):
        row = self._row(ref)
        if ref.tenant_id != context.actor.tenant_id or row.state != SandboxState.READY:
            raise PermissionError("sandbox is unavailable to this tenant")
        row.attached_clients += 1
        return _CubeHandle(self, row)

    async def inspect(self, ref):
        row = self._row(ref)
        return SandboxSnapshot(ref=ref, state=row.state, revision=row.revision,
                               created_at=row.created_at, updated_at=row.updated_at,
                               attached_clients=row.attached_clients)

    async def snapshot(self, ref):
        raise RuntimeError("Cube Volume provider does not support VM snapshots")

    async def restore(self, checkpoint, context):
        raise RuntimeError("Cube Volume provider does not support VM snapshots")

    async def release(self, request, context):
        row = self._row(request.ref)
        if row.ref.tenant_id != context.actor.tenant_id:
            raise PermissionError("tenant does not own sandbox")
        key = (request.ref.sandbox_id, request.idempotency_key)
        previous = self._receipts.get(key)
        if previous:
            return previous.model_copy(update={"duplicate": True})
        if request.expected_revision != row.revision:
            raise RuntimeError("sandbox revision does not match release request")
        if request.disposition == SandboxReleaseDisposition.SNAPSHOT_AND_TERMINATE:
            raise RuntimeError("Cube Volume provider does not support snapshots")
        if request.disposition == SandboxReleaseDisposition.TERMINATE:
            await self.terminate(request.ref, TerminateMode.FORCE)
        receipt = SandboxReleaseReceipt(
            ref=request.ref, disposition=request.disposition, state=row.state,
            compute_released=row.state == SandboxState.TERMINATED, released_at=utc_now(),
        )
        self._receipts[key] = receipt
        return receipt

    async def terminate(self, ref, mode):
        row = self._row(ref)
        if row.state == SandboxState.TERMINATED:
            return
        row.state = SandboxState.LOST
        try:
            await asyncio.to_thread(row.sandbox.kill)
        except BaseException:
            row.state = SandboxState.LOST
            raise
        row.state = SandboxState.TERMINATED
        row.revision += 1
        row.updated_at = utc_now()

    async def purge_terminated(self, ref):
        row = self._row(ref)
        if row.state != SandboxState.TERMINATED or row.attached_clients:
            raise RuntimeError("only detached terminated sandboxes can be purged")
        self._rows.pop(ref.sandbox_id)
        now = utc_now()
        self._used_nonces = {nonce: expiry for nonce, expiry in self._used_nonces.items()
                             if expiry > now}
        self._receipts = {key: value for key, value in self._receipts.items() if key[0] != ref.sandbox_id}

    def _row(self, ref):
        row = self._rows.get(ref.sandbox_id)
        if row is None or row.ref != ref:
            raise ValueError("sandbox reference is unknown")
        return row

    def _verify(self, row, operation, intent, grant):
        payload = json.dumps(grant.model_dump(mode="json", exclude={"signature"}),
                             sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        signature = hmac.new(self.verification_key, payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, grant.signature):
            raise PermissionError("sandbox grant signature is invalid")
        now = utc_now()
        self._used_nonces = {nonce: expiry for nonce, expiry in self._used_nonces.items()
                             if expiry > now}
        if grant.expires_at <= now or grant.nonce in self._used_nonces or row.state != SandboxState.READY:
            raise PermissionError("sandbox grant is expired, used or sandbox is unavailable")
        if (intent.operation != operation or intent.sandbox_id != row.ref.sandbox_id
                or intent.run_id != row.ref.owner_run_id or grant.run_id != intent.run_id
                or grant.tool_call_id != intent.tool_call_id or grant.sandbox_id != row.ref.sandbox_id
                or grant.spec_hash != row.ref.spec_hash or grant.policy_hash != row.ref.policy_hash
                or grant.tenant_id != row.ref.tenant_id or grant.operation_digest != intent.digest()
                or operation not in grant.allowed_operations):
            raise PermissionError("sandbox grant does not match operation")
        if grant.single_use:
            self._used_nonces[grant.nonce] = grant.expires_at

    def _authorize(self, row, operation, path, intent, grant):
        self._verify(row, operation.value, intent, grant)
        if intent.path != path or operation not in row.spec.filesystem.allowed_operations:
            raise PermissionError("file operation does not match signed intent or policy")
        parts = relative_parts(path)
        wire = "/workspace" + ("/" + "/".join(parts) if parts else "")
        if not any(wire == root or wire.startswith(root.rstrip("/") + "/")
                   for root in row.spec.filesystem.allowed_roots):
            raise PermissionError("path is outside allowed roots")
        if operation in MUTATING_FILE_OPERATIONS:
            protected = row.spec.filesystem.protected_path_for("/".join(parts))
            if protected is not None:
                raise PermissionError(f"path is protected by sandbox policy ({protected})")

    @staticmethod
    def _file_stat(item):
        return FileStat(path="/workspace" + ("/" + item["path"] if item["path"] else ""),
                        size=item["size"], is_file=item["is_file"],
                        is_directory=item["is_directory"])

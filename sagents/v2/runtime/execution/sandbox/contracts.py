"""SAgents V2 module for runtime/execution/sandbox/contracts.py."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import Field, field_serializer, model_validator

from sagents.v2.contracts.common import Identifier, StrictModel


class IsolationLevel(str, Enum):
    NONE = "none"
    PROCESS = "process"
    CONTAINER = "container"
    VM = "vm"
    REMOTE_MANAGED = "remote_managed"


class FileSystemMode(str, Enum):
    WORKSPACE = "workspace"
    MOUNTS = "mounts"
    OVERLAY = "overlay"
    SNAPSHOT = "snapshot"


class NetworkMode(str, Enum):
    NONE = "none"
    ALLOWLIST = "allowlist"
    PROXY = "proxy"
    UNRESTRICTED = "unrestricted"


class FileOperation(str, Enum):
    READ = "read"
    WRITE = "write"
    CREATE = "create"
    DELETE = "delete"
    RENAME = "rename"
    LIST = "list"


class SandboxState(str, Enum):
    PROVISIONING = "provisioning"
    READY = "ready"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"
    LOST = "lost"


class SandboxDurability(str, Enum):
    EPHEMERAL = "ephemeral"
    RECONNECTABLE = "reconnectable"
    SNAPSHOTABLE = "snapshotable"
    DURABLE_EXTERNAL = "durable_external"


class TerminateMode(str, Enum):
    GRACEFUL = "graceful"
    FORCE = "force"


class SandboxReleaseDisposition(str, Enum):
    """Host-selected treatment of compute at an execution boundary."""

    DETACH = "detach"
    TERMINATE = "terminate"
    SNAPSHOT_AND_TERMINATE = "snapshot_and_terminate"


class ProcessCapabilities(StrictModel):
    available: bool
    supports_argv: bool = False
    supports_shell: bool = False
    supports_signals: bool = False
    supports_pty: bool = False
    max_processes: int | None = Field(default=None, gt=0)


class ResourceLimitCapabilities(StrictModel):
    cpu: bool = False
    memory: bool = False
    disk: bool = False
    process_count: bool = False
    file_descriptors: bool = False
    wall_time: bool = False
    network_bytes: bool = False


class SandboxCapabilities(StrictModel):
    api_version: Literal["3"] = "3"
    isolation_level: IsolationLevel
    os: str
    architectures: tuple[str, ...]
    filesystem_modes: frozenset[FileSystemMode]
    network_modes: frozenset[NetworkMode]
    process: ProcessCapabilities
    resources: ResourceLimitCapabilities
    supports_background_jobs: bool
    supports_suspend: bool
    supports_snapshot: bool
    supports_reconnect: bool
    supports_secret_injection: bool
    supported_release_dispositions: frozenset[SandboxReleaseDisposition]
    supports_terminal_purge: bool = False
    supports_automatic_terminal_retention: bool = False
    terminal_ttl_seconds: int | None = Field(default=None, gt=0)
    max_retained_terminal_items: int | None = Field(default=None, ge=0)
    max_lifetime_seconds: int | None = Field(default=None, gt=0)

    @field_serializer(
        "filesystem_modes",
        "network_modes",
        "supported_release_dispositions",
        when_used="json",
    )
    def serialize_capability_sets(self, value: frozenset[Enum]) -> list[str]:
        """Keep capability negotiation stable on every process/hash seed."""

        return sorted(item.value for item in value)


class MountSpec(StrictModel):
    source_ref: Identifier
    target: str
    read_only: bool = True
    noexec: bool = True
    allow_symlinks: bool = False


class FileSystemPolicy(StrictModel):
    allowed_operations: frozenset[FileOperation]
    allowed_roots: tuple[str, ...] = ("/workspace",)
    max_file_bytes: int | None = Field(default=None, gt=0)
    max_total_bytes: int | None = Field(default=None, gt=0)
    allow_symlinks: bool = False

    @field_serializer("allowed_operations", when_used="json")
    def serialize_allowed_operations(
        self, value: frozenset[FileOperation]
    ) -> list[str]:
        """Keep persisted policy JSON and hashes stable across processes."""

        return sorted(operation.value for operation in value)


class ProcessPolicy(StrictModel):
    enabled: bool = False
    read_only: bool = False
    allowed_executables: tuple[str, ...] = ()
    allow_shell: bool = False
    allowed_env_names: tuple[str, ...] = ()
    max_processes: int = Field(default=1, gt=0)
    max_wall_time_seconds: float | None = Field(default=None, gt=0)
    max_output_bytes: int = Field(default=1_048_576, gt=0)
    allow_background_jobs: bool = False


class NetworkPolicy(StrictModel):
    mode: NetworkMode = NetworkMode.NONE
    allowed_hosts: tuple[str, ...] = ()
    allowed_ports: tuple[int, ...] = ()
    allowed_schemes: tuple[Literal["http", "https"], ...] = ("https",)
    allowed_methods: tuple[str, ...] = ("GET", "HEAD")
    allowed_request_headers: tuple[str, ...] = (
        "accept",
        "content-type",
        "user-agent",
    )
    allow_listen: bool = False
    deny_private_networks: bool = True
    max_redirects: int = Field(default=5, ge=0, le=20)
    max_request_body_bytes: int = Field(default=1_048_576, ge=0)
    max_response_bytes: int = Field(default=10_485_760, gt=0)
    max_wall_time_seconds: float = Field(default=30, gt=0)

    @model_validator(mode="after")
    def validate_none_mode(self) -> "NetworkPolicy":
        if self.mode == NetworkMode.NONE and (
            self.allowed_hosts or self.allowed_ports or self.allow_listen
        ):
            raise ValueError("network mode none cannot contain network allowances")
        return self


class LifecyclePolicy(StrictModel):
    durability: SandboxDurability = SandboxDurability.EPHEMERAL
    idle_ttl_seconds: int | None = Field(default=None, gt=0)
    max_lifetime_seconds: int | None = Field(default=None, gt=0)
    safe_pause_behavior: SandboxReleaseDisposition = (
        SandboxReleaseDisposition.SNAPSHOT_AND_TERMINATE
    )
    unsafe_pause_behavior: SandboxReleaseDisposition = SandboxReleaseDisposition.DETACH

    @model_validator(mode="before")
    @classmethod
    def migrate_v2_pause_behavior(cls, value: Any) -> Any:
        """Load persisted v2 policy values without accepting a v2 provider."""

        if not isinstance(value, dict) or "pause_behavior" not in value:
            return value
        migrated = dict(value)
        legacy = str(migrated.pop("pause_behavior"))
        aliases = {
            "snapshot": SandboxReleaseDisposition.SNAPSHOT_AND_TERMINATE.value,
            "snapshot_and_terminate": SandboxReleaseDisposition.SNAPSHOT_AND_TERMINATE.value,
            "terminate": SandboxReleaseDisposition.TERMINATE.value,
            "retain": SandboxReleaseDisposition.DETACH.value,
            "detach": SandboxReleaseDisposition.DETACH.value,
        }
        try:
            migrated.setdefault("safe_pause_behavior", aliases[legacy])
        except KeyError as exc:
            raise ValueError(f"unsupported legacy pause_behavior {legacy!r}") from exc
        return migrated


class ResolvedSandboxSpec(StrictModel):
    spec_version: Literal["sage.sandbox-spec/v3"] = "sage.sandbox-spec/v3"
    spec_hash: str
    workspace_root: str = "/workspace"
    architecture: str
    filesystem_mode: FileSystemMode = FileSystemMode.WORKSPACE
    mounts: tuple[MountSpec, ...] = ()
    filesystem: FileSystemPolicy
    process: ProcessPolicy = Field(default_factory=ProcessPolicy)
    network: NetworkPolicy = Field(default_factory=NetworkPolicy)
    lifecycle: LifecyclePolicy = Field(default_factory=LifecyclePolicy)
    policy_hash: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class SandboxRef(StrictModel):
    sandbox_id: Identifier
    provider_id: Identifier
    provider_version: str
    tenant_id: Identifier | None = None
    owner_run_id: Identifier
    spec_hash: str
    policy_hash: str


class SandboxSnapshot(StrictModel):
    ref: SandboxRef
    state: SandboxState
    revision: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime
    attached_clients: int = Field(default=0, ge=0)
    file_count: int = Field(default=0, ge=0)
    total_file_bytes: int = Field(default=0, ge=0)


class SandboxCheckpointRef(StrictModel):
    checkpoint_id: Identifier
    provider_id: Identifier
    provider_version: str
    tenant_id: Identifier | None = None
    sandbox_id: Identifier
    snapshot_ref: Identifier | None = None
    state_revision: int = Field(ge=0)
    spec_hash: str
    policy_hash: str
    job_refs: tuple[Identifier, ...] = ()
    created_at: datetime
    expires_at: datetime | None = None


class SandboxReleaseRequest(StrictModel):
    ref: SandboxRef
    disposition: SandboxReleaseDisposition
    reason: str
    expected_revision: int = Field(ge=0)
    idempotency_key: Identifier


class SandboxReleaseReceipt(StrictModel):
    ref: SandboxRef
    disposition: SandboxReleaseDisposition
    state: SandboxState
    checkpoint: SandboxCheckpointRef | None = None
    compute_released: bool
    duplicate: bool = False
    released_at: datetime

    @model_validator(mode="after")
    def validate_release_result(self) -> "SandboxReleaseReceipt":
        if self.compute_released and self.state != SandboxState.TERMINATED:
            raise ValueError("compute_released requires a terminated sandbox")
        if (
            self.disposition == SandboxReleaseDisposition.SNAPSHOT_AND_TERMINATE
            and self.compute_released
            and self.checkpoint is None
        ):
            raise ValueError("snapshot release requires a checkpoint")
        if (
            self.disposition == SandboxReleaseDisposition.DETACH
            and self.compute_released
        ):
            raise ValueError("detach cannot claim compute was released")
        return self


class OperationIntent(StrictModel):
    operation: Identifier
    run_id: Identifier
    tool_call_id: Identifier
    sandbox_id: Identifier
    path: str | None = None
    target_path: str | None = None
    executable: str | None = None
    argv: tuple[str, ...] = ()
    network_host: str | None = None
    network_port: int | None = Field(default=None, ge=1, le=65535)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def digest(self) -> str:
        payload = self.model_dump(mode="json", exclude_none=True)
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class SandboxGrant(StrictModel):
    grant_id: Identifier
    run_id: Identifier
    tool_call_id: Identifier
    sandbox_id: Identifier
    tenant_id: Identifier | None = None
    policy_hash: str
    spec_hash: str
    operation_digest: str
    allowed_operations: frozenset[Identifier]
    issued_at: datetime
    expires_at: datetime
    nonce: Identifier
    single_use: bool = True
    signature: str

    @field_serializer("allowed_operations", when_used="json")
    def serialize_allowed_operations(self, value: frozenset[str]) -> list[str]:
        """Canonicalize the signed grant payload for cross-process verification."""

        return sorted(value)


class FileStat(StrictModel):
    path: str
    size: int = Field(ge=0)
    is_file: bool
    is_directory: bool
    content_hash: str | None = None


class ProcessRequest(StrictModel):
    argv: tuple[str, ...]
    cwd: str = "/workspace"
    env: dict[str, str] = Field(default_factory=dict)
    stdin: bytes | None = None
    timeout_seconds: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_argv(self) -> "ProcessRequest":
        if not self.argv or not self.argv[0]:
            raise ValueError("process argv must include an executable")
        return self


class ProcessResult(StrictModel):
    process_id: Identifier
    argv: tuple[str, ...]
    exit_code: int
    stdout: bytes = b""
    stderr: bytes = b""
    timed_out: bool = False
    duration_seconds: float = Field(ge=0)
    truncated: bool = False


class NetworkRequest(StrictModel):
    method: str = "GET"
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    body: bytes | None = None
    timeout_seconds: float | None = Field(default=None, gt=0)


class NetworkResult(StrictModel):
    request_id: Identifier
    status_code: int = Field(ge=100, le=599)
    final_url: str
    headers: dict[str, str] = Field(default_factory=dict)
    body: bytes = b""
    redirect_count: int = Field(default=0, ge=0)
    truncated: bool = False

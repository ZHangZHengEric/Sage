from dataclasses import asdict, dataclass
from typing import Any, Mapping, Optional, Union


DEFAULT_VIRTUAL_WORKSPACE = "/sage-workspace"


@dataclass
class RuntimeContext:
    """Normalized runtime/deployment context for a session run."""

    deployment_mode: str = "desktop"
    sandbox_mode: str = "local"
    host_workspace: Optional[str] = None
    virtual_workspace: str = DEFAULT_VIRTUAL_WORKSPACE
    sandbox_id: Optional[str] = None
    remote_server_url: Optional[str] = None
    remote_provider: Optional[str] = None
    remote_api_key: Optional[str] = None
    remote_image: Optional[str] = None
    remote_timeout: Optional[int] = None
    remote_persistent: Optional[bool] = None
    remote_sandbox_ttl: Optional[int] = None

    @classmethod
    def from_input(
        cls,
        runtime_context: Optional[Union["RuntimeContext", Mapping[str, Any]]] = None,
        **legacy_kwargs: Any,
    ) -> "RuntimeContext":
        if isinstance(runtime_context, cls):
            data = runtime_context.to_dict()
        elif isinstance(runtime_context, Mapping):
            data = dict(runtime_context)
        elif runtime_context is None:
            data = {}
        else:
            raise TypeError(f"Unsupported runtime_context type: {type(runtime_context)!r}")

        for key, value in legacy_kwargs.items():
            if value is None:
                continue
            current = data.get(key)
            if current in (None, ""):
                data[key] = value

        deployment_mode = str(data.get("deployment_mode") or "desktop").lower()
        sandbox_mode = str(data.get("sandbox_mode") or "local").lower()
        virtual_workspace = str(data.get("virtual_workspace") or DEFAULT_VIRTUAL_WORKSPACE)
        host_workspace = data.get("host_workspace")
        if host_workspace is not None:
            host_workspace = str(host_workspace)

        return cls(
            deployment_mode=deployment_mode,
            sandbox_mode=sandbox_mode,
            host_workspace=host_workspace,
            virtual_workspace=virtual_workspace,
            sandbox_id=data.get("sandbox_id"),
            remote_server_url=data.get("remote_server_url"),
            remote_provider=data.get("remote_provider"),
            remote_api_key=data.get("remote_api_key"),
            remote_image=data.get("remote_image"),
            remote_timeout=data.get("remote_timeout"),
            remote_persistent=data.get("remote_persistent"),
            remote_sandbox_ttl=data.get("remote_sandbox_ttl"),
        )

    def requires_host_workspace(self) -> bool:
        return self.sandbox_mode in {"local", "passthrough"}

    def is_remote(self) -> bool:
        return self.sandbox_mode == "remote"

    def validate(self) -> None:
        if self.requires_host_workspace() and (
            self.host_workspace is None or not str(self.host_workspace).strip()
        ):
            raise ValueError("host_workspace is required for local/passthrough runtime")
        if self.is_remote():
            if not self.sandbox_id or not str(self.sandbox_id).strip():
                raise ValueError("sandbox_id is required for remote runtime")
            if not self.remote_server_url or not str(self.remote_server_url).strip():
                raise ValueError("remote_server_url is required for remote runtime")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def signature(self) -> tuple[Any, ...]:
        data = self.to_dict()
        return tuple((key, data[key]) for key in sorted(data.keys()))

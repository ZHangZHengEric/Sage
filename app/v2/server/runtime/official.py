"""Product tool metadata and registered sandbox services for file management."""

from __future__ import annotations

from sagents.v2.runtime.execution.sandbox import (
    NetworkPolicy, NetworkMode, SandboxGrantIssuer,
)
from sagents.v2.tool.plugins.official import (
    official_tool_categories,
    official_tool_definitions,
)
from sagents.v2.tool.contracts import ToolDefinition

DEFAULT_OFFICIAL_TOOLS = (
    "file_read",
    "file_write",
    "file_update",
    "apply_patch",
    "list_dir",
    "glob",
    "grep",
    "execute_shell_command",
    "await_shell",
    "kill_shell",
    "todo_write",
    "todo_read",
)


async def install_sandbox(execution, application, settings=None) -> None:
    """Create the process provider through the application's plugin lifecycle."""

    if execution.sandbox_grant_issuer is not None:
        return
    execution.sandbox_provider = application.service("server.file-sandbox")
    execution.sandbox_grant_issuer = application.service("server.file-grants")


def file_sandbox_registrations(settings):
    from app.v2.server.runtime.sdk_plugins import service_registration
    from sagents.v2.runtime.extensions import ExtensionDependency, ExtensionRegistration
    from sagents.v2.runtime.execution.sandbox import LocalWorkspaceSandboxProvider
    issuer = SandboxGrantIssuer()
    grants = service_registration("server.file-grants", issuer)
    template = service_registration("server.file-sandbox", None, ownership="owned")
    async def create(context, deps):
        provider = LocalWorkspaceSandboxProvider(
            deps.require("server.file-grants").verification_key,
            linux_execution_uid=settings.linux_execution_uid,
            linux_execution_gid=settings.linux_execution_gid,
        )
        await provider.validate_runtime(forbidden_roots=(settings.data_root,))
        return provider
    return grants, ExtensionRegistration(
        descriptor=template.descriptor.model_copy(update={
            "dependencies": (ExtensionDependency(capability="server.file-grants"),),
        }), factory=create,
    )


def default_agent_tools() -> list[str]:
    """Initial Package configuration; execution never expands an empty list."""
    return list(DEFAULT_OFFICIAL_TOOLS)


def official_tool_catalog() -> list[dict[str, object]]:
    defaults = set(DEFAULT_OFFICIAL_TOOLS)
    categories = official_tool_categories()
    return [
        tool_catalog_item(item, category=categories.get(item.name, ""), default=item.name in defaults)
        for item in official_tool_definitions()
    ]


def tool_catalog_item(
    definition: ToolDefinition, *, category: str = "", source: str = "official", default: bool = False
) -> dict[str, object]:
    """Project discovery metadata; browsing a definition never invokes its tool."""
    return {
        "name": definition.name,
        "description": definition.description,
        "input_schema": definition.input_schema,
        "side_effect_level": definition.side_effect_level.value,
        "requires_approval": definition.requires_approval,
        "approval_key": definition.approval_key,
        "category": category,
        "source": source,
        "default": default,
    }


def agent_network_policy(sandbox, settings, *, live=None):
    mode = NetworkMode.UNRESTRICTED if (
        sandbox.network == settings.sandbox_network_mode == "unrestricted"
        and (live is None or live.network == "unrestricted")
    ) else NetworkMode.NONE
    return NetworkPolicy(mode=mode, deny_private_networks=mode != NetworkMode.UNRESTRICTED)

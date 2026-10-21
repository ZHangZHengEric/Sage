"""Official repository and workspace choices, through public plugin contracts."""

from pydantic import Field

from sagents.v2.concurrency import bounded_to_thread
from sagents.v2.contracts.common import StrictModel
from sagents.v2.runtime.extensions import (
    CapabilityOffer,
    ExtensionDependency,
    ExtensionDescriptor,
    ExtensionRegistration,
    ExtensionScope,
)
from sagents.v2.skill.plugins.repository import (
    MemorySkillRepository,
    SqliteSkillRepository,
)
from sagents.v2.skill.plugins.workspace import (
    AutoSyncSkillWorkspace,
    FixedCopySkillWorkspace,
    ReadonlyMountSkillWorkspace,
)


class RepositoryConfig(StrictModel):
    path: str = Field(min_length=1)
    max_files: int = Field(default=2000, gt=0, strict=True)
    max_total_bytes: int = Field(default=64 * 1024**2, gt=0, strict=True)


class MemoryRepositoryConfig(StrictModel):
    max_files: int = Field(default=2000, gt=0, strict=True)
    max_total_bytes: int = Field(default=64 * 1024**2, gt=0, strict=True)


class WorkspaceConfig(MemoryRepositoryConfig):
    pass


def skill_registrations():
    values = []
    for implementation, config in (
        (SqliteSkillRepository, RepositoryConfig),
        (MemorySkillRepository, MemoryRepositoryConfig),
    ):

        async def repository(context, deps, implementation=implementation):
            return await bounded_to_thread(
                "skill-io", lambda: implementation(**context.config)
            )

        values.append(
            ExtensionRegistration(
                descriptor=ExtensionDescriptor(
                    plugin_id=implementation.plugin_id,
                    name=implementation.name,
                    description=implementation.description,
                    version="2.0.0",
                    provides=tuple(
                        CapabilityOffer(capability=name, api_version="2")
                        for name in (
                            "skill.management",
                            "skill.provider",
                        )
                    ),
                    supported_scopes=frozenset({ExtensionScope.PROCESS}),
                    default_scope=ExtensionScope.PROCESS,
                    config_schema=config.model_json_schema(),
                    built_in=True,
                    capabilities={
                        "versioned": True,
                        "writable": True,
                        "durable": implementation is SqliteSkillRepository,
                    },
                ),
                config_model=config,
                factory=repository,
                start=lambda instance, context, deps: {
                    name: instance
                    for name in (
                        "skill.management",
                        "skill.provider",
                    )
                },
            )
        )

    for implementation in (
        AutoSyncSkillWorkspace,
        FixedCopySkillWorkspace,
        ReadonlyMountSkillWorkspace,
    ):

        def create(context, deps, implementation=implementation):
            environment = deps.require("execution.environment")
            if environment.sandbox is None or environment.grant_issuer is None:
                raise ValueError(
                    "Skill workspace requires an execution.binding sandbox"
                )
            return implementation(
                environment.sandbox, environment.grant_issuer, **context.config
            )

        values.append(
            ExtensionRegistration(
                descriptor=ExtensionDescriptor(
                    plugin_id=implementation.plugin_id,
                    name=implementation.name,
                    description=implementation.description,
                    version="2.0.0",
                    provides=(
                        CapabilityOffer(capability="skill.workspace", api_version="2"),
                    ),
                    dependencies=(
                        ExtensionDependency(capability="execution.environment"),
                    ),
                    supported_scopes=frozenset({ExtensionScope.RUN}),
                    default_scope=ExtensionScope.RUN,
                    config_schema=WorkspaceConfig.model_json_schema(),
                    built_in=True,
                    capabilities={
                        "stable_path": True,
                        "auto_sync": implementation is AutoSyncSkillWorkspace,
                        "requires_readonly_mounts": implementation
                        is ReadonlyMountSkillWorkspace,
                    },
                ),
                factory=create,
                config_model=WorkspaceConfig,
            )
        )
    return tuple(values)

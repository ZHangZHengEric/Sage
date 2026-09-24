"""Thin Server adapter for the SAgents package-management contract."""

from __future__ import annotations

from pathlib import Path

from sagents.v2.agent.management import AgentManagementService

from app.server_v2.packages.builder import ServerPackageBuilderFactory
from app.server_v2.packages.policy import ServerPackagePolicy
from app.server_v2.packages.queries import ServerPackageQueries
from app.server_v2.packages.repository import DatabasePackageStore


class ServerAgentManagement(AgentManagementService):
    def __init__(
        self,
        root,
        *,
        database,
        settings,
        paths,
        users,
        catalog,
        skills,
        skill_catalog,
        execution,
        mcp_plugins,
        a2a_plugins,
        package_authorizer,
        extensions,
        run_quota,
        model_budget,
        log_sink,
        job_runtime,
    ):
        if database is None:
            raise ValueError("Server package database is required")
        Path(root).mkdir(parents=True, exist_ok=True)
        self.policy = ServerPackagePolicy(
            users=users,
            catalog=catalog,
            skills=skills,
            package_authorizer=package_authorizer,
            extensions=extensions,
        )
        self.package_builder_factory = ServerPackageBuilderFactory(
            settings=settings,
            paths=paths,
            catalog=catalog,
            skills=skills,
            execution=execution,
            mcp_plugins=mcp_plugins,
            a2a_plugins=a2a_plugins,
            extensions=extensions,
            run_quota=run_quota,
            policy=self.policy,
            log_sink=log_sink,
        )
        self.queries = ServerPackageQueries(
            users=users,
            catalog=catalog,
            skills=skills,
            skill_catalog=skill_catalog,
            model_budget=model_budget,
            run_quota=run_quota,
        )
        super().__init__(
            root,
            store=DatabasePackageStore(database),
            builder_factory=self.builder,
            max_applications=settings.max_managed_applications,
            max_concurrent_builds=settings.max_managed_builds,
            authorize=self.authorize_package,
            model_budget=model_budget,
            job_runtime=job_runtime,
            allow_source_plugins=package_authorizer is not None,
            inventory=tuple(
                {
                    "id": item.descriptor.plugin_id,
                    "version": item.descriptor.version,
                }
                for item in extensions
            ),
        )

    def schema(self):
        return self.queries.schema(super().schema())

    async def resources(self, context):
        return await self.queries.resources(context, super().resources)

    async def authorize_package(self, action, bundle, context):
        await self.policy.authorize(action, bundle, context, self)

    async def builder(self, bundle, root, context):
        return await self.package_builder_factory.build(bundle, root, context, self)

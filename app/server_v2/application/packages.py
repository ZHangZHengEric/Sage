"""Thin Server adapter for the SAgents package-management contract."""

from __future__ import annotations

from pathlib import Path

from sagents.v2.agent.management import AgentManagementService

from app.server_v2.infrastructure.persistence.packages import DatabasePackageStore


class ServerAgentManagement(AgentManagementService):
    def __init__(
        self,
        root,
        *,
        database,
        policy,
        builder_factory,
        queries,
        max_applications,
        max_concurrent_builds,
        model_budget,
        job_runtime,
        allow_source_plugins,
        inventory,
    ):
        if database is None:
            raise ValueError("Server package database is required")
        Path(root).mkdir(parents=True, exist_ok=True)
        self.policy = policy
        self.package_builder_factory = builder_factory
        self.queries = queries
        super().__init__(
            root,
            store=DatabasePackageStore(database),
            builder_factory=self.builder,
            max_applications=max_applications,
            max_concurrent_builds=max_concurrent_builds,
            authorize=self.authorize_package,
            model_budget=model_budget,
            job_runtime=job_runtime,
            allow_source_plugins=allow_source_plugins,
            inventory=inventory,
        )

    def schema(self):
        return self.queries.schema(super().schema())

    async def resources(self, context):
        return await self.queries.resources(context, super().resources)

    async def authorize_package(self, action, bundle, context):
        await self.policy.authorize(action, bundle, context, self)

    async def builder(self, bundle, root, context):
        return await self.package_builder_factory.build(bundle, root, context, self)

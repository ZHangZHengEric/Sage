"""Trusted host execution injection for already-admitted, frozen Runs."""

from dataclasses import dataclass, field
from typing import Any

from sagents.v2.sagent import DriverFactory, SAgent


@dataclass(frozen=True)
class HostAgentExecution:
    """Keep host admission/recovery contracts while sharing the public lifecycle.

    The factory must resolve each run_id independently from its durable snapshot;
    it must not capture a single Run. Providers remain owned by the host App.
    """

    driver_factory: DriverFactory
    spec_hash: str
    runtime: Any
    dispatcher: Any
    agent_id: str | None = None
    memory_service: Any = None
    memory_scope: dict = field(default_factory=dict)

    def resolve_descriptor(self, package, runtime, *, models=None):
        """Identify the facade; the host driver validates/loads the frozen graph.

        Dependencies belong to that per-Run graph, not to a second set of live
        providers in the process facade. Package cardinality is checked by App.
        """
        import hashlib
        import json
        from sagents.v2.package.manifest.resolver import ResolvedSageManifest
        from sagents.v2.composition.resolution import _resolve_package

        if isinstance(package, ResolvedSageManifest):
            return package.model_copy(deep=True)
        name, definition = next(iter(package.agents.items()))
        descriptor = package.model_copy(
            update={"agents": {name: definition.model_copy(update={"subagents": ()})}}
        )
        _, resolved = _resolve_package(descriptor, runtime=runtime, models=models)
        # Include the complete declaration even though the facade owns no graph.
        payload = package.model_dump(mode="json")
        for definition in payload["agents"].values():
            if not definition.get("preload_skills"):
                definition.pop("preload_skills", None)
        digest = hashlib.sha256(
            json.dumps(
                payload, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        return resolved.model_copy(update={"manifest_hash": f"sha256:{digest}"})

    def create_agent(self):
        return SAgent(
            runtime=self.runtime,
            driver_factory=self.driver_factory,
            dispatcher=self.dispatcher,
            memory_service=self.memory_service,
            memory_scope=dict(self.memory_scope),
        )

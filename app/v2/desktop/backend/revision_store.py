"""Upgrade archived Desktop provider names without rewriting accepted Runs."""

from copy import deepcopy

from sagents.v2.composition.revision_store import (
    AgentRevisionStore,
    MigratedAgentRevision,
    RecoveryIdentity,
)
from sagents.v2.package.manifest.runtime import REMOVED_CAPABILITIES


class DesktopAgentRevisionStore(AgentRevisionStore):
    def _decode(self, raw):
        package = raw["package"]
        capabilities = package["runtime"]["capabilities"]
        if raw.get("recovery") or not REMOVED_CAPABILITIES.intersection(capabilities):
            return super()._decode(raw)
        if not package["package_id"].startswith("desktop."):
            return super()._decode(raw)
        package = deepcopy(package)
        choices = package["runtime"]["capabilities"]
        for old, new in (
            ("tool.catalog", "tool.provider"),
            ("skill.catalog", "skill.provider"),
        ):
            if old in choices:
                if new in choices:
                    raise ValueError("conflicting archived Desktop providers")
                values = choices.pop(old)
                for selection in values if isinstance(values, list) else [values]:
                    plugin = selection["plugin"]
                    if plugin == "com.sage.desktop.run." + old.replace(".", "-"):
                        selection["plugin"] = "com.sage.desktop.run." + new.replace(
                            ".", "-"
                        )
                choices[new] = values
        for old in ("tool.executor", "skill.source"):
            if old in choices:
                raise ValueError(
                    f"cannot migrate independent archived {old}; restore its paired provider"
                )
        compactor = choices.pop("context.unit-compactor", None)
        if compactor is not None and (
            compactor["plugin"] != "sage.context.unit-compactor.reference"
            or compactor.get("config")
        ):
            raise ValueError("cannot migrate a custom archived context compactor")
        for signal in ("log", "diagnostic", "trace"):
            name = f"observability.{signal}-sink"
            selection = choices.pop(name, None)
            if selection is None:
                continue
            if selection["plugin"] != "com.sage.desktop." + name.replace(
                ".", "-"
            ) or selection.get("config"):
                raise ValueError("cannot migrate a custom archived observation sink")
        choices["observability.provider"] = {
            "plugin": "com.sage.desktop.observability-provider",
            "scope": "process",
            "config": {},
        }
        resolved = MigratedAgentRevision.model_validate(package)
        resolved._recovery_identity = RecoveryIdentity(raw["spec_hash"])
        return resolved

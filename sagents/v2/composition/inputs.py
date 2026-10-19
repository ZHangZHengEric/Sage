"""Unambiguous public configuration inputs; parsing never opens providers."""

from pathlib import Path
from typing import Any

from sagents.v2.package.manifest.loader import SageManifestLoader
from sagents.v2.package.manifest.root import SageManifest
from sagents.v2.package.manifest.resolver import ResolvedSageManifest
from sagents.v2.package.manifest.runtime import RuntimeConfig
from sagents.v2.package.strict_yaml import load_unique_yaml


PackageInput = SageManifest | ResolvedSageManifest | str | Path | dict[str, Any]
RuntimeInput = RuntimeConfig | str | Path | dict[str, Any]


def runtime_input(
    value: RuntimeInput | None = None, *, config_text: str | None = None
) -> RuntimeConfig | None:
    if value is not None and config_text is not None:
        raise ValueError("runtime and runtime_config_text are mutually exclusive")
    if isinstance(value, (str, Path)):
        config_text = Path(value).expanduser().read_text(encoding="utf-8")
    if config_text is not None:
        value = load_unique_yaml(config_text)
        if not isinstance(value, dict):
            raise ValueError("runtime config must be a mapping")
    if isinstance(value, RuntimeConfig):
        # model_copy(update=...) deliberately bypasses Pydantic validation.
        # Re-parse its contents so callers cannot bypass parameter contracts.
        value = value.model_dump(mode="python")
    return (
        RuntimeConfig.model_validate(value).model_copy(deep=True)
        if value is not None
        else None
    )


def package_input(
    value: PackageInput | None = None,
    *,
    config_text: str | None = None,
    base_path: str | Path | None = None,
) -> SageManifest | ResolvedSageManifest:
    if (value is None) == (config_text is None):
        raise ValueError("provide exactly one of package or config_text")
    loader = SageManifestLoader()
    if isinstance(value, (str, Path)):
        if base_path is not None:
            raise ValueError("base_path is only valid for in-memory configuration")
        path = Path(value).expanduser()
        if path.is_dir():
            path = path / "sage.yaml"
        config_text = path.read_text(encoding="utf-8")
        base_path = path.parent
        value = None
    if config_text is not None:
        value = loader.loads(config_text)
    elif isinstance(value, dict):
        value = SageManifest.model_validate(value)
    if not isinstance(value, (SageManifest, ResolvedSageManifest)):
        raise TypeError("package must be a path, mapping, or manifest")
    value = value.model_copy(deep=True)
    if isinstance(value, SageManifest):
        agents = {}
        for name, agent in value.agents.items():
            if agent.instructions.path is not None:
                if base_path is None:
                    raise ValueError("base_path is required for instruction resources")
                root = Path(base_path).expanduser().resolve()
                resource = (root / agent.instructions.path).resolve()
                if root not in resource.parents or not resource.is_file():
                    raise ValueError(
                        "instruction resource must be a file inside base_path"
                    )
                agent = agent.model_copy(
                    update={
                        "instructions": agent.instructions.model_copy(
                            update={
                                "inline": resource.read_text(encoding="utf-8"),
                                "path": None,
                            }
                        )
                    }
                )
            agents[name] = agent
        value = value.model_copy(update={"agents": agents})
    if len(value.agents) != 1:
        raise ValueError("an Agent Package must define exactly one Agent")
    return value

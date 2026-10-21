"""Read persisted Desktop settings and upgrade removed built-in choices once."""

import json
from pathlib import Path

from .schemas import DesktopV2Settings


def read_desktop_settings(path: Path) -> DesktopV2Settings:
    if not path.exists():
        return DesktopV2Settings()
    raw = json.loads(path.read_text(encoding="utf-8"))
    selections = raw.setdefault("component_selections", {})
    configs = raw.setdefault("component_configs", {})
    changed = False
    compactor = "context.unit-compactor"
    if compactor in selections or compactor in configs:
        if selections.get(compactor, "sage.context.unit-compactor.reference") not in {
            "reference",
            "sage.context.unit-compactor.reference",
        } or configs.get(compactor):
            raise ValueError("cannot migrate a custom Desktop context compactor")
        selections.pop(compactor, None)
        configs.pop(compactor, None)
        changed = True

    log = "observability.log-sink"
    if log in selections or log in configs:
        if (
            "observability.provider" in selections
            or "observability.provider" in configs
        ):
            raise ValueError("conflicting saved Desktop observation providers")
        plugin = selections.pop(log, "sage.logging.filesystem")
        config = configs.pop(log, {})
        fields = {"min_level": "log_level", "format": "log_format"}
        if plugin in {"filesystem", "sage.logging.filesystem"}:
            options = {"log_stdout": False}
            fields.update(
                root="log_root",
                filename="log_filename",
                max_bytes="log_max_bytes",
                backup_count="log_backup_count",
            )
        elif plugin in {"stdout", "sage.logging.stdout"}:
            options = {"log_stdout": True, "log_root": None}
            fields["stream"] = "log_stream"
        elif plugin in {"noop", "sage.logging.noop"} and not config:
            options = {"log_stdout": False, "log_root": None}
        else:
            raise ValueError("cannot migrate a custom Desktop log sink")
        if set(config) - fields.keys():
            raise ValueError("cannot migrate unknown Desktop log configuration")
        options.update({fields[key]: value for key, value in config.items()})
        from .observability import normalize_observation_config

        selections["observability.provider"] = "sage.observability.local"
        configs["observability.provider"] = normalize_observation_config(
            "sage.observability.local", options
        )
        changed = True

    settings = DesktopV2Settings.model_validate(raw)
    if changed:
        temporary = path.with_suffix(".tmp")
        temporary.write_text(settings.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(path)
    return settings

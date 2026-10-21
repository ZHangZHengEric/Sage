
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Any

import json

import pytest

from app.v2.desktop.backend.observability import create_desktop_observability
from app.v2.desktop.backend.schemas import ComponentSelectionRequest
from app.v2.desktop.backend.service import DesktopV2Service
from app.v2.desktop.backend.settings_store import read_desktop_settings


@pytest.mark.parametrize(
    "plugin,config,expected",
    [
        (
            "sage.logging.filesystem",
            {"min_level": "warning", "filename": "desktop.log"},
            {
                "log_stdout": False,
                "log_level": "warning",
                "log_filename": "desktop.log",
            },
        ),
        (
            "sage.logging.stdout",
            {"stream": "stderr", "format": "text"},
            {
                "log_stdout": True,
                "log_root": None,
                "log_stream": "stderr",
                "log_format": "text",
            },
        ),
    ],
)
def test_saved_logging_settings_keep_their_behavior(tmp_path, plugin, config, expected):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "component_selections": {"observability.log-sink": plugin},
                "component_configs": {"observability.log-sink": config},
            }
        )
    )
    settings = read_desktop_settings(path)
    options = settings.component_configs["observability.provider"]
    assert {key: options[key] for key in expected} == expected
    assert read_desktop_settings(path) == settings


def test_unknown_saved_plugin_is_rejected_without_overwriting_settings(tmp_path):
    path = tmp_path / "settings.json"
    original = json.dumps(
        {"component_selections": {"observability.log-sink": "custom.logger"}}
    )
    path.write_text(original)
    with pytest.raises(ValueError, match="custom Desktop log sink"):
        read_desktop_settings(path)
    assert path.read_text() == original


@pytest.mark.asyncio
async def test_saved_desktop_settings_upgrade_preserves_disabled_logs(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    path = runtime / "settings.json"
    path.write_text(
        json.dumps(
            {
                "theme_mode": "dark",
                "component_selections": {
                    "observability.log-sink": "sage.logging.noop",
                    "context.unit-compactor": "sage.context.unit-compactor.reference",
                },
                "component_configs": {"context.unit-compactor": {}},
            }
        )
    )
    service = DesktopV2Service(tmp_path)
    try:
        await service.start()
        settings = await service.get_settings()
        assert settings.theme_mode == "dark"
        assert settings.component_selections == {
            "observability.provider": "sage.observability.local"
        }
        assert not cast("Any", service.observability).logs.outputs
        assert cast("Any", service.observability).diagnostics.available
        assert "observability.log-sink" not in path.read_text()
        assert "context.unit-compactor" not in path.read_text()
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_phoenix_selection_supplies_defaults_and_survives_restart(tmp_path):
    service = DesktopV2Service(tmp_path)
    if not service.extensions.get(
        "sage.observability.phoenix"
    ).descriptor.availability.available:
        pytest.skip("OpenTelemetry exporter is not installed")
    try:
        saved = await service.select_component(
            "observability.provider",
            ComponentSelectionRequest(plugin_id="sage.observability.phoenix"),
            "user",
        )
        assert saved["config"]["endpoint"] == "http://127.0.0.1:6006/v1/traces"
    finally:
        await service.close()
    provider = create_desktop_observability(tmp_path / "runtime")
    try:
        assert provider.plugin_id == "sage.observability.phoenix"
    finally:
        await provider.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "plugin,config",
    [
        ("sage.observability.phoenix", {"endpoint": "not-a-url"}),
        ("sage.observability.langfuse", {}),
        ("sage.observability.langfuse", {"base_url": "https://example.invalid"}),
    ],
)
async def test_invalid_observation_selection_does_not_change_settings(
    tmp_path, monkeypatch, plugin, config
):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    service = DesktopV2Service(tmp_path)
    if not service.extensions.get(plugin).descriptor.availability.available:
        pytest.skip("OpenTelemetry exporter is not installed")
    try:
        before = await service.get_settings()
        with pytest.raises(ValueError):
            await service.select_component(
                "observability.provider",
                ComponentSelectionRequest(plugin_id=plugin, config=config),
                "user",
            )
        assert await service.get_settings() == before
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_generic_settings_patch_cannot_persist_invalid_observation_config(
    tmp_path,
):
    service = DesktopV2Service(tmp_path)
    try:
        before = await service.get_settings()
        with pytest.raises(ValueError):
            await service.patch_settings(
                {
                    "component_selections": {
                        "observability.provider": "sage.observability.langfuse"
                    },
                    "component_configs": {
                        "observability.provider": {"base_url": "invalid"}
                    },
                }
            )
        assert await service.get_settings() == before
    finally:
        await service.close()

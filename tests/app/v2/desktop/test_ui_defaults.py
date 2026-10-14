import pytest
from app.v2.desktop.backend.service import DesktopV2Service
from app.v2.desktop.backend.schemas import DesktopV2Settings


@pytest.mark.asyncio
async def test_default_interactive_ui_persists_and_old_settings_default_off(tmp_path):
    assert DesktopV2Settings.model_validate({}).default_interactive_ui is False
    service = DesktopV2Service(tmp_path / "data")
    try:
        saved = await service.patch_settings(
            {
                "default_interactive_ui": True,
                "agent_workspace_path": str(tmp_path / "workspace"),
            }
        )
        assert saved.default_interactive_ui is True
        assert (await service.get_settings()).default_interactive_ui is True
    finally:
        await service.close()
    restored = DesktopV2Service(tmp_path / "data")
    try:
        assert (await restored.get_settings()).default_interactive_ui is True
        saved = await restored.patch_settings({"default_interactive_ui": False})
        assert saved.default_interactive_ui is False
    finally:
        await restored.close()

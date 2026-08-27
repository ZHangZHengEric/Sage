import importlib.util
import inspect
from pathlib import Path

from app.server import routers
from app.server.core.middleware import WHITELIST_API_PATHS
from common.models import system
from common.models.base import Base
from common.schemas import base as base_schemas


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_server_desktop_version_backend_is_removed():
    assert importlib.util.find_spec("app.server.routers.version") is None
    assert "/api/system/version/check" not in WHITELIST_API_PATHS
    assert "/api/system/version/latest" not in WHITELIST_API_PATHS

    router_registry = inspect.getsource(routers.register_routes)
    assert "version_router" not in router_registry

    for name in ("Version", "VersionArtifact", "VersionDao"):
        assert not hasattr(system, name)

    assert "version" not in Base.metadata.tables
    assert "version_artifact" not in Base.metadata.tables


def test_server_web_desktop_version_surfaces_are_removed():
    assert not (REPO_ROOT / "app/server/web/src/views/VersionList.vue").exists()
    assert not (REPO_ROOT / "app/server/web/src/views/Download.vue").exists()

    router_source = (REPO_ROOT / "app/server/web/src/router/index.js").read_text()
    sidebar_source = (REPO_ROOT / "app/server/web/src/views/Sidebar.vue").read_text()
    system_api_source = (REPO_ROOT / "app/server/web/src/api/system.js").read_text()
    login_source = (REPO_ROOT / "app/server/web/src/views/Login.vue").read_text()

    assert "VersionList" not in router_source
    assert "name: 'Download'" not in router_source
    assert "VersionList" not in sidebar_source
    assert "sidebar.downloadClient" not in sidebar_source
    assert "/api/system/version" not in system_api_source
    assert "zavixai.com/html/sage.html" not in login_source


def test_desktop_updates_directly_from_github_releases():
    desktop_system_router = (
        REPO_ROOT / "app/desktop/core/routers/system.py"
    ).read_text()
    desktop_settings = (
        REPO_ROOT / "app/desktop/ui/src/views/SystemSettings.vue"
    ).read_text()
    tauri_config = (REPO_ROOT / "app/desktop/tauri/tauri.conf.json").read_text()
    tauri_main = (REPO_ROOT / "app/desktop/tauri/src/main.rs").read_text()
    tauri_manifest = (REPO_ROOT / "app/desktop/tauri/Cargo.toml").read_text()
    desktop_package = (REPO_ROOT / "app/desktop/ui/package.json").read_text()
    capabilities = (
        REPO_ROOT / "app/desktop/tauri/capabilities/default.json"
    ).read_text()

    assert "/system/version/check" not in desktop_system_router
    assert "SAGE_UPDATE_URL" not in desktop_system_router
    assert (REPO_ROOT / "app/desktop/ui/src/stores/updater.js").exists()
    assert "useUpdaterStore" in desktop_settings
    assert (
        "https://github.com/ZHangZHengEric/Sage/releases/latest/download/latest.json"
        in tauri_config
    )
    assert "/api/system/version" not in tauri_config
    assert "tauri_plugin_updater" in tauri_main
    assert "tauri-plugin-updater" in tauri_manifest
    assert "@tauri-apps/plugin-updater" in desktop_package
    assert "updater:default" in capabilities

    for name in ("TauriPlatform", "TauriUpdateResponse"):
        assert not hasattr(base_schemas, name)


def test_current_docs_do_not_advertise_server_desktop_versions():
    current_docs = (
        REPO_ROOT / "docs/en/api/HTTP_API_PLATFORM.md",
        REPO_ROOT / "docs/en/api/HTTP_API_REFERENCE.md",
        REPO_ROOT / "docs/zh/api/HTTP_API_PLATFORM.md",
        REPO_ROOT / "docs/zh/api/HTTP_API_REFERENCE.md",
        REPO_ROOT / "docs/en/ENV_VARS.md",
        REPO_ROOT / "docs/zh/ENV_VARS.md",
    )

    for path in current_docs:
        source = path.read_text()
        assert "/api/system/version" not in source
        assert "SAGE_UPDATE_URL" not in source

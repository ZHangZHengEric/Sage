import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts/generate_tauri_updater_manifest.py"


def load_manifest_module():
    assert SCRIPT_PATH.exists()
    spec = importlib.util.spec_from_file_location("updater_manifest", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_manifest_maps_signed_github_release_assets(tmp_path):
    assets = {
        "Sage-1.2.3-aarch64.app.tar.gz": "mac arm bundle",
        "Sage-1.2.3-aarch64.app.tar.gz.sig": "mac-arm-signature\n",
        "Sage-1.2.3-x86_64.app.tar.gz": "mac intel bundle",
        "Sage-1.2.3-x86_64.app.tar.gz.sig": "mac-intel-signature\n",
        "Sage-1.2.3-x86_64-setup.exe": "windows installer",
        "Sage-1.2.3-x86_64-setup.exe.sig": "windows-signature\n",
    }
    for filename, content in assets.items():
        (tmp_path / filename).write_text(content)

    module = load_manifest_module()
    manifest = module.build_manifest(
        repo="ZHangZHengEric/Sage",
        tag="desktop-v1.2.3",
        version="1.2.3",
        assets_dir=tmp_path,
    )

    assert manifest == {
        "version": "1.2.3",
        "platforms": {
            "darwin-aarch64": {
                "url": "https://github.com/ZHangZHengEric/Sage/releases/download/desktop-v1.2.3/Sage-1.2.3-aarch64.app.tar.gz",
                "signature": "mac-arm-signature",
            },
            "darwin-x86_64": {
                "url": "https://github.com/ZHangZHengEric/Sage/releases/download/desktop-v1.2.3/Sage-1.2.3-x86_64.app.tar.gz",
                "signature": "mac-intel-signature",
            },
            "windows-x86_64": {
                "url": "https://github.com/ZHangZHengEric/Sage/releases/download/desktop-v1.2.3/Sage-1.2.3-x86_64-setup.exe",
                "signature": "windows-signature",
            },
        },
    }


def test_build_manifest_rejects_missing_signature(tmp_path):
    (tmp_path / "Sage-1.2.3-aarch64.app.tar.gz").write_text("bundle")

    module = load_manifest_module()

    try:
        module.build_manifest(
            repo="ZHangZHengEric/Sage",
            tag="desktop-v1.2.3",
            version="1.2.3",
            assets_dir=tmp_path,
        )
    except ValueError as exc:
        assert "signature" in str(exc).lower()
    else:
        raise AssertionError("missing updater signatures must fail the release")


def test_release_workflow_publishes_manifest_after_all_platform_builds():
    workflow = (REPO_ROOT / ".github/workflows/release-desktop.yml").read_text()
    windows_build = (
        REPO_ROOT / "app/desktop/scripts/build_windows.ps1"
    ).read_text()

    assert "publish-updater-manifest:" in workflow
    assert "needs: build-and-release" in workflow
    assert "scripts/generate_tauri_updater_manifest.py" in workflow
    assert "gh release upload \"$TAG\" latest.json --clobber" in workflow
    assert "*.exe.sig" in workflow
    assert "if (-not $env:TAURI_SIGNING_PRIVATE_KEY)" in windows_build
    assert "Remove-Item Env:TAURI_SKIP_SIGNATURE" in windows_build

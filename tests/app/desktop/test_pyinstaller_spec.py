from pathlib import Path


def test_desktop_pyinstaller_spec_collects_dynamic_model_imports():
    spec_path = (
        Path(__file__).resolve().parents[3]
        / "app"
        / "desktop"
        / "sage-desktop.spec"
    )

    spec_text = spec_path.read_text()

    assert 'collect_submodules("common.models")' in spec_text


def test_windows_build_uses_shared_pyinstaller_spec():
    script_path = (
        Path(__file__).resolve().parents[3]
        / "app"
        / "desktop"
        / "scripts"
        / "build_windows.ps1"
    )

    script_text = script_path.read_text()

    assert "sage-desktop.spec" in script_text
    assert (
        "& pyinstaller @pyiArgs" in script_text
        or "-m PyInstaller @pyiArgs" in script_text
    )

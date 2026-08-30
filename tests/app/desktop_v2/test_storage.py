from __future__ import annotations

from app.desktop_v2.backend.storage import prepare_desktop_v2_storage


def test_storage_creates_only_v2_owned_layout(tmp_path):
    paths = prepare_desktop_v2_storage(data_root=tmp_path / "sage")

    assert paths.runtime_root.is_dir()
    assert paths.skills_root.is_dir()
    assert paths.catalog_file == paths.runtime_root / "desktop-catalog.json"
    assert not (paths.runtime_root / "legacy").exists()

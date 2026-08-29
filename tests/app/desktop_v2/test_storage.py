from __future__ import annotations

import os

from app.desktop_v2.backend.storage import prepare_desktop_v2_storage


def test_storage_creates_only_v2_owned_layout(tmp_path, monkeypatch):
    monkeypatch.delenv("SAGE_DESKTOP_V2_DATA_DIR", raising=False)

    paths = prepare_desktop_v2_storage(data_root=tmp_path / "sage")

    assert paths.runtime_root.is_dir()
    assert paths.skills_root.is_dir()
    assert paths.catalog_file == paths.runtime_root / "desktop-catalog.json"
    assert os.environ["SAGE_DESKTOP_V2_DATA_DIR"] == str(paths.data_root)
    assert not (paths.runtime_root / "legacy").exists()

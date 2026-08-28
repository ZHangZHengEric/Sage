"""Create the isolated Desktop v2 data layout without importing another app."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DesktopV2StoragePaths:
    data_root: Path
    runtime_root: Path
    skills_root: Path
    catalog_file: Path


def prepare_desktop_v2_storage(
    *, data_root: Path | None = None
) -> DesktopV2StoragePaths:
    """Create only v2-owned directories and publish the selected data root."""

    configured_root = os.getenv("SAGE_DESKTOP_V2_DATA_DIR")
    root = (
        data_root
        or (Path(configured_root).expanduser() if configured_root else None)
        or Path.home() / "sage"
    ).resolve()
    runtime_root = root / "runtime"
    skills_root = root / "skills"
    runtime_root.mkdir(parents=True, exist_ok=True)
    skills_root.mkdir(parents=True, exist_ok=True)
    os.environ["SAGE_DESKTOP_V2_DATA_DIR"] = str(root)
    return DesktopV2StoragePaths(
        data_root=root,
        runtime_root=runtime_root,
        skills_root=skills_root,
        catalog_file=runtime_root / "desktop-catalog.json",
    )

"""Create the isolated Desktop v2 data layout without importing another app."""

from __future__ import annotations

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
    """Create only v2-owned directories from an explicit or fixed root."""

    root = (data_root or Path.home() / "sage").resolve()
    runtime_root = root / "runtime"
    skills_root = root / "skills"
    runtime_root.mkdir(parents=True, exist_ok=True)
    skills_root.mkdir(parents=True, exist_ok=True)
    return DesktopV2StoragePaths(
        data_root=root,
        runtime_root=runtime_root,
        skills_root=skills_root,
        catalog_file=runtime_root / "desktop-catalog.json",
    )

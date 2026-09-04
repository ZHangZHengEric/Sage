from pathlib import Path

import pytest

from app.server_v2.core.errors import ServerV2Error
from app.server_v2.domain.skills import (
    artifact_relative_path,
    reject_absolute_artifact_path,
    resolve_artifact_path,
    workspace_skill_path,
)


def test_artifact_relative_path_is_dimension_scoped():
    assert (
        artifact_relative_path(
            dimension="system",
            owner_user_id="",
            name="demo",
            version_id="sver_1",
        )
        == "system/demo/sver_1"
    )
    assert (
        artifact_relative_path(
            dimension="user",
            owner_user_id="user_1",
            name="demo",
            version_id="sver_1",
        )
        == "users/user_1/demo/sver_1"
    )


def test_mysql_path_helpers_reject_absolute_paths():
    with pytest.raises(ServerV2Error, match="relative"):
        reject_absolute_artifact_path("/var/sage/skills/system/demo/v1")
    with pytest.raises(ServerV2Error, match="escapes"):
        reject_absolute_artifact_path("../etc/passwd")


def test_absolute_path_is_joined_from_deployment_root(tmp_path: Path):
    relative = "system/demo/sver_1"
    resolved = resolve_artifact_path(tmp_path, relative)
    assert resolved == (tmp_path / "skills" / relative).resolve()
    assert resolved.is_relative_to((tmp_path / "skills").resolve())


def test_workspace_skill_stays_under_tenant_workspace(tmp_path: Path):
    path = workspace_skill_path(tmp_path, "user_1", "demo")
    assert path == tmp_path / "tenants" / "user_1" / "workspace" / "skills" / "demo"

import hashlib
from pathlib import Path

from sagents.v2.workspace import (
    BareWorkspaceInitializer,
    ClawWorkspaceInitializer,
)


def test_claw_workspace_initializer_seeds_new_v2_content_without_overwriting(
    tmp_path: Path,
):
    root = tmp_path / "agent_workspace"
    root.mkdir()
    (root / "SOUL.md").write_text("Custom soul", encoding="utf-8")

    created = ClawWorkspaceInitializer(language="zh").initialize(root)

    assert {"AGENT.md", "IDENTITY.md", "USER.md", "MEMORY.md"} <= set(created)
    assert {
        "data",
        "logs",
        "memory",
        "projects",
        "temp",
    } <= set(created)
    assert (root / "SOUL.md").read_text(encoding="utf-8") == "Custom soul"
    assert (
        (root / "AGENT.md")
        .read_text(encoding="utf-8")
        .startswith("# AGENT.md - 工作空间要求以及规范")
    )
    assert (
        (root / "IDENTITY.md")
        .read_text(encoding="utf-8")
        .startswith("# IDENTITY.md - 身份定义")
    )
    assert "## 用户背景\n- 暂无" in (root / "USER.md").read_text(encoding="utf-8")
    assert "## 核心信息\n- 暂无" in (root / "MEMORY.md").read_text(encoding="utf-8")


def test_claw_workspace_initializer_selects_v1_language_templates(tmp_path: Path):
    portuguese = tmp_path / "pt"
    fallback = tmp_path / "fallback"

    ClawWorkspaceInitializer(language="pt-BR").initialize(portuguese)
    ClawWorkspaceInitializer(language="ja").initialize(fallback)

    assert (
        (portuguese / "AGENT.md")
        .read_text(encoding="utf-8")
        .startswith("# AGENT.md - Especificação do Espaço de Trabalho")
    )
    assert (
        (fallback / "AGENT.md")
        .read_text(encoding="utf-8")
        .startswith("# AGENT.md - Workspace Specification")
    )


def test_claw_workspace_initializer_matches_desktop_v1_1_8_chinese_snapshot(
    tmp_path: Path,
):
    root = tmp_path / "agent_workspace"
    expected = {
        "AGENT.md": "7b74bed51aae2f6253b6f57225ebdd1733fbd9308bed9c6f1baafac456220820",
        "IDENTITY.md": "c023d60a2609c49eac2a75f5fd4b16612cf79f8e86ecf82eb48b58cc71522bc1",
        "SOUL.md": "6051b23fcfe61266567481670bf59f0d913493e00dc9fbd523cd5e8305af3872",
        "USER.md": "988706cd3d6ab6c4d09fa348b1f1a83b2c0a8a75fda03ecf5c1debc0113d7266",
        "MEMORY.md": "d6f3bd0660fd752879972445fabbed0bd8cfb3307e7b81f5e70f0fb72b91eb98",
    }

    ClawWorkspaceInitializer(language="zh").initialize(root)

    actual = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in expected
    }
    assert actual == expected


def test_claw_workspace_initializer_resolves_system_language(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("LANGUAGE", "zh-CN")
    root = tmp_path / "agent_workspace"

    ClawWorkspaceInitializer(language="system").initialize(root)

    assert (
        (root / "AGENT.md")
        .read_text(encoding="utf-8")
        .startswith("# AGENT.md - 工作空间要求以及规范")
    )


def test_claw_workspace_initializer_upgrades_only_untouched_v2_placeholders(
    tmp_path: Path,
):
    root = tmp_path / "agent_workspace"
    root.mkdir()
    (root / "IDENTITY.md").write_text(
        "# Identity\n\nDescribe the Agent's role, responsibilities, and stable identity here.\n",
        encoding="utf-8",
    )
    (root / "USER.md").write_text("Custom user", encoding="utf-8")

    changed = ClawWorkspaceInitializer(language="zh").initialize(root)

    assert "IDENTITY.md" in changed
    assert (
        (root / "IDENTITY.md")
        .read_text(encoding="utf-8")
        .startswith("# IDENTITY.md - 身份定义")
    )
    assert (root / "USER.md").read_text(encoding="utf-8") == "Custom user"


def test_claw_workspace_initializer_relocalizes_only_managed_v1_seed(
    tmp_path: Path,
):
    root = tmp_path / "agent_workspace"
    ClawWorkspaceInitializer(language="en").initialize(root)
    (root / "SOUL.md").write_text("Custom soul", encoding="utf-8")

    changed = ClawWorkspaceInitializer(language="zh").initialize(root)

    assert {"AGENT.md", "IDENTITY.md", "USER.md", "MEMORY.md"} <= set(changed)
    assert (
        (root / "AGENT.md")
        .read_text(encoding="utf-8")
        .startswith("# AGENT.md - 工作空间要求以及规范")
    )
    assert (root / "SOUL.md").read_text(encoding="utf-8") == "Custom soul"


def test_bare_workspace_initializer_only_creates_the_root(tmp_path: Path):
    root = tmp_path / "agent_workspace"

    assert BareWorkspaceInitializer().initialize(root) == ()
    assert root.is_dir()
    assert list(root.iterdir()) == []

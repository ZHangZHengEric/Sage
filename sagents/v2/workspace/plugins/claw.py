"""Seed the V1-compatible identity, memory, and Claw working layout."""

from __future__ import annotations

import hashlib
from pathlib import Path

from sagents.v2.workspace.claw_templates import claw_workspace_documents


_INITIAL_V2_PLACEHOLDERS = {
    "AGENT.md": """# Agent Workspace

This is the Agent's persistent working directory.

- Keep durable working instructions in this file.
- Put task outputs in `projects/` or another clearly named folder.
- Use `temp/` only for disposable intermediate files.
""",
    "IDENTITY.md": """# Identity

Describe the Agent's role, responsibilities, and stable identity here.
""",
    "SOUL.md": """# Soul

Describe the Agent's enduring principles and working style here.
""",
    "USER.md": """# User

Record durable user preferences that are useful across conversations here.
""",
    "MEMORY.md": """# Memory

Keep a concise index of durable workspace knowledge here.
""",
}


_MANAGED_CLAW_TEMPLATE_DIGESTS = {
    "AGENT.md": {
        "7b74bed51aae2f6253b6f57225ebdd1733fbd9308bed9c6f1baafac456220820",
        "d65dc29ccb72f44cbab321276d09bcab39a8eb7e800d4ff1a8df32971354af9b",
        "1a700ff3b4b0d95e2ab441df05db0b79a5c9fc76a9e1fde985c453c07bad8914",
    },
    "IDENTITY.md": {
        "c023d60a2609c49eac2a75f5fd4b16612cf79f8e86ecf82eb48b58cc71522bc1",
        "8e45749f855ae8eeb7ad00aa12445bd613c1ace67ae6c5e6dca09d9939fc587d",
        "ef6c931b41c83ea2b6c6d5833185d7f6135cea372533a62c770ff3cde3f4f630",
        "4bf1ce28a064d30ae94a5dc4b8af382355aada10e0bc0ee0833d078a487492b3",
        "9ad62e3bbdb10ce15ae62bfcaac18be7437e90e65323c5265372f8e27d8da53f",
        "8c16859ae128ba0ead6720fe303735e9d76f02b1876adb280fb8b68c6692f08f",
    },
    "SOUL.md": {
        "6051b23fcfe61266567481670bf59f0d913493e00dc9fbd523cd5e8305af3872",
        "08ce1ab4425d65350373cb4404d8bbedb9dc7cb4d72795986cea25bdb22b6b85",
        "9f3af348b44c02e25d8a685969defbe69481736eb96889ffc04fdfab368fe9d1",
    },
    "USER.md": {
        "988706cd3d6ab6c4d09fa348b1f1a83b2c0a8a75fda03ecf5c1debc0113d7266",
        "77f86a0f020875b6d29a975c45efe6d340fb4cec8039c5017bde12482bfaf6f1",
        "dc8232066b455eb925d78d8228a8dcd156893ee364f292e27d3cb7208994c5ee",
    },
    "MEMORY.md": {
        "d6f3bd0660fd752879972445fabbed0bd8cfb3307e7b81f5e70f0fb72b91eb98",
        "8df7aed356d03316d121d6b9a6909faea524d5622d6fe9778eb52b1f44b81521",
        "97c28b04a9d05f144ed7afecdf5353e7cf6ea9f8db1a8d36b2910b3309532b50",
    },
}


def _is_replaceable_v2_seed(path: Path, filename: str, replacement: str) -> bool:
    if not path.is_file():
        return False
    try:
        content = path.read_bytes()
    except OSError:
        return False
    if content == replacement.encode("utf-8"):
        return False
    try:
        if content.decode("utf-8") == _INITIAL_V2_PLACEHOLDERS[filename]:
            return True
    except UnicodeError:
        return False
    return (
        hashlib.sha256(content).hexdigest() in _MANAGED_CLAW_TEMPLATE_DIGESTS[filename]
    )


class ClawWorkspaceInitializer:
    _directories = (
        "data",
        "logs",
        "memory",
        "projects",
        "temp",
    )

    def __init__(self, *, language: str = "en") -> None:
        self.language = language

    def initialize(self, root: Path) -> tuple[str, ...]:
        root.mkdir(parents=True, exist_ok=True)
        created: list[str] = []
        for name in self._directories:
            path = root / name
            if path.exists():
                continue
            path.mkdir()
            created.append(name)
        for name, content in claw_workspace_documents(self.language).items():
            path = root / name
            if path.exists():
                if _is_replaceable_v2_seed(path, name, content):
                    path.write_text(content, encoding="utf-8")
                    created.append(name)
                continue
            path.write_text(content, encoding="utf-8")
            created.append(name)
        return tuple(created)

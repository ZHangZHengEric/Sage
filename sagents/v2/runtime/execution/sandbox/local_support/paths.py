"""Workspace-owned directories and native process/file-tool path semantics."""

from __future__ import annotations

import sys
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LocalSandboxPaths:
    root: Path
    workspace_root: str
    platform: str = sys.platform

    @property
    def temporary(self) -> Path:
        # Keep the existing scratch location; no migration of user files.
        return self.root / ".sage-sandbox-tmp"

    @property
    def home(self) -> Path:
        return self.root / ".sage-sandbox-home"

    @property
    def environment(self) -> dict[str, str]:
        home = "/home/agent" if self.platform == "linux" else str(self.home)
        temporary = "/tmp" if self.platform == "linux" else str(self.temporary)
        return {
            "HOME": home,
            "TMPDIR": temporary,
            "TMP": temporary,
            "TEMP": temporary,
            "XDG_CACHE_HOME": f"{home}/.cache",
            "XDG_CONFIG_HOME": f"{home}/.config",
            "XDG_DATA_HOME": f"{home}/.local/share",
            "XDG_STATE_HOME": f"{home}/.local/state",
        }

    @property
    def directories(self) -> tuple[Path, ...]:
        return (
            self.temporary,
            self.home,
            self.home / ".cache",
            self.home / ".config",
            self.home / ".local",
            self.home / ".local/share",
            self.home / ".local/state",
        )

    def host_path(self, value: str) -> Path:
        if value == "~" or value.startswith("~/"):
            value = self.environment["HOME"] + value[1:]
        for name, target in self.environment.items():
            for prefix in (f"${name}", "${" + name + "}"):
                if value == prefix or value.startswith(prefix + "/"):
                    value = target + value[len(prefix) :]
        value = os.path.normpath(value)
        # An explicit in-workspace host path remains usable by host integrations,
        # including when its parent happens to be the host's /tmp.
        candidate = Path(value)
        if candidate.is_absolute() and (
            candidate == self.root or self.root in candidate.parents
        ):
            return candidate
        mappings = [(self.workspace_root, self.root)]
        if self.platform == "linux":
            mappings = [
                ("/tmp", self.temporary),
                ("/var/tmp", self.temporary),
                ("/dev/shm", self.temporary),
                ("/home/agent", self.home),
                *mappings,
            ]
        for alias, host in mappings:
            if value == alias or value.startswith(alias.rstrip("/") + "/"):
                return host / value[len(alias) :].lstrip("/")
        candidate = Path(value)
        return candidate if candidate.is_absolute() else self.root / candidate

    def wire_path(self, candidate: Path) -> str:
        if self.platform != "linux":
            return str(candidate)
        if self.platform == "linux":
            for host, alias in ((self.temporary, "/tmp"), (self.home, "/home/agent")):
                if candidate == host or host in candidate.parents:
                    relative = candidate.relative_to(host).as_posix()
                    return alias + (f"/{relative}" if relative != "." else "")
        relative = candidate.relative_to(self.root).as_posix()
        return self.workspace_root.rstrip("/") + (
            f"/{relative}" if relative != "." else ""
        )

    def describe(self) -> dict:
        return {
            "provider": "local-workspace",
            "os": self.platform,
            "isolation": "bubblewrap" if self.platform == "linux" else "macOS Seatbelt",
            "workspace": self.workspace_root
            if self.platform == "linux"
            else str(self.root),
            "file_tool_workspace_alias": self.workspace_root,
            "environment": self.environment,
            "directory_scope": "workspace-owned; included in sandbox disk quota",
            "path_rules": (
                "Relative paths use the workspace, not HOME. File tools accept ~/, $HOME/, "
                "${TMPDIR}/ and the listed XDG variables using sandbox values. Shell uses normal "
                "shell expansion. System executables/libraries are read-only; this is not a VM. "
                + (
                    "/tmp and /var/tmp refer to sandbox temporary storage."
                    if self.platform == "linux"
                    else "There is no virtual absolute-path remapping in native macOS Shell. "
                    "Use the supplied TMPDIR/HOME paths; host /tmp and /private/tmp are not sandbox aliases."
                )
            ),
        }

"""Explicit, frozen host lint environment for isolated RSI target workspaces."""

from pathlib import Path
import hashlib
import os
import shutil

from pydantic import field_validator
from sagents.v2.contracts.common import StrictModel


class RsiLintEnvironment(StrictModel):
    root: str
    node: str

    @field_validator("root", "node")
    @classmethod
    def absolute(cls, value):
        if not Path(value).is_absolute() or Path(value) == Path("/"):
            raise ValueError("Lint paths must be absolute, non-root paths")
        return str(Path(value).resolve())

    def fingerprint(self):
        root, node = Path(self.root), Path(self.node)
        for path in (
            root / "bin/eslint",
            root / "eslint.config.mjs",
            root / "package-lock.json",
            root / "node_modules/eslint/package.json",
            node,
        ):
            if not path.is_file():
                raise ValueError(f"Lint environment is not installed: {path}")
        if not os.access(root / "bin/eslint", os.X_OK) or not os.access(node, os.X_OK):
            raise ValueError("Lint entry point and Node must be executable")
        for path in root.rglob("*"):
            if path.is_symlink() and not path.resolve().is_relative_to(root):
                raise ValueError("Lint environment contains an external file link")
        digest = hashlib.sha256()
        for path in [node, *sorted(p for p in root.rglob("*") if p.is_file())]:
            if path != node and not path.resolve().is_relative_to(root):
                raise ValueError("Lint environment contains an external file link")
            digest.update(str(path).encode())
            digest.update(path.read_bytes())
        return digest.hexdigest()


def lint_binding(environment, *, target, tools):
    """Internal Eval/Tuner roles never gain a process grant from this option."""
    if environment is None or not target or "read_lints" not in tools:
        return {}, {"enabled": False}
    root, node = Path(environment.root), Path(environment.node)
    return {
        "command_path": os.pathsep.join(
            [str(root / "bin"), str(node.parent), "/usr/bin", "/bin"]
        ),
        "read_paths": [str(root), str(node.parent.parent)],
    }, {
        "enabled": True,
        "allow_shell": True,
        "allowed_executables": ["bash"],
        "max_processes": 1,
        "max_wall_time_seconds": 30,
        "max_output_bytes": 1048576,
        "allow_background_jobs": False,
    }


def default_lint_environment():
    """Resolve Sage's standard installed runtime, never a dataset-specific path."""
    from sagents.v2.tool.official import quality

    root = Path(quality.__file__).with_name("lint")
    node = shutil.which("node")
    if not node:
        raise ValueError("read_lints requires Node.js in the host PATH")
    environment = RsiLintEnvironment(root=str(root), node=node)
    try:
        environment.fingerprint()
    except ValueError as error:
        raise ValueError(
            "Sage lint runtime is not ready. Install its locked dependencies with "
            f"npm ci --prefix {root} --ignore-scripts --no-audit --no-fund"
        ) from error
    return environment


def resolve_lint_environment(explicit, tools):
    return (
        explicit
        if explicit is not None or "read_lints" not in tools
        else default_lint_environment()
    )

"""Execute Cube bridge scripts against isolated directories, without a Cube VM."""

from __future__ import annotations

import base64
import json
from pathlib import Path
import shlex
import subprocess
import sys
from types import SimpleNamespace


class FakeCubeClient:
    def __init__(self, root: Path):
        self.root = root
        self.created = []

    def create_sandbox(self, name, **options):
        root = self.root / name
        root.mkdir(parents=True, exist_ok=True)
        sandbox = FakeSandbox(root, f"cube_{len(self.created)}")
        self.created.append(sandbox)
        return sandbox


class FakeSandbox:
    def __init__(self, root, sandbox_id):
        self.root, self.sandbox_id = root, sandbox_id
        self.commands = self
        self.killed = False

    def kill(self):
        self.killed = True

    def run(self, command, *, cwd, timeout, **kwargs):
        parts = shlex.split(command)
        script = parts[parts.index("-c") + 1]
        payload = json.loads(base64.b64decode(parts[-1]))
        for key in ("root", "cwd"):
            if payload.get(key, "").startswith("/workspace"):
                payload[key] = str(self.root) + payload[key][len("/workspace") :]
        encoded = base64.b64encode(json.dumps(payload).encode()).decode()
        result = subprocess.run(
            [sys.executable, "-I", "-c", script, encoded],
            cwd="/",
            timeout=timeout,
            capture_output=True,
            text=True,
            check=False,
        )
        return SimpleNamespace(
            stdout=result.stdout, stderr=result.stderr, exit_code=result.returncode
        )

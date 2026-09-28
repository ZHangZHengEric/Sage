"""Keep the architecture gate effective for normal and hidden import edges."""
from pathlib import Path
import importlib.util

import pytest


spec = importlib.util.spec_from_file_location(
    "check_architecture", Path(__file__).resolve().parents[2] / "scripts/checks/check_architecture.py"
)
architecture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(architecture)


@pytest.mark.parametrize("source, destination, code", [
    ("sagents/v2/example.py", "sagents/v1/example.py", "from sagents.v1 import example"),
    ("sagents/v2/example.py", "sagents/v1/example.py", "from ..v1 import example"),
    ("sagents/v2/example.py", "sagents/v1/example.py", "importlib.import_module('sagents.v1.example')"),
    ("app/v2/server/example.py", "common/example.py", "from app.v1.common import example"),
    ("app/v2/desktop/backend/example.py", "common/example.py", "import common.example"),
])
def test_gate_rejects_legacy_dependencies(tmp_path, monkeypatch, source, destination, code):
    for name, content in [(source, code), (destination, "")]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    monkeypatch.setattr(architecture, "ROOT", tmp_path)
    monkeypatch.setattr(architecture.subprocess, "check_output", lambda *a, **kw: source.encode())
    count, errors = architecture.check()
    assert count == 1
    assert any("dependency" in error for error in errors), errors


def test_gate_accepts_version_owned_relative_import(tmp_path, monkeypatch):
    source = "sagents/v2/example.py"
    (tmp_path / "sagents/v2").mkdir(parents=True)
    (tmp_path / source).write_text("from . import helper")
    (tmp_path / "sagents/v2/helper.py").write_text("")
    monkeypatch.setattr(architecture, "ROOT", tmp_path)
    monkeypatch.setattr(architecture.subprocess, "check_output", lambda *a, **kw: source.encode())
    assert architecture.check() == (1, [])

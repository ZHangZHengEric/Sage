"""Exercise the documented no-file quick start without a paid model call."""
from __future__ import annotations

import pytest

from examples import sagents_v2_quickstart as example
from sagents.v2 import SAgentBuilder
from sagents.v2.model.contracts import ModelEventKind, ModelResponse, ModelStreamEvent
from sagents.v2.testing.plugins.scripted_model import ScriptedModelProvider, ScriptedModelStep


@pytest.mark.asyncio
async def test_yaml_string_quickstart_completes_without_manifest_file(tmp_path, monkeypatch, capsys):
    provider = ScriptedModelProvider((ScriptedModelStep(events=(ModelStreamEvent(
        kind=ModelEventKind.COMPLETED,
        response=ModelResponse(response_id="hello", text="Hello!", finish_reason="stop"),
    ),)),))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(example, "SAgentBuilder", lambda: SAgentBuilder().with_model_provider(provider))
    await example.main()
    output = capsys.readouterr().out
    assert "Hello!" in output
    assert "COMPLETED" in output
    assert len(provider.requests) == 1
    assert not list(tmp_path.rglob("sage.yaml"))
    assert (tmp_path / "runtime").is_dir()

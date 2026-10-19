"""Exercise the documented no-file quick start without a paid model call."""
from __future__ import annotations

import pytest

from examples import sagents_v2_quickstart as example
from sagents.v2.model.contracts import ModelEventKind, ModelResponse, ModelStreamEvent
from sagents.v2.testing.plugins.scripted_model import ScriptedModelProvider, ScriptedModelStep


@pytest.mark.asyncio
async def test_yaml_string_quickstart_completes_without_manifest_file(tmp_path, monkeypatch, capsys):
    provider = ScriptedModelProvider((ScriptedModelStep(events=(ModelStreamEvent(
        kind=ModelEventKind.COMPLETED,
        response=ModelResponse(response_id="hello", text="Hello!", finish_reason="stop"),
    ),)), ScriptedModelStep(events=(ModelStreamEvent(
        kind=ModelEventKind.COMPLETED,
        response=ModelResponse(response_id="judge", text='{"decision":"completed"}', finish_reason="stop"),
    ),)),))
    monkeypatch.chdir(tmp_path)
    from examples.sagents_v2_host.registrations import provided
    from sagents.v2.composition.defaults import default_runtime
    from sagents.v2.package.manifest.runtime import CapabilitySelection
    registration = provided("test.quickstart.model", lambda context, deps: provider, "model.provider")
    runtime = default_runtime("runtime")
    runtime = runtime.model_copy(update={"capabilities": {
        **runtime.capabilities, "model.provider": CapabilitySelection(plugin="test.quickstart.model"),
    }})
    await example.main(runtime=runtime, registrations=(registration,))
    output = capsys.readouterr().out
    assert "Hello!" in output
    assert "COMPLETED" in output
    assert len(provider.requests) == 2  # reply and the standard completion judge
    assert not list(tmp_path.rglob("sage.yaml"))
    assert (tmp_path / "runtime").is_dir()

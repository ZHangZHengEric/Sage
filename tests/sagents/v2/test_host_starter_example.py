"""Keep the documented host entrypoints runnable without credentials or network."""

from argparse import Namespace
import json
from pathlib import Path

import pytest

from examples.sagents_v2_host import __main__ as starter
from examples.sagents_v2_host.bootstrap import HostSettings, build_application


def args(tmp_path, *, inspect=False):
    return Namespace(
        manifest=Path(starter.__file__).with_name("sage.yaml"),
        runtime_root=tmp_path,
        log_level="info",
        environment=None,
        offline=True,
        inspect=inspect,
        prompt="Hello",
        idempotency_key="example-test",
    )


@pytest.mark.asyncio
async def test_documented_inspection_does_not_execute_model(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    model = starter.offline_model()
    monkeypatch.setattr(starter, "offline_model", lambda: model)
    await starter.main(args(tmp_path, inspect=True))
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report["plan"]["package_id"] == "example.host"
    assert report["plan"]["composition_hash"].startswith("sha256:")
    assert report["readiness"] is not None
    assert any(
        p["capability"] == "model.provider" and p["source"] == "host"
        for p in report["plan"]["providers"]
    )
    assert model.requests == []


@pytest.mark.asyncio
async def test_documented_offline_run_emits_events_and_model_diagnostics(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    await starter.main(args(tmp_path))
    output = capsys.readouterr()
    records = [json.loads(line) for line in output.out.splitlines()]
    assert records[-1] == {"state": "completed"}
    assert any(row.get("type") == "run.completed" for row in records)
    assert "model.request.started" in output.err
    evidence = list((tmp_path / "sessions").glob("*/runs/*/llm_requests/*.json"))
    assert len(evidence) == 1
    assert (evidence[0].parent.parent / "run.json").exists()


@pytest.mark.asyncio
async def test_bootstrap_rejects_missing_environment_instead_of_silent_fallback(
    tmp_path,
):
    from sagents.v2.contracts.errors import SageV2Error

    with pytest.raises(SageV2Error) as caught:
        await build_application(
            HostSettings(
                Path(starter.__file__).with_name("sage.yaml"),
                tmp_path,
                environment="missing",
            ),
            model=starter.offline_model(),
        )
    assert caught.value.info.code == "manifest.environment_not_found"

"""Keep the offline onboarding example aligned with the optimizer contract."""
import importlib
import json
import os
import runpy
import socket
import subprocess

import pytest


@pytest.mark.parametrize("repair_once", [False, True])
def test_package_optimizer_example_offline(monkeypatch, capsys, repair_once):
    for name in tuple(os.environ):
        monkeypatch.delenv(name)
    attempted = []

    def deny(*args, **kwargs):
        attempted.append(True)
        raise AssertionError("The scripted onboarding example must remain offline")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)
    monkeypatch.setattr(subprocess, "Popen", deny)
    monkeypatch.setattr(os, "system", deny)
    if hasattr(os, "posix_spawn"):
        monkeypatch.setattr(os, "posix_spawn", deny)

    optimizer = importlib.import_module("sagents.v2.optimization.experiments")
    validate = optimizer.validate_experiment
    calls = []

    def validate_with_one_repair(*args, **kwargs):
        calls.append(args[0])
        if repair_once and len(calls) == 1:
            raise ValueError("Exercise the example's same-round repair response")
        return validate(*args, **kwargs)

    monkeypatch.setattr(optimizer, "validate_experiment", validate_with_one_repair)
    runpy.run_module("examples.v2.package_optimizer", run_name="__main__")
    result = json.loads(capsys.readouterr().out)
    assert result["baseline_score"] == 0.4
    assert result["selected_score"] == 0.8
    assert result["goal_verified"] is False
    assert "final_passed" not in result
    assert result["original_hash"] != result["candidate_hash"]
    assert [r["round"] for r in result["rounds"]] == [1, 2, 3]
    assert [r["accepted"] for r in result["rounds"]] == [True, False, True]
    assert all(r["reason"] for r in result["rounds"])
    assert not attempted
    if repair_once:
        assert len(calls) == 4
        assert calls[0].training_case_ids == calls[1].training_case_ids
        assert calls[0].parent_hash == calls[1].parent_hash

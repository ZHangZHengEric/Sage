"""Exercise the packaged Node entry point without downloading dependencies."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

RUNNER = Path(__file__).resolve().parents[4] / "deploy/images/frontend-test/runner.cjs"


@pytest.fixture
def runner(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required to exercise runner.cjs")
    root = tmp_path / "tenants/20005/agent/workspace"
    tests = root / ".sage-tests"
    tests.mkdir(parents=True)
    (root / "project").mkdir()
    # Dependency loading is covered by image acceptance; isolate path handling.
    modules = tmp_path / "modules/jsdom"
    modules.mkdir(parents=True)
    (modules / "index.js").write_text("exports.JSDOM = class {};\n")
    script = tests / "dom.cjs"
    script.write_text("module.exports = async ({assert,workspace,artifacts,require}) => {"
                      "assert.equal(workspace,process.env.SAGE_WORKSPACE_ROOT || process.cwd().replace(/\\/\\.sage-tests$/, ''));"
                      "require('node:fs').writeFileSync(artifacts+'/proof.txt','ok');};")
    def run(value=".sage-tests/dom.cjs", *, cwd=None, configured=True, mode="jsdom"):
        env = {**os.environ, "NODE_PATH": str(modules.parent)}
        env.pop("SAGE_WORKSPACE_ROOT", None)
        if configured:
            env["SAGE_WORKSPACE_ROOT"] = str(root)
        return subprocess.run([node, str(RUNNER), mode, str(value)], cwd=cwd or root,
                              env=env, text=True, capture_output=True, timeout=10)
    return root, script, run


@pytest.mark.parametrize("absolute", [False, True])
def test_tenant_root_is_independent_of_process_workdir(runner, absolute):
    root, script, run = runner
    result = run(script if absolute else ".sage-tests/dom.cjs", cwd=root / "project")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "passed"
    assert report["workspace"] == str(root)
    artifacts = Path(report["artifacts"])
    assert artifacts.is_relative_to(root / ".sage-tests/artifacts")
    assert (artifacts / "proof.txt").read_text() == "ok"
    assert json.loads((artifacts / "report.json").read_text()) == report


def test_standalone_caller_uses_workspace_cwd(runner):
    _, _, run = runner
    assert run(configured=False).returncode == 0


@pytest.mark.parametrize("escape", ["outside", "script_symlink", "test_directory", "artifact_directory"])
def test_outside_and_symlink_paths_fail_before_test_execution(runner, tmp_path, escape):
    root, script, run = runner
    outside = tmp_path / "workspace-other"
    outside.mkdir()
    target = outside / "bad.cjs"
    target.write_text("throw Error('must not run');")
    value = target
    if escape == "script_symlink":
        value = root / ".sage-tests/link.cjs"
        value.symlink_to(target)
    elif escape == "test_directory":
        script.unlink()
        script.parent.rmdir()
        script.parent.symlink_to(outside, target_is_directory=True)
        value = ".sage-tests/bad.cjs"
    elif escape == "artifact_directory":
        (script.parent / "artifacts").symlink_to(outside, target_is_directory=True)
        value = script
    result = run(value)
    assert result.returncode != 0
    assert json.loads(result.stderr)["status"] == "failed"
    assert not (outside / "report.json").exists()


def test_assertion_failure_retains_report_and_nonzero_exit(runner):
    root, script, run = runner
    script.write_text("module.exports = async ({assert}) => assert.fail('DOM mismatch');")
    result = run()
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["status"] == "failed" and "DOM mismatch" in report["error"]
    assert Path(report["artifacts"]).is_relative_to(root)

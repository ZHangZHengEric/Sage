from types import SimpleNamespace

from sagents.v2.optimization.contracts import OptimizationObservation
from sagents.v2.optimization.workspace_evidence import attest_files, local_workspace
from evaluation_datasets.web_design.preflight import fixture_observation


def test_only_host_selected_local_binding_maps_execution_directory(tmp_path):
    config = SimpleNamespace(runtime=SimpleNamespace(capabilities={'execution.binding':SimpleNamespace(
        plugin='sage.execution.binding.local-workspace',config={'workspace':str(tmp_path/'work')})}))
    assert local_workspace(config) == tmp_path/'work'
    config.runtime.capabilities['execution.binding'].plugin = 'other-execution-provider'
    assert local_workspace(config) is None


def test_snapshot_uses_bound_work_root_and_cannot_read_symlinks_or_parent_paths(tmp_path):
    root = tmp_path/'work'
    root.mkdir()
    (root/'index.html').write_text('Actual output')
    (tmp_path/'index.html').write_text('Wrong package root')
    observation = OptimizationObservation.model_validate(fixture_observation({'index.html':'Declared output'}))
    observation = observation.model_copy(update={'evidence':{**observation.evidence,'run_id':'fixture'}})
    snapshot = attest_files(observation,root)
    assert snapshot['workspace_files']['files']['index.html']['content'] == 'Actual output'
    (root/'index.html').unlink()
    (root/'index.html').symlink_to(tmp_path/'index.html')
    rejected = attest_files(observation,root)['workspace_files']
    assert rejected['complete'] is False and rejected['files'] == {}
    observation.evidence['final_items'][0]['data']['arguments']['file_path'] = '../index.html'
    assert attest_files(observation,root)['workspace_files']['complete'] is False


def test_pending_native_execution_never_claims_terminal_file_authority(tmp_path):
    observation = OptimizationObservation(state='suspended',evidence={'run_id':'pending'})
    assert 'workspace_files' not in attest_files(observation,tmp_path)


def test_platform_without_secure_open_preserves_receipts_without_snapshot(tmp_path, monkeypatch):
    import os

    observation = OptimizationObservation.model_validate(fixture_observation({'index.html':'Declared output'}))
    monkeypatch.setattr(os, 'supports_dir_fd', set())
    snapshot = attest_files(observation, tmp_path)['workspace_files']
    assert snapshot['complete'] is False
    assert snapshot['files'] == {}
    assert snapshot['errors'] == ['OSError']

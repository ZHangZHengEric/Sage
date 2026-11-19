import importlib.util
import json
from pathlib import Path
from unittest.mock import call, patch

import pytest

spec = importlib.util.spec_from_file_location('release_v2', Path(__file__).resolve().parents[2] / 'deploy/release_v2.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def test_replace_refuses_missing_or_ambiguous_upstream():
    for text in ('reverse_proxy localhost:1234', ' reverse_proxy localhost:32004\n reverse_proxy 127.0.0.1:32004\n'):
        with pytest.raises(ValueError):
            release.replace_port(text, 32004, 32006)


def test_replace_preserves_other_products():
    before = ' reverse_proxy localhost:32004\n reverse_proxy localhost:32002\n'
    assert release.replace_port(before, 32004, 32006) == ' reverse_proxy 127.0.0.1:32006\n reverse_proxy localhost:32002\n'


def test_failed_public_check_restores_config(tmp_path):
    caddy = tmp_path / 'Caddyfile'
    original = ' reverse_proxy localhost:32000\n reverse_proxy localhost:32001\n'
    caddy.write_text(original)
    manifest = {'release': 'new', 'previous_release': 'old', 'api_port': 32004,
                'web_port': 32005, 'observe_seconds': 0,
                'routes': [{'file': str(caddy), 'old_api_port': 32000, 'old_web_port': 32001}]}
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    with patch.object(release, 'local_verify'), patch.object(release, 'run') as run, \
            patch.object(release, 'scheduler_release') as scheduler, \
            patch.object(release, 'public_verify', side_effect=[RuntimeError('502'), None]):
        with pytest.raises(RuntimeError, match='502'):
            release.cutover(manifest, tmp_path)
    assert caddy.read_text() == original
    assert run.call_args_list.count(call('systemctl', 'reload', 'caddy')) == 2
    assert scheduler.call_args_list == [
        call(manifest, tmp_path, 'check'),
        call(manifest, tmp_path, 'change'),
        call(manifest, tmp_path, 'change', rollback=True),
    ]


def test_stale_rollback_does_not_overwrite_new_release(tmp_path):
    caddy = tmp_path / 'Caddyfile'
    caddy.write_text('new deployment')
    with pytest.raises(RuntimeError, match='changed since cutover'):
        release.restore({}, {str(caddy): {'before': 'old', 'after': 'candidate'}}, tmp_path)
    assert caddy.read_text() == 'new deployment'


def test_web_html_cannot_pass_readiness():
    with patch.object(release, 'request', return_value=b'<html>SPA</html>'):
        with pytest.raises(ValueError):
            release.verify('http://api', 'http://web')


def test_verify_reads_current_manifest_after_shared_lock(tmp_path, monkeypatch):
    manifest = tmp_path / 'current.json'
    manifest.write_text('{"release": "previous"}')

    def wait_for_release(_lock, mode):
        assert mode == release.fcntl.LOCK_SH
        manifest.write_text('{"release": "current"}')

    monkeypatch.setattr(release, 'RELEASE_LOCK', tmp_path / 'release.lock')
    monkeypatch.setattr('sys.argv', ['release_v2.py', 'verify', str(manifest)])
    with patch.object(release.fcntl, 'flock', side_effect=wait_for_release), \
            patch.object(release, 'local_verify') as local, \
            patch.object(release, 'public_verify') as public:
        release.main()
    local.assert_called_once_with({'release': 'current'})
    public.assert_called_once_with({'release': 'current'})


@pytest.mark.parametrize('subnet', (None, '10.250.64.16/28'))
def test_prepare_generates_isolated_pair_and_proxy_healthcheck(tmp_path, subnet):
    from types import SimpleNamespace
    rendered = {'name': 'sage_standalone', 'networks': {'default': {'name': 'sage_standalone_default'}},
                'services': {name: {'build': {}, 'image': 'old', 'container_name': name,
                                   'ports': [], 'environment': {}, 'networks': {'default': None}}
                             for name in ('sage-server', 'sage-web')}}
    manifest = {'release': 'test-green', 'previous_release': 'test-blue',
                'env_file': '/tmp/env', 'data_root': '/data/sage_v2',
                'server_image': 'server:release', 'web_image': 'web:release',
                'api_port': 32008, 'web_port': 32009}
    if subnet:
        manifest['network_subnet'] = subnet
    with patch.object(release, 'run', return_value=SimpleNamespace(stdout=json.dumps(rendered))), \
            patch.object(release, 'scheduler_release') as scheduler, \
            patch.object(release, 'local_verify') as verify:
        release.prepare(manifest, tmp_path)
    compose = json.loads((tmp_path / 'compose.json').read_text())
    assert compose['networks'] == {'default': {'ipam': {'config': [{'subnet': subnet}]}} if subnet else {}}
    assert compose['name'] == 'sage-release-test-green'
    assert 'sage-server-v2-test-green:8090' in (tmp_path / 'web.conf').read_text()
    assert '/readyz' in compose['services']['sage-web']['healthcheck']['test'][1]
    assert compose['services']['sage-web']['ports'][0]['host_ip'] == '127.0.0.1'
    assert 'build' not in compose['services']['sage-server']
    assert compose['services']['sage-server']['environment']['SAGE_SCHEDULER_RELEASE_ID'] == 'test-green'
    verify.assert_called_once_with(manifest)
    scheduler.assert_called_once_with(manifest, tmp_path, 'check')


def test_cutover_requires_exact_prepared_manifest(tmp_path):
    (tmp_path / 'manifest.json').write_text('{"release":"other"}')
    with pytest.raises(RuntimeError, match='exact manifest'):
        release.cutover({'release': 'new'}, tmp_path)


def test_first_handoff_refuses_live_legacy_backend(tmp_path):
    manifest = {'release': 'new', 'previous_release': None,
                'routes': [{'old_api_port': 32000}]}
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    with patch.object(release, 'local_verify'), \
            patch.object(release, 'scheduler_release'), \
            patch.object(release.socket, 'socket') as socket:
        socket.return_value.__enter__.return_value.connect_ex.return_value = 0
        with pytest.raises(RuntimeError, match='Legacy backend still accepts connections'):
            release.cutover(manifest, tmp_path)
    assert not (tmp_path / 'rollback.json').exists()


def test_active_release_changes_are_idempotent_and_reject_stale_rollback():
    import fakeredis
    from app.v2.server.runtime.release_handoff import change_active_release

    key = 'scheduler:active-release'
    with fakeredis.FakeRedis(decode_responses=True) as redis:
        change_active_release(redis, key, None, 'blue')
        change_active_release(redis, key, 'blue', 'green')
        change_active_release(redis, key, 'blue', 'green')
        assert redis.get(key) == 'green'
        change_active_release(redis, key, 'green', 'blue')
        change_active_release(redis, key, 'blue', 'later')
        with pytest.raises(RuntimeError, match='later'):
            change_active_release(redis, key, 'green', 'blue')
        assert redis.get(key) == 'later'

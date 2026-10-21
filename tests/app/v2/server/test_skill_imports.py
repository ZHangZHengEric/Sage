
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from app.v2.server.skills.records import SkillRecord

import io
import socket
import zipfile

import pytest

from app.v2.server.skills import import_sources
from app.v2.server.skills.downloads import download_public_https
from sagents.v2.contracts.errors import SageV2Error


def archive(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as target:
        for path, body in files.items():
            target.writestr(path, body)
    return buffer.getvalue()


def skill(name, body='Hello'):
    return f'---\nname: {name}\ndescription: Example\n---\n{body}\n'


def test_cli_command_preserves_selected_skills_and_normalizes_source():
    source = import_sources.parse_skills_command(
        'npx skills add vercel-labs/agent-skills --skill web-design-guidelines -s frontend-design -y'
    )
    assert source.repository == 'vercel-labs/agent-skills'
    assert source.skills == ('web-design-guidelines', 'frontend-design')


@pytest.mark.parametrize('command', [
    'npx evil add owner/repo', 'npx skills remove owner/repo',
    'npx skills add owner/repo; touch /tmp/pwned',
    'npx skills add $(id)', 'npx skills add ./local',
    'npx skills add owner/repo --global',
    'npx skills add owner/repo --agent codex',
    'npx skills add https://github.com.evil.test/owner/repo',
])
def test_cli_command_rejects_shell_and_host_side_effects(command):
    with pytest.raises(SageV2Error):
        import_sources.parse_skills_command(command)


def test_multi_skill_archive_preserves_nested_resources():
    packages = import_sources.inspect_archive(archive({
        'repo/skills/one/SKILL.md': skill('one'),
        'repo/skills/one/scripts/run.py': 'print(1)',
        'repo/skills/two/SKILL.md': skill('two'),
        'repo/README.md': 'Repository',
    }))
    assert set(packages) == {'repo/skills/one', 'repo/skills/two'}
    assert packages['repo/skills/one'].files['scripts/run.py'] == b'print(1)'


@pytest.mark.parametrize('path', ['../SKILL.md', '/SKILL.md', 'a/../../SKILL.md'])
def test_remote_archive_rejects_escaping_paths(path):
    with pytest.raises(SageV2Error):
        import_sources.inspect_archive(archive({path: skill('bad')}))


def test_remote_archive_rejects_duplicate_paths_and_symlinks():
    with pytest.raises(SageV2Error):
        import_sources.inspect_archive(archive({'one/SKILL.md': skill('one'), 'one/./SKILL.md': 'other'}))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as target:
        link = zipfile.ZipInfo('one/SKILL.md')
        link.create_system = 3
        link.external_attr = 0o120777 << 16
        target.writestr(link, '/etc/passwd')
    with pytest.raises(SageV2Error):
        import_sources.inspect_archive(buffer.getvalue())


def test_repository_ignores_unrelated_symlink_but_rejects_links_inside_skill():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as target:
        target.writestr('repo/skills/one/SKILL.md', skill('one'))
        link = zipfile.ZipInfo('repo/CLAUDE.md')
        link.create_system = 3
        link.external_attr = 0o120777 << 16
        target.writestr(link, 'AGENTS.md')
    assert import_sources.inspect_archive(buffer.getvalue())['repo/skills/one'].name == 'one'
    with zipfile.ZipFile(buffer, 'a') as target:
        link.filename = 'repo/skills/one/link'
        target.writestr(link, '/etc/passwd')
    with pytest.raises(SageV2Error):
        import_sources.inspect_archive(buffer.getvalue())


def test_downloader_revalidates_redirect_dns_and_bounds_stream(monkeypatch):
    from app.v2.server.skills import downloads

    class Response:
        status = 200
        remaining = b'x' * 17
        def getheader(self, name):
            return None
        def read1(self, size):
            chunk, self.remaining = self.remaining[:size], self.remaining[size:]
            return chunk

    response = Response()
    connections = []
    class Connection:
        sock = None
        def __init__(self, host, address, timeout):
            connections.append((host, address))
        def request(self, *args, **kwargs):
            pass
        def getresponse(self):
            return response
        def close(self):
            pass

    monkeypatch.setattr(downloads, '_PinnedHTTPSConnection', Connection)
    monkeypatch.setattr(socket, 'getaddrinfo', lambda host, *a, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1' if host == 'private.test' else '1.1.1.1', 443))
    ])
    with pytest.raises(SageV2Error, match='大小限制'):
        download_public_https('https://public.test/file.zip', max_bytes=16)
    assert connections == [('public.test', '1.1.1.1')]
    response.status = 302
    setattr(response, 'getheader', lambda name: 'https://private.test/secret' if name == 'Location' else None)
    with pytest.raises(SageV2Error, match='私网'):
        download_public_https('https://public.test/file.zip')
    assert [host for host, _ in connections] == ['public.test', 'public.test']


def test_cli_adapter_uses_project_copy_and_does_not_inherit_credentials(tmp_path, monkeypatch):
    import shutil
    observed = {}
    packages = import_sources.inspect_archive(archive({'one/SKILL.md': skill('one')}))
    monkeypatch.setenv('GH_TOKEN', 'must-not-inherit')
    monkeypatch.setattr(import_sources.shutil, 'which', lambda name: '/bin/npx')
    class Process:
        returncode = 0
        def __init__(self, args, **kwargs):
            observed.update(args=args, **kwargs)
            shutil.copytree(import_sources.Path(args[4]) / 'skills', kwargs['cwd'] / '.agents' / 'skills')
        def wait(self, timeout=None):
            return 0
    monkeypatch.setattr(import_sources.subprocess, 'Popen', Process)
    result = import_sources._run_skills_cli(packages, tmp_path / 'cache')
    assert result['one'].files == packages['one'].files
    assert '--global' not in observed['args']
    assert observed['args'][-6:] == ['--agent', 'universal', '--copy', '--yes', '--skill', '*']
    assert 'GH_TOKEN' not in observed['env']
    assert observed['env']['npm_config_ignore_scripts'] == 'true'


def test_https_download_rejects_private_dns_before_connecting(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))])
    with pytest.raises(SageV2Error):
        download_public_https('https://download.example/skill.zip')


@pytest.mark.parametrize('url', ['http://example.com/a.zip', 'file:///etc/passwd', 'https://user:pass@example.com/a.zip', 'https://example.com:8443/a.zip'])
def test_https_download_rejects_unsupported_urls(url):
    with pytest.raises(SageV2Error):
        download_public_https(url)


def test_remote_preview_import_conflicts_and_retry(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.v2.server.main import create_app
    from app.v2.server.skills import imports
    from tests.app.v2.server.conftest import make_test_service, register_and_login

    host = make_test_service(tmp_path)
    prepared = import_sources.PreparedImport('a' * 64, import_sources.inspect_archive(archive({
        'one/SKILL.md': skill('one'), 'one/data.bin': b'\x00\xff',
        'two/SKILL.md': skill('two'),
    })))
    monkeypatch.setattr(imports, 'prepare_import', lambda *args, **kwargs: prepared)
    source = {'kind': 'zip_url', 'value': 'https://example.com/skills.zip'}
    with TestClient(create_app(service=host)) as client:
        assert client.post('/api/skill-import-previews', json=source).status_code == 401
        token = register_and_login(client)
        headers = {'Authorization': f'Bearer {token}'}
        preview = client.post('/api/skill-import-previews', json=source, headers=headers)
        assert preview.status_code == 200, preview.text
        data = preview.json()['data']
        assert [item['name'] for item in data['candidates']] == ['one', 'two']
        first = data['candidates'][0]
        body = {**source, 'revision': data['revision'], 'items': [{
            'path': first['path'], 'package_sha256': first['package_sha256'], 'expected_version_id': '',
        }]}
        published = client.post('/api/skill-imports', json=body, headers=headers)
        assert published.status_code == 200, published.text
        result = published.json()['data']
        assert result['success_count'] == 1
        assert result['skills'][0]['owner_user_id']
        path = host.paths.data_root / 'skills' / result['skills'][0]['artifact_path']
        assert (path / 'data.bin').read_bytes() == b'\x00\xff'
        assert client.post('/api/skill-imports', json=body, headers=headers).json()['data']['success_count'] == 1
        for agent in client.get('/api/agents', headers=headers).json()['data']:
            assert client.get(f"/api/agents/{agent['id']}/skills", headers=headers).json()['data'] == []
        # A stale preview cannot overwrite an edit made after it was displayed.
        created = result['skills'][0]
        client.put(f"/api/skills/{created['skill_id']}", json={'content': skill('one', 'Edited')}, headers=headers)
        conflicted = client.post('/api/skill-imports', json=body, headers=headers).json()['data']
        assert conflicted['failed_count'] == 1
        fresh = client.post('/api/skill-import-previews', json=source, headers=headers).json()['data']
        assert fresh['candidates'][0]['status'] == 'conflict'
        body['items'][0]['expected_version_id'] = fresh['candidates'][0]['expected_version_id']
        assert client.post('/api/skill-imports', json=body, headers=headers).json()['data']['failed_count'] == 1
        body['items'][0]['overwrite'] = True
        assert client.post('/api/skill-imports', json=body, headers=headers).json()['data']['success_count'] == 1
        body['revision'] = 'b' * 64
        assert client.post('/api/skill-imports', json=body, headers=headers).status_code == 409


async def test_store_rejects_stale_import_version(tmp_path):
    from dataclasses import replace
    from app.v2.server.skills.repository import MemorySkillStore
    from app.v2.server.skills.service import SkillCatalogService

    store = MemorySkillStore()
    service = SkillCatalogService(store, tmp_path)
    first = await service.publish_markdown(name='one', content=skill('one'), user_id='owner', role='user')
    with pytest.raises(SageV2Error):
        await store.publish(replace(first, version_id='other'), expected_version_id='stale')
    assert (cast('SkillRecord', await store.get(first.skill_id))).version_id == first.version_id

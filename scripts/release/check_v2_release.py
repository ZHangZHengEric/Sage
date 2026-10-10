"""Fail release builds on version drift, missing runtime resources or missing assets."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tarfile
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[2]
VERSION = '2.0.0'


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--assets', type=Path)
    parser.add_argument('--complete', action='store_true')
    args = parser.parse_args()
    project = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']
    assert project['version'] == VERSION
    assert project['requires-python'] == '>=3.12'
    assert f'version: {VERSION}+1' in (ROOT / 'app/v2/desktop/pubspec.yaml').read_text()
    assert f'version="{VERSION}"' in (ROOT / 'app/v2/server/main.py').read_text()
    for path in ['app/v2/server/web/package.json', 'app/v2/server/web/package-lock.json']:
        data = json.loads((ROOT / path).read_text())
        assert data['version'] == VERSION, path
        if 'packages' in data:
            assert data['packages']['']['version'] == VERSION
    assert tomllib.loads((ROOT / 'clients/terminal/Cargo.toml').read_text())['package']['version'] == VERSION
    lock = tomllib.loads((ROOT / 'clients/terminal/Cargo.lock').read_text())
    assert next(p['version'] for p in lock['package'] if p['name'] == 'sage-terminal') == VERSION
    for readme in ('README.md', 'README_CN.md'):
        text = (ROOT / readme).read_text()
        assert 'Version-2.0.0-green.svg' in text, readme
        assert '/releases/tag/v2.0.0' in text, readme
    assert not (ROOT / '.github/workflows/release-desktop.yml').exists(), 'Legacy application release must stay disabled'
    workflow = (ROOT / '.github/workflows/release-v2.yml').read_text()
    assert 'app/v1' not in workflow and 'desktop-v1' not in workflow
    if args.assets:
        wheel = args.assets / f'sage-{VERSION}-py3-none-any.whl'
        sdist = args.assets / f'sage-{VERSION}.tar.gz'
        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
            for required in ['app/v2/desktop/backend/main.py', 'app/v2/server/main.py',
                             'clients/cli/main.py', 'sagents/v2/__init__.py', 'mcp_servers/anytool/__init__.py']:
                assert required in names, f'Missing wheel module: {required}'
            assert any(n.startswith('app/skills/') and n.endswith('/SKILL.md') for n in names)
            metadata = archive.read(f'sage-{VERSION}.dist-info/METADATA').decode()
            assert f'Version: {VERSION}' in metadata
        with tarfile.open(sdist) as archive:
            assert f'sage-{VERSION}/app/v2/desktop/backend/main.py' in archive.getnames()
        if args.complete:
            expected = [f'Sage-{VERSION}-source.tar.gz', f'Sage-{VERSION}-server-web.tar.gz',
                f'Sage-{VERSION}-macos-arm64.dmg', f'Sage-{VERSION}-macos-x86_64.dmg',
                f'Sage-{VERSION}-windows-x86_64-setup.exe',
                *[f'Sage-{VERSION}-linux-{arch}.{ext}' for arch in ('arm64', 'x86_64') for ext in ('deb', 'tar.gz')]]
            for name in expected:
                assert (args.assets / name).is_file(), f'Missing release asset: {name}'
                assert (args.assets / name).stat().st_size > 0, f'Empty release asset: {name}'
    print('Sage 2.0 release versions and package boundaries verified.')


if __name__ == '__main__':
    main()

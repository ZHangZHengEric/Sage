"""Exercise a bundled Desktop backend outside the repository, without host Python."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
import secrets
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.error
import urllib.request


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('runtime', type=Path)
    args = parser.parse_args()
    root = args.runtime.resolve()
    manifest = json.loads((root / 'sage-runtime.json').read_text())
    python = root / ('python/python.exe' if os.name == 'nt' else 'python/bin/python3')
    environment = {k: v for k, v in os.environ.items() if k not in {'PYTHONHOME', 'PYTHONPATH', 'LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH', 'DYLD_FALLBACK_LIBRARY_PATH'}}
    environment['PYTHONNOUSERSITE'] = '1'
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    with tempfile.TemporaryDirectory(prefix='sage-release-smoke-') as temp:
        environment.update(HOME=temp, USERPROFILE=temp)
        # Check installed package resources as well as lazy v2 imports.
        subprocess.run([str(python), '-c', r'''
from pathlib import Path
import importlib.metadata
import sys
import app
from app.v2.desktop.backend.service import DesktopV2Service
from sagents.v2 import SAgentBuilder
assert importlib.metadata.version('sage') == '2.0.0'
assert any((Path(app.__file__).parent / 'skills').glob('*/SKILL.md'))
assert not any(n.startswith(('app.v1.', 'sagents.v1.')) for n in sys.modules)
# Verify native one-writer locks, including Windows, across processes.
import asyncio
import subprocess
from sagents.v2.runtime.session.plugins.filesystem import FilesystemSessionStore
from sagents.v2.runtime.execution.scheduler.plugins.filesystem import FilesystemScheduler
for module, name, error in (
    ('sagents.v2.runtime.session.plugins.filesystem', 'FilesystemSessionStore', 'StoreInUseError'),
    ('sagents.v2.runtime.execution.scheduler.plugins.filesystem', 'FilesystemScheduler', 'SchedulerInUseError'),
):
    cls = getattr(__import__(module, fromlist=[name]), name)
    store_root = Path.cwd() / name
    first = cls(store_root)
    probe = f'from {module} import {name}, {error}\ntry: {name}({str(store_root)!r})\nexcept {error}: raise SystemExit(42)'
    assert subprocess.run([sys.executable, '-c', probe]).returncode == 42
    asyncio.run(first.close())
    replacement = cls(store_root)
    asyncio.run(replacement.close())
'''], cwd=temp, env=environment, check=True)
        with (Path(temp) / 'stderr.log').open('w+') as log:
            process = subprocess.Popen([str(python), '-m', 'app.v2.desktop.backend.main',
                '--data-root', str(Path(temp) / 'data'), '--build-id', manifest['build_id']],
                cwd=temp, env=environment, stdout=subprocess.PIPE, stderr=log, text=True)
            executor = ThreadPoolExecutor(max_workers=1)
            try:
                def read_ready():
                    for line in process.stdout:
                        try:
                            value = json.loads(line)
                        except ValueError:
                            continue
                        if isinstance(value, dict) and 'port' in value and 'auth_token' in value:
                            return value
                    raise RuntimeError('Sidecar exited before readiness')
                ready = executor.submit(read_ready).result(timeout=90)
                endpoint = f"http://127.0.0.1:{ready['port']}"
                headers = {'Authorization': f"Bearer {ready['auth_token']}"}
                for attempt in range(120):
                    try:
                        request = urllib.request.Request(endpoint + '/health', headers=headers)
                        with urllib.request.urlopen(request, timeout=2) as response:
                            health = json.load(response)['data']
                        break
                    except (urllib.error.URLError, TimeoutError):
                        time.sleep(0.25)
                else:
                    raise RuntimeError('Sidecar never became healthy')
                assert health['status'] == 'ok' and health['build_id'] == manifest['build_id']
                assert health['protocol'] == 'sage.runtime/v2', health
                client_id = secrets.token_urlsafe(24)
                for method in ('PUT', 'DELETE'):
                    request = urllib.request.Request(endpoint + f'/api/v2/runtime/clients/{client_id}',
                        headers=headers, method=method)
                    with urllib.request.urlopen(request, timeout=5) as response:
                        result = json.load(response)['data']
                assert result['shutdown_requested'] is True
                assert process.wait(timeout=20) == 0
                assert not (Path(temp) / 'data/runtime/desktop-v2-sidecar.json').exists()
            except BaseException:
                log.flush()
                log.seek(0)
                print(log.read())
                raise
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                executor.shutdown(wait=True)
    print('Bundled v2 imports, skills, authenticated readiness and shutdown passed.')


if __name__ == '__main__':
    main()

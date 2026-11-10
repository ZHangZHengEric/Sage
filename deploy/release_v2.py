#!/usr/bin/env python3
"""Paired Compose releases with checked Caddy cutover; Linux deployment host only."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def request(base, path, expected=200, body=None):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):
            return None
    req = urllib.request.Request(base.rstrip('/') + path, data=body,
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=10) as response:
            status, payload = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status, payload = exc.code, exc.read()
    if status != expected:
        raise RuntimeError(f'{base}{path}: expected {expected}, got {status}')
    return payload


def verify(api, web):
    for base in (api, web):
        if json.loads(request(base, '/readyz')).get('status') != 'ok':
            raise RuntimeError(f'{base}: not ready')
        request(base, '/health')
        # Exercise the API router through both entrances without a login side effect.
        request(base, '/api/auth/login', 422, b'{}')
    request(web, '/')
    print(f'OK: {api} and {web}', flush=True)


def replace_port(text, old, new):
    result, count = re.subn(r'(?m)^(\s*reverse_proxy )(?:localhost|127\.0\.0\.1):'
                            + str(int(old)) + r'\s*$',
                            lambda m: m[1] + f'127.0.0.1:{int(new)}', text)
    if count != 1:
        raise ValueError(f'Expected exactly one upstream on port {old}, found {count}')
    return result


def atomic_write(path, text):
    path = Path(path)
    temp = path.with_name(path.name + '.sage-next')
    temp.write_text(text)
    os.chmod(temp, path.stat().st_mode & 0o777 if path.exists() else 0o600)
    temp.replace(path)


def public_verify(m):
    for route in m['routes']:
        verify(route['api_url'], route['web_url'])


def local_verify(m):
    verify(f"http://127.0.0.1:{m['api_port']}", f"http://127.0.0.1:{m['web_port']}")


def reload_caddy(m):
    run('caddy', 'validate', '--config', m.get('caddy_config', '/etc/caddy/Caddyfile'),
        '--adapter', 'caddyfile', stdout=subprocess.DEVNULL)
    run('systemctl', 'reload', 'caddy')


def prepare(m, directory):
    if (directory / 'compose.json').exists():
        raise RuntimeError('Release already prepared; use a new release ID')
    env = dict(os.environ, SAGE_COMPOSE_ENV_FILE=str(Path(m['env_file']).resolve()),
               SAGE_ROOT=m['data_root'])
    if not Path(m['data_root']).is_absolute():
        raise ValueError('data_root must be absolute')
    rendered = run('docker', 'compose', '--env-file', m['env_file'], '-f',
                   str(ROOT / 'standalone/docker-compose.yml'), 'config', '--format', 'json',
                   env=env, capture_output=True)
    config = json.loads(rendered.stdout)
    config['name'] = 'sage-release-' + m['release']
    config['networks'] = {'default': {}}
    for kind, target, port in [('server', 8090, m['api_port']), ('web', 80, m['web_port'])]:
        service = config['services']['sage-' + kind]
        service.pop('build', None)
        service['image'] = m[kind + '_image']
        service['container_name'] = f"sage-{kind}-v2-{m['release']}"
        service['ports'] = [{'target': target, 'published': str(port), 'host_ip': '127.0.0.1'}]
    nginx = (ROOT / 'standalone/nginx.conf').read_text().replace(
        'set $sage_backend sage-server:8090;',
        f"set $sage_backend sage-server-v2-{m['release']}:8090;")
    (directory / 'web.conf').write_text(nginx)
    web = config['services']['sage-web']
    web['volumes'] = [{'type': 'bind', 'source': str(directory / 'web.conf'),
                       'target': '/etc/nginx/conf.d/default.conf', 'read_only': True}]
    web['healthcheck'] = {'test': ['CMD-SHELL', 'wget -qO- -T 4 http://127.0.0.1/ >/dev/null && wget -qO- -T 4 http://127.0.0.1/readyz >/dev/null'],
                          'interval': '30s', 'timeout': '10s', 'retries': 3}
    atomic_write(directory / 'compose.json', json.dumps(config, indent=2))
    atomic_write(directory / 'manifest.json', json.dumps(m, sort_keys=True, indent=2))
    run('docker', 'compose', '-f', str(directory / 'compose.json'), 'up', '-d', '--wait', '--wait-timeout', '180')
    local_verify(m)


def restore(m, state):
    # Refuse to overwrite a subsequent deployment or unrelated operator edit.
    for file, item in state.items():
        if Path(file).read_text() not in (item['before'], item['after']):
            raise RuntimeError(f'{file} changed since cutover; refusing stale rollback')
    for file, item in state.items():
        atomic_write(file, item['before'])
    reload_caddy(m)
    public_verify(m)


def cutover(m, directory):
    if not (directory / 'manifest.json').exists() or json.loads((directory / 'manifest.json').read_text()) != m:
        raise RuntimeError('Run prepare with this exact manifest before cutover')
    local_verify(m)
    backup = directory / 'rollback.json'
    if backup.exists():
        raise RuntimeError('Cutover already attempted; use rollback or a new release ID')
    state = {}
    for route in m['routes']:
        file = route['file']
        if file in state:
            raise ValueError('Each Caddy file must appear once')
        before = Path(file).read_text()
        after = replace_port(before, route['old_api_port'], m['api_port'])
        after = replace_port(after, route['old_web_port'], m['web_port'])
        state[file] = {'before': before, 'after': after}
    monitor = m.get('monitor_manifest')
    if monitor:
        state[monitor] = {'before': Path(monitor).read_text(),
                          'after': json.dumps(m, indent=2)}
    atomic_write(backup, json.dumps(state, indent=2))
    try:
        for file, item in state.items():
            if Path(file).read_text() != item['before']:
                raise RuntimeError(f'{file} changed while preparing cutover')
            atomic_write(file, item['after'])
        reload_caddy(m)
        # Keep the release lock throughout the observation window.
        deadline = time.monotonic() + max(0, m.get('observe_seconds', 60))
        while True:
            public_verify(m)
            if time.monotonic() >= deadline:
                break
            time.sleep(5)
    except BaseException:
        restore(m, state)
        raise
    print('Cutover verified. Previous containers retained; no automatic cleanup.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'verify', 'cutover', 'rollback'])
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    m = json.loads(args.manifest.read_text())
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,60}', m['release']):
        parser.error('release must be a unique lowercase slug')
    directory = Path(m.get('state_root', '/data/sage_v2/releases')) / m['release']
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open('/tmp/palune-sage-production-release.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == 'prepare':
            prepare(m, directory)
        elif args.action == 'verify':
            local_verify(m)
            public_verify(m)
        elif args.action == 'cutover':
            cutover(m, directory)
        else:
            restore(m, json.loads((directory / 'rollback.json').read_text()))


if __name__ == '__main__':
    main()

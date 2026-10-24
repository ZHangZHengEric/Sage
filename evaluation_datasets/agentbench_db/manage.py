"""Explicit lifecycle for a disposable, loopback-only benchmark MySQL server."""
from __future__ import annotations
import argparse
import json
import secrets
import shutil
import subprocess
import time
from evaluation_datasets.agentbench_db import runtime

IMAGE = 'mysql:8.0.36'
LABEL = 'sage.rsi.dataset=agentbench-db'


def docker(*args):
    if not shutil.which('docker'):
        raise RuntimeError('Docker is required. Install/start Docker Desktop or Docker Engine, then retry.')
    return subprocess.run(['docker', *args], check=True, capture_output=True, text=True).stdout.strip()


def managed(config):
    item = json.loads(docker('inspect', config['container_id']))[0]
    if item['Config'].get('Labels', {}).get('sage.rsi.dataset') != 'agentbench-db':
        raise RuntimeError('Refusing to operate on a container without the benchmark label')
    return item


def start():
    if runtime.CONNECTION.exists():
        managed(runtime.configuration())
        return runtime.preflight()
    docker('info')
    password = secrets.token_hex(24)
    runtime.CONNECTION.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Credentials are sent through stdin, not command-line arguments or stdout.
    envfile = runtime.CONNECTION.parent / 'mysql.env'
    envfile.touch(mode=0o600)
    envfile.write_text('MYSQL_ROOT_PASSWORD=' + password + '\nMYSQL_ROOT_HOST=%\n')
    try:
        container = docker('run', '-d', '--rm', '--label', LABEL,
            '--publish', '127.0.0.1::3306', '--env-file', str(envfile),
            '--memory', '1g', '--cpus', '2', '--tmpfs', '/var/lib/mysql:rw,size=536870912',
            IMAGE, '--innodb-buffer-pool-size=128M', '--max-connections=32',
            '--local-infile=OFF', '--character-set-server=utf8mb4', '--collation-server=utf8mb4_0900_ai_ci')
    finally:
        envfile.unlink(missing_ok=True)
    try:
        item = json.loads(docker('inspect', container))[0]
        binding = item['NetworkSettings']['Ports']['3306/tcp'][0]
        config = {'host': '127.0.0.1', 'port': int(binding['HostPort']), 'password': password,
            'container_id': container, 'image': IMAGE, 'image_id': item['Image']}
        runtime.CONNECTION.touch(mode=0o600)
        runtime.CONNECTION.write_text(json.dumps(config))
        runtime.CONNECTION.chmod(0o600)
        deadline = time.monotonic() + 120
        while True:
            try:
                return runtime.preflight()
            except Exception:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(1)
    except BaseException:
        docker('stop', container)
        runtime.CONNECTION.unlink(missing_ok=True)
        raise


def stop():
    if not runtime.CONNECTION.exists():
        return {'stopped': True}
    config = runtime.configuration()
    managed(config)
    docker('stop', config['container_id'])
    runtime.CONNECTION.unlink()
    return {'stopped': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['start', 'status', 'stop'])
    args = parser.parse_args()
    result = start() if args.action == 'start' else stop() if args.action == 'stop' else runtime.preflight()
    print(json.dumps(result))

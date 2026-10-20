"""Bundle a relocatable CPython and the release wheel into a Flutter build."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--wheel', type=Path, required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--commit', required=True)
    args = parser.parse_args()
    bundle = args.bundle.resolve()
    if not bundle.is_dir():
        parser.error(f'Flutter bundle is missing: {bundle}')
    root = bundle / 'Contents/Resources/sage-runtime' if sys.platform == 'darwin' else bundle / 'sage-runtime'
    if root.exists():
        parser.error(f'Refusing to replace existing runtime: {root}')
    managed = subprocess.check_output(['uv', 'python', 'find', '--managed-python', '3.13'], text=True).strip()
    prefix = Path(subprocess.check_output([managed, '-c', 'import sys; print(sys.prefix)'], text=True).strip())
    # Preserve relative interpreter/library links from python-build-standalone.
    shutil.copytree(prefix, root / 'python', symlinks=True)
    python = root / ('python/python.exe' if os.name == 'nt' else 'python/bin/python3')
    environment = {k: v for k, v in os.environ.items() if k not in {'PYTHONHOME', 'PYTHONPATH', 'LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH', 'DYLD_FALLBACK_LIBRARY_PATH'}}
    environment['PYTHONNOUSERSITE'] = '1'
    subprocess.run(['uv', 'pip', 'install', '--break-system-packages', '--python', str(python), f'{args.wheel.resolve()}[desktop-v2]'], env=environment, check=True)
    subprocess.run(['uv', 'pip', 'check', '--python', str(python)], env=environment, check=True)
    # setup-node supplies the official relocatable binary on each release runner.
    node = shutil.which('node')
    if node is None:
        raise RuntimeError('Desktop packaging requires Node.js 22+ for OpenUI')
    major = int(subprocess.check_output([node, '-p', 'process.versions.node.split(".")[0]'], text=True).strip())
    if major < 22:
        raise RuntimeError('OpenUI requires Node.js 22+')
    node_root = root / 'node'
    node_root.mkdir()
    shutil.copy2(Path(node).resolve(), node_root / ('node.exe' if os.name == 'nt' else 'node'))
    # Include the Node distribution license with the bundled executable.
    node_prefix = Path(node).resolve().parent
    license_path = next((p for p in (node_prefix / 'LICENSE', node_prefix.parent / 'LICENSE', node_prefix.parent / 'share/doc/node/LICENSE') if p.is_file()), None)
    if license_path is None:
        raise RuntimeError('Node distribution LICENSE is required for packaging')
    shutil.copy2(license_path, node_root / 'LICENSE')
    (root / 'sage-runtime.json').write_text(json.dumps({
        'version': args.version, 'commit': args.commit,
        'build_id': f'release-{args.version}-{args.commit}',
    }, indent=2) + '\n')
    # Dependency records accompany every platform bundle for release inspection.
    frozen = subprocess.check_output(['uv', 'pip', 'freeze', '--python', str(python)], text=True, env=environment)
    (root / 'dependencies.txt').write_text(frozen)
    print(root)


if __name__ == '__main__':
    main()

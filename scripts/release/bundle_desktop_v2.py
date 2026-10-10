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
    subprocess.run(['uv', 'pip', 'install', '--break-system-packages', '--python', str(python), str(args.wheel.resolve())], env=environment, check=True)
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

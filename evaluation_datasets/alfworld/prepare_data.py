"""Restore the exact selected self-contained games from the official release ZIP."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent


def restore(archive):
    resource = json.loads((ROOT / 'resources.json').read_text())
    if hashlib.sha256(archive.read_bytes()).hexdigest() != resource['sha256']:
        raise ValueError('Wrong ALFWorld release archive SHA256')
    tasks = json.loads((ROOT / 'data/tasks.json').read_text())
    # The committed manifest is the exact subset definition, independent of ZIP
    # ordering, library version and machine. Do not extract arbitrary ZIP paths.
    with zipfile.ZipFile(archive) as source:
        for task in tasks:
            raw = source.read(task['source_member'])
            if hashlib.sha256(raw).hexdigest() != task['sha256']:
                raise ValueError('Selected official game hash mismatch')
            path = ROOT / 'data' / task['game']
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
    return len(tasks)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Restore committed selection; download URL is in resources.json')
    parser.add_argument('--archive', type=Path, required=True)
    print(restore(parser.parse_args().archive))

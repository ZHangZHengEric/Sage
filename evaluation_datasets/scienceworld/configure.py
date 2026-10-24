"""Persist a local JRE path usable by MCP and isolated Python scorers."""
import argparse
import json
import subprocess
from pathlib import Path
from evaluation_datasets.scienceworld.runtime import ROOT

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--java-home', type=Path, required=True)
    args = parser.parse_args()
    home = args.java_home.expanduser().resolve()
    subprocess.run([str(home / 'bin/java'), '-version'], check=True)
    target = ROOT / '.runtime/java.json'
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    target.write_text(json.dumps({'java_home': str(home)}) + '\n')
    target.chmod(0o600)
    print('Configured local JRE; run python -m evaluation_datasets.scienceworld.runtime to preflight.')

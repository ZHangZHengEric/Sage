"""Required Windows build inputs must survive a clean checkout and cache cleanup."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def test_windows_runner_manifest_is_source_not_ignored_output():
    relative = 'app/v2/desktop/windows/runner/runner.exe.manifest'
    assert (ROOT / relative).is_file()
    cmake = ROOT / 'app/v2/desktop/windows/runner/CMakeLists.txt'
    assert '"runner.exe.manifest"' in cmake.read_text()
    result = subprocess.run(
        ['git', 'check-ignore', '--no-index', '-q', '--', relative], cwd=ROOT,
    )
    assert result.returncode == 1, 'Windows runner manifest must be included in source control'

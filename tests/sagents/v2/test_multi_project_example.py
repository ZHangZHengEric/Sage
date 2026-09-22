from pathlib import Path

import pytest

from examples.sagents_v2_multi_project import run_example


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_first", [False, True])
async def test_public_api_multi_project_concurrency(tmp_path: Path, cancel_first: bool):
    result = await run_example(tmp_path, cancel_first=cancel_first)
    assert result == {
        "sessions": 3,
        "concurrent_runs": 3,
        "artifacts": 6 if cancel_first else 9,
    }

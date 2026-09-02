"""Pytest root helpers.

Keep the repository root on ``sys.path`` so tests can import project modules
without repeating local path hacks or hard-coded user directories.
"""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
root = str(REPO_ROOT)
if root not in sys.path:
    sys.path.insert(0, root)

"""Read the filesystem Session location map without opening a writer."""

import json
from pathlib import Path
from urllib.parse import quote

SESSION_LAYOUT_FORMAT = "sage.filesystem-session-layout/v1"


def resolve_session_directory(sessions_root: Path, session_id: str) -> Path:
    root = sessions_root.resolve()
    segment = quote(session_id, safe="")
    if not segment or segment in {".", ".."}:
        raise ValueError("unsafe Session identifier")
    location = root.parent / ".session-store" / "locations" / f"{segment}.json"
    if not location.is_file():
        return root / segment
    payload = json.loads(location.read_text(encoding="utf-8"))
    if (
        payload.get("format") != SESSION_LAYOUT_FORMAT
        or payload.get("session_id") != session_id
    ):
        raise ValueError("location identity does not match")
    candidate = (root / payload["relative_path"]).resolve()
    candidate.relative_to(root)
    return candidate

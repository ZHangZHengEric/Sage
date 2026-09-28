"""Optional same-origin hosting for the built Server v2 web client."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def mount_web(app: FastAPI, root: Path) -> None:
    root = root.resolve()
    if not (root / "index.html").is_file():
        return
    if (root / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        # Unknown protocol routes must remain 404, never a successful HTML page.
        if full_path.split("/", 1)[0] in {"api", "a2a", ".well-known", "assets"}:
            raise HTTPException(status_code=404, detail="not found")
        candidate = (root / full_path).resolve()
        if not candidate.is_relative_to(root):
            raise HTTPException(status_code=404, detail="not found")
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(root / "index.html")

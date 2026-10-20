"""Upload ingress bounds memory while retaining per-file publication results.

Catalog tests already cover ZIP validation/publication. The missing boundary is
the router's file reads: reject an oversized file without reading it entirely,
and finish each publication before reading the next file.
"""

import io
from types import SimpleNamespace
import zipfile

from app.v2.server.routers.skills import upload_skills
from app.v2.server.skills.repository import MemorySkillStore
from app.v2.server.skills.service import SkillCatalogService


LIMIT = 32 * 1024 * 1024


def skill_zip(name):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("SKILL.md", f"---\nname: {name}\ndescription: Demo\n---\n# Body\n")
    return stream.getvalue()


async def test_upload_limits_each_read_and_preserves_mixed_batch_results(tmp_path):
    service = SkillCatalogService(MemorySkillStore(), tmp_path)

    class File:
        def __init__(self, filename, payload=b"", expected_visible=()):
            self.filename = filename
            self.payload = payload
            self.expected_visible = expected_visible

        async def read(self, size=-1):
            assert 0 < size <= LIMIT + 1, "upload must never read the whole file"
            visible = await service.list_visible(user_id="owner", role="user")
            assert {item.name for item in visible} == set(self.expected_visible)
            if self.filename == "huge.zip":
                # Simulate a larger external file without allocating it fully.
                return b"x" * size
            assert self.filename.endswith(".zip"), "invalid extension must not be read"
            return self.payload[:size]

    response = await upload_skills(
        SimpleNamespace(user_id="owner", role="user"), service,
        [File("huge.zip"), File("invalid.txt"), File("bad.zip", b"bad"),
         File("first.zip", skill_zip("first")),
         File("second.zip", skill_zip("second"), ("first",))],
    )
    data = response["data"]
    assert [item["filename"] for item in data["results"]] == [
        "huge.zip", "invalid.txt", "bad.zip", "first.zip", "second.zip",
    ]
    assert [item["success"] for item in data["results"]] == [False, False, False, True, True]
    assert data["results"][0]["message"] == "zip exceeds size limits"
    assert data["success_count"] == 2 and data["failed_count"] == 3
    assert [item["name"] for item in data["skills"]] == ["first", "second"]
    assert {item.name for item in await service.list_visible(user_id="owner", role="user")} == {"first", "second"}

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.v2.server.conversations.orm import ThreadRow
from app.v2.server.database import Database, DatabaseSettings
from app.v2.server.database.schema import create_host_schema
from app.v2.server.routers.web import mount_web
from app.v2.server.skills.files import inspect_skill_directory
from app.v2.server.skills.orm import SkillRow


async def test_old_thread_schema_is_upgraded_without_losing_rows(tmp_path):
    database = Database(DatabaseSettings(url=f"sqlite+aiosqlite:///{tmp_path}/old.db"))
    await database.start()
    try:
        async with database._engine.begin() as connection:
            await connection.execute(
                text(
                    "CREATE TABLE threads (thread_id VARCHAR(64) PRIMARY KEY, "
                    "user_id VARCHAR(64), title VARCHAR(512), updated_at VARCHAR(64))"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO threads VALUES ('thread_1', 'user_1', 'old title', 'now')"
                )
            )
        await create_host_schema(database)
        await create_host_schema(database)
        async with database._engine.connect() as connection:
            row = (await connection.execute(select(ThreadRow))).mappings().one()
        assert row["title"] == "old title"
        assert row["agent_id"] == ""
    finally:
        await database.stop()


def test_skill_description_mysql_column_can_hold_full_metadata():
    from sqlalchemy.dialects.mysql import dialect

    assert (
        SkillRow.__table__.c.description.type.compile(dialect=dialect()) == "LONGTEXT"
    )


@pytest.mark.parametrize(
    "description, expected",
    [
        ('"' + "长描述" * 500 + '"', "长描述" * 500),
        (
            ">-\n  Select this skill for video\n  longer than 30 seconds.",
            "Select this skill for video longer than 30 seconds.",
        ),
        ("|\n  first line\n  second line", "first line\nsecond line\n"),
    ],
)
def test_skill_package_preserves_yaml_description(tmp_path, description, expected):
    (tmp_path / "SKILL.md").write_text(
        f"---\nname: demo\ndescription: {description}\n---\n# Body", encoding="utf-8"
    )
    package = inspect_skill_directory(tmp_path)
    assert package.name == "demo"
    assert package.description == expected


def test_built_web_serves_navigation_and_preserves_protocol_404(tmp_path):
    (tmp_path / "index.html").write_text("<html>studio</html>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text('console.log("app")')
    app = FastAPI()
    mount_web(app, tmp_path)
    with TestClient(app) as client:
        for path in ["/", "/studio", "/chat/thread_1"]:
            response = client.get(path)
            assert response.status_code == 200
            assert response.text == "<html>studio</html>"
        assert client.get("/assets/app.js").status_code == 200
        for path in [
            "/api",
            "/api/missing",
            "/a2a/missing",
            "/.well-known/missing",
            "/assets/missing.js",
            "/%2e%2e/private",
        ]:
            assert client.get(path).status_code == 404


def test_web_without_build_leaves_backend_routes_untouched(tmp_path):
    app = FastAPI()
    mount_web(app, tmp_path)
    with TestClient(app) as client:
        assert client.get("/").status_code == 404
        assert client.get("/openapi.json").status_code == 200

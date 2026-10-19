import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.v2.server.routers.web import mount_web
from app.v2.server.skills.files import inspect_skill_directory
from app.v2.server.skills.orm import SkillRow


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

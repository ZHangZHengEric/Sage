from pathlib import Path


def test_server_installs_browsers_after_final_playwright_version_is_resolved():
    repo_root = Path(__file__).resolve().parents[2]
    dockerfile = (repo_root / "deploy/images/Dockerfile.server").read_text(
        encoding="utf-8"
    )

    node_package = dockerfile.index("npm install -g playwright@1.58.0")
    python_pin = dockerfile.index('"playwright==1.61.0"')
    final_requirements = dockerfile.index(
        "pip install --no-cache-dir -r requirements.server.txt"
    )
    python_browser_install = dockerfile.index(
        "python -m playwright install --with-deps chromium"
    )

    assert node_package < python_pin < final_requirements < python_browser_install
    assert "PLAYWRIGHT_BROWSERS_PATH=/usr/local/share/ms-playwright" in dockerfile


def test_server_prunes_desktop_only_im_dependencies():
    repo_root = Path(__file__).resolve().parents[2]
    dockerfile = (repo_root / "deploy/images/Dockerfile.server").read_text(
        encoding="utf-8"
    )

    requirements_filter = dockerfile.split(
        "requirements.txt > requirements.server.txt", maxsplit=1
    )[0]

    assert "lark-oapi" in requirements_filter
    assert "dingtalk-stream" in requirements_filter
    assert "python-socks" in requirements_filter
    assert "RUN rm -rf /app/mcp_servers/im_server" in dockerfile


def test_server_does_not_install_removed_auth_or_verification_dependencies():
    repo_root = Path(__file__).resolve().parents[2]
    dockerfile = (repo_root / "deploy/images/Dockerfile.server").read_text(
        encoding="utf-8"
    )

    assert "Authlib" not in dockerfile
    assert "alibabacloud_dm20151123" not in dockerfile

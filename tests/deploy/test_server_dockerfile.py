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


def test_server_downloads_playwright_browsers_from_domestic_mirror():
    repo_root = Path(__file__).resolve().parents[2]
    dockerfile = (repo_root / "deploy/images/Dockerfile.server").read_text(
        encoding="utf-8"
    )

    mirror_setting = (
        "PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST="
        "https://cdn.npmmirror.com/binaries/playwright"
    )
    node_setup = dockerfile.index("RUN curl -fsSL https://deb.nodesource.com/setup_20.x")
    mirror_position = dockerfile.index(mirror_setting)
    browser_install = dockerfile.index("npm install -g playwright@1.58.0")

    assert dockerfile.count(mirror_setting) == 1
    assert node_setup < mirror_position < browser_install


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

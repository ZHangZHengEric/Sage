from pathlib import Path


def test_server_installs_one_shared_browser_after_playwright_versions_are_resolved():
    repo_root = Path(__file__).resolve().parents[2]
    dockerfile = (repo_root / "deploy/images/Dockerfile.server").read_text(
        encoding="utf-8"
    )

    node_package = dockerfile.index("npm install -g playwright@1.61.0")
    python_pin = dockerfile.index('"playwright==1.61.0"')
    final_requirements = dockerfile.index(
        "pip install --no-cache-dir -r requirements.server.txt"
    )
    python_browser_install = dockerfile.index(
        "python -m playwright install --with-deps chromium"
    )

    assert node_package < python_pin < final_requirements < python_browser_install
    assert dockerfile.count("playwright install --with-deps chromium") == 1
    assert "playwright@1.58.0" not in dockerfile
    assert "PLAYWRIGHT_BROWSERS_PATH=/usr/local/share/ms-playwright" in dockerfile


def test_server_downloads_playwright_browsers_from_domestic_mirror():
    repo_root = Path(__file__).resolve().parents[2]
    dockerfile = (repo_root / "deploy/images/Dockerfile.server").read_text(
        encoding="utf-8"
    )

    python_mirror = (
        "PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST="
        "https://cdn.npmmirror.com/binaries/playwright"
    )
    final_requirements = dockerfile.index(
        "pip install --no-cache-dir -r requirements.server.txt"
    )
    copy_source = dockerfile.index("COPY . .")

    assert python_mirror in dockerfile[final_requirements:copy_source]
    assert dockerfile.count(python_mirror) == 1
    assert "https://cdn.npmmirror.com/binaries/chrome-for-testing" not in dockerfile
    assert "ENV PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST=" not in dockerfile


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

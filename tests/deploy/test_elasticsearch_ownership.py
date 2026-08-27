from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_deployment_does_not_bundle_elasticsearch():
    deployment_sources = (
        REPO_ROOT / "deploy/compose.sh",
        REPO_ROOT / "deploy/prod/docker-compose.yml",
        REPO_ROOT / "deploy/README.md",
        REPO_ROOT / "scripts/dev-up.sh",
        REPO_ROOT / "docs/en/applications/WEB.md",
        REPO_ROOT / "docs/zh/applications/WEB.md",
    )
    bundled_elasticsearch_markers = (
        "sage-es",
        "Dockerfile.es",
        "SAGE_ELASTICSEARCH_PUBLISHED_PORT",
        "/es/data",
        "MySQL + ES + RustFS",
        "Requires MySQL, Elasticsearch, RustFS",
    )

    for source in deployment_sources:
        content = source.read_text(encoding="utf-8")
        for marker in bundled_elasticsearch_markers:
            assert marker not in content, f"{source} still contains {marker}"

    assert not (REPO_ROOT / "deploy/images/Dockerfile.es").exists()

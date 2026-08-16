import pytest

from sagents.storage import (
    SessionStorageConfig,
    StorageError,
    create_session_store,
)


def test_factory_builds_default_backend_from_session_root(tmp_path):
    store = create_session_store(session_root=str(tmp_path))

    assert store.healthcheck()["backend"] == "filesystem"
    assert store.root == str(tmp_path)


def test_factory_accepts_backend_neutral_config(tmp_path):
    store = create_session_store(
        SessionStorageConfig(
            backend="filesystem",
            options={"root": str(tmp_path)},
        )
    )

    assert store.root == str(tmp_path)


def test_factory_reads_environment_config(monkeypatch, tmp_path):
    monkeypatch.setenv("SAGE_SESSION_STORAGE_BACKEND", "filesystem")
    monkeypatch.setenv(
        "SAGE_SESSION_STORAGE_OPTIONS", f'{{"root": "{tmp_path}"}}'
    )

    store = create_session_store()

    assert store.root == str(tmp_path)


def test_factory_rejects_unknown_backend(tmp_path):
    with pytest.raises(StorageError, match="unsupported session storage backend"):
        create_session_store(
            {"backend": "unknown", "options": {"root": str(tmp_path)}}
        )

import json
import stat
from concurrent.futures import ThreadPoolExecutor

import pytest
from cryptography.fernet import Fernet

from app.v2.server.im.credentials import IMCredentials
from tests.app.v2.server.im.test_feishu import config


def test_credentials_are_encrypted_and_bound_to_owner_and_external_account():
    vault = IMCredentials(Fernet.generate_key().decode())
    stored = vault.seal("alice", config())
    assert set(stored) == {"app_id", "tenant_key", "credentials_ciphertext"}
    assert '"secret"' not in json.dumps(stored)
    assert vault.open("alice", stored).app_secret.get_secret_value() == "secret"
    for owner, value in [
        ("bob", stored),
        ("alice", {**stored, "app_id": "cli_other"}),
        ("alice", {**stored, "tenant_key": "other"}),
    ]:
        with pytest.raises(ValueError, match="cannot be decrypted"):
            vault.open(owner, value)
    with pytest.raises(ValueError, match="cannot be decrypted"):
        IMCredentials(Fernet.generate_key().decode()).open("alice", stored)


def test_first_start_persists_private_key_and_restart_reuses_it(tmp_path):
    vault = IMCredentials.load(tmp_path)
    key_file = tmp_path / "secrets" / "im-credentials.key"
    original = key_file.read_bytes()
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(key_file.parent.stat().st_mode) == 0o700
    stored = vault.seal("alice", config())
    restarted = IMCredentials.load(tmp_path, allow_create=False)
    assert restarted.open("alice", stored).app_secret.get_secret_value() == "secret"
    assert key_file.read_bytes() == original
    assert "secret" not in repr(config()).replace("app_secret", "")


def test_concurrent_first_starts_publish_one_complete_key(tmp_path):
    with ThreadPoolExecutor(max_workers=12) as pool:
        vaults = list(pool.map(lambda _: IMCredentials.load(tmp_path), range(32)))
    stored = vaults[0].seal("alice", config())
    assert all(v.open("alice", stored).app_id == "cli_test" for v in vaults)
    assert list((tmp_path / "secrets").iterdir()) == [
        tmp_path / "secrets" / "im-credentials.key"
    ]


@pytest.mark.parametrize("content", [b"", b"broken", b"a" * 4096])
def test_corrupt_key_is_never_overwritten(tmp_path, content):
    IMCredentials.load(tmp_path)
    key_file = tmp_path / "secrets" / "im-credentials.key"
    key_file.write_bytes(content)
    with pytest.raises(RuntimeError, match="IM credential key"):
        IMCredentials.load(tmp_path)
    assert key_file.read_bytes() == content


def test_missing_key_with_existing_credentials_is_not_regenerated(tmp_path):
    with pytest.raises(RuntimeError, match="IM credential key.*missing"):
        IMCredentials.load(tmp_path, allow_create=False)
    assert not (tmp_path / "secrets" / "im-credentials.key").exists()


@pytest.mark.parametrize("target", ["directory", "key"])
def test_key_storage_rejects_symlinks(tmp_path, target):
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_key = outside / "im-credentials.key"
    outside_key.write_bytes(Fernet.generate_key())
    if target == "directory":
        (tmp_path / "secrets").symlink_to(outside, target_is_directory=True)
    else:
        (tmp_path / "secrets").mkdir(mode=0o700)
        (tmp_path / "secrets" / "im-credentials.key").symlink_to(outside_key)
    with pytest.raises(RuntimeError, match="IM credential key"):
        IMCredentials.load(tmp_path)


def test_key_storage_rejects_public_read_permissions(tmp_path):
    IMCredentials.load(tmp_path)
    (tmp_path / "secrets" / "im-credentials.key").chmod(0o644)
    with pytest.raises(RuntimeError, match="IM credential key"):
        IMCredentials.load(tmp_path)

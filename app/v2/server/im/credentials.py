"""Connection credential encryption with an automatically persisted server key."""

import json
import os
import stat
from pathlib import Path
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken

from .feishu import FeishuConfig


class IMCredentials:
    def __init__(self, key):
        self._cipher = Fernet(key.encode())

    @classmethod
    def load(cls, data_root: Path, *, allow_create: bool = True):
        """Publish a complete private key once, including concurrent first starts.

        The key lives outside tenant workspaces. Existing encrypted connections
        must never cause a replacement key to be generated after key loss.
        """
        directory = data_root / "secrets"
        name = "im-credentials.key"
        try:
            directory.mkdir(mode=0o700, exist_ok=True)
            directory_fd = os.open(
                directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            )
            try:
                if stat.S_IMODE(os.fstat(directory_fd).st_mode) & 0o077:
                    raise ValueError("key directory must be private")
                try:
                    return cls._durable_read(data_root, directory_fd, name)
                except FileNotFoundError:
                    if not allow_create:
                        raise RuntimeError(
                            "IM credential key is missing; restore the server secrets backup"
                        ) from None
                temporary = ".im-key-" + uuid4().hex
                fd = os.open(
                    temporary,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=directory_fd,
                )
                try:
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(Fernet.generate_key())
                        stream.flush()
                        os.fsync(stream.fileno())
                    try:
                        # A hard link publishes without replacing another starter's key.
                        os.link(
                            temporary,
                            name,
                            src_dir_fd=directory_fd,
                            dst_dir_fd=directory_fd,
                        )
                    except FileExistsError:
                        pass
                finally:
                    os.unlink(temporary, dir_fd=directory_fd)
                return cls._durable_read(data_root, directory_fd, name)
            finally:
                os.close(directory_fd)
        except (OSError, ValueError, TypeError):
            raise RuntimeError(
                "IM credential key storage is invalid or inaccessible; restore a private valid key file"
            ) from None

    @classmethod
    def _durable_read(cls, data_root, directory_fd, name):
        fd = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd
        )
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
                raise ValueError("key must be a private regular file")
            value = stream.read(45)
            if len(value) != 44:
                raise ValueError("invalid key size")
            vault = cls(value.decode("ascii"))
        # Also fence a concurrent publisher: no caller may save ciphertext
        # before the key's directory entries have reached persistent storage.
        os.fsync(directory_fd)
        root_fd = os.open(data_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(root_fd)
        finally:
            os.close(root_fd)
        return vault

    def seal(self, owner_id, config: FeishuConfig):
        payload = {"owner_id": owner_id, **config.request_payload()}
        encrypted = self._cipher.encrypt(json.dumps(payload).encode()).decode()
        return {
            "app_id": config.app_id,
            "tenant_key": config.tenant_key,
            "credentials_ciphertext": encrypted,
        }

    def open(self, owner_id, stored):
        try:
            payload = json.loads(
                self._cipher.decrypt(stored["credentials_ciphertext"].encode())
            )
            if (
                payload.pop("owner_id") != owner_id
                or payload["app_id"] != stored["app_id"]
                or payload["tenant_key"] != stored["tenant_key"]
            ):
                raise ValueError("credential binding mismatch")
            return FeishuConfig.model_validate(payload)
        except (InvalidToken, ValueError, TypeError, KeyError, AttributeError):
            raise ValueError("IM credentials cannot be decrypted") from None

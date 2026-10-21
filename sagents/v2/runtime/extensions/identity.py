"""Stable extension configuration identities without exposing credential values."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import SecretStr


def config_identity(value: Any) -> str:
    def normalize(candidate: Any, seen: set[int]) -> Any:
        if candidate is None or isinstance(candidate, (str, int, float, bool)):
            return candidate
        if isinstance(candidate, SecretStr):
            return {
                "secret_sha256": hashlib.sha256(
                    candidate.get_secret_value().encode()
                ).hexdigest()
            }
        marker = id(candidate)
        if marker in seen:
            return {"cycle": True}
        if isinstance(candidate, (bytes, bytearray)):
            return {"bytes_sha256": hashlib.sha256(bytes(candidate)).hexdigest()}
        if isinstance(candidate, Path):
            return str(candidate)
        if isinstance(candidate, Mapping):
            seen.add(marker)
            return {
                str(key): normalize(item, seen)
                for key, item in sorted(
                    candidate.items(), key=lambda pair: str(pair[0])
                )
            }
        if isinstance(candidate, (list, tuple)):
            seen.add(marker)
            return [normalize(item, seen) for item in candidate]
        return {
            "type": f"{type(candidate).__module__}.{type(candidate).__qualname__}",
            "id": marker,
        }

    return hashlib.sha256(
        json.dumps(normalize(value, set()), sort_keys=True).encode()
    ).hexdigest()

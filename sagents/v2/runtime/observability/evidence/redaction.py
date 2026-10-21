"""Sanitize diagnostic snapshots independently of their storage backend."""

from __future__ import annotations

from functools import lru_cache
import json
import re
from typing import Any

REDACTED = "[REDACTED]"
_SECRET_KEY = re.compile(
    r"authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|"
    r"secret|credential|cookie|private[_-]?key|^(?:token|headers|env|environment)$",
    re.I,
)
_SECRET_TEXT = re.compile(
    r"(?i)\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+|\bsk-[A-Za-z0-9_-]{6,}|"
    r"\b(?:[A-Za-z0-9]+_)*(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret|token)"
    r"\s*[=:]\s*[\"']?[^\s\"'&,;}]+"
)
_URL_QUERY_SECRET = re.compile(
    r"([?&](?:key|sig|signature|auth|credential)=)[^&\s]+", re.I
)
_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:[A-Z ]*PRIVATE KEY)-----.*?-----END (?:[A-Z ]*PRIVATE KEY)-----",
    re.S,
)
_URL_AUTH = re.compile(r"(\b[a-z][a-z0-9+.-]*://)[^\s/@]+(?::[^\s/@]*)?@", re.I)


def redact(value: Any) -> Any:
    """Redact structured credentials, embedded JSON and common inline secrets.

    Also remove secret values from sibling free-text fields in this snapshot.
    Arbitrary unlabelled secrets in prose cannot be recognized reliably.
    """
    secrets: set[str] = set()

    def collect(item):
        if isinstance(item, dict):
            for key, child in item.items():
                if _SECRET_KEY.search(str(key)):
                    if isinstance(child, str) and len(child) >= 4:
                        secrets.add(child)
                else:
                    collect(child)
        elif isinstance(item, (tuple, list)):
            for child in item:
                collect(child)
        elif isinstance(item, str) and item.lstrip().startswith(("{", "[")):
            try:
                collect(json.loads(item))
            except (ValueError, RecursionError):
                pass

    collect(value)
    ordered_secrets = sorted(secrets, key=len, reverse=True)

    @lru_cache(maxsize=32)
    def clean_text(item: str) -> str:
        # Wire and normalized streams often contain the same multi-MiB text.
        # Reuse its sanitized value within this snapshot only: another snapshot
        # may discover a different set of sibling secrets. Keep the cache bounded.
        if item.lstrip().startswith(("{", "[")):
            try:
                return json.dumps(clean(json.loads(item)), ensure_ascii=False)
            except (ValueError, RecursionError):
                pass
        for secret in ordered_secrets:
            item = item.replace(secret, REDACTED)
        item = _PRIVATE_KEY.sub(REDACTED, _SECRET_TEXT.sub(REDACTED, item))
        item = _URL_QUERY_SECRET.sub(r"\1[REDACTED]", item)
        return _URL_AUTH.sub(r"\1[REDACTED]@", item)

    def clean(item):
        if isinstance(item, dict):
            return {
                str(k): REDACTED if _SECRET_KEY.search(str(k)) else clean(v)
                for k, v in item.items()
            }
        if isinstance(item, (tuple, list)):
            return [clean(v) for v in item]
        if isinstance(item, str):
            return clean_text(item)
        return item

    try:
        return clean(value)
    finally:
        # The recursive closures form a cycle; release large cached strings now
        # rather than waiting for cyclic garbage collection.
        clean_text.cache_clear()

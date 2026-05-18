from typing import Any, Dict, List, Optional


class CLIError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        next_steps: Optional[List[str]] = None,
        debug_detail: Optional[str] = None,
        exit_code: int = 1,
    ) -> None:
        super().__init__(message)
        self.next_steps = list(next_steps or [])
        self.debug_detail = debug_detail
        self.exit_code = exit_code


def trim_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def mask_api_key(value: Optional[str]) -> Optional[str]:
    normalized = trim_optional_text(value)
    if not normalized:
        return None
    if len(normalized) <= 8:
        return "*" * len(normalized)
    return f"{normalized[:4]}...{normalized[-4:]}"


def sanitize_provider_record(record: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = dict(record)
    raw_api_keys = sanitized.get("api_keys") or []
    masked_api_keys = [masked for item in raw_api_keys if (masked := mask_api_key(item))]
    sanitized["api_keys"] = masked_api_keys
    sanitized["api_key_preview"] = masked_api_keys[0] if masked_api_keys else None
    return sanitized


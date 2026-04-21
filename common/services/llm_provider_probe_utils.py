from typing import Optional


def friendly_provider_probe_error(exc: Exception, *, subject: Optional[str] = None) -> str:
    error_str = str(exc or "").strip()
    lower = error_str.lower()
    prefix = f"{subject} " if subject else ""

    if "401" in error_str or "authentication" in lower or "unauthorized" in lower:
        return f"{prefix}authentication failed. Please check the API key.".strip()
    if "quota" in lower or "insufficient_quota" in lower:
        return f"{prefix}quota is insufficient. Please check billing or quota limits.".strip()
    if "model" in lower and ("not found" in lower or "does not exist" in lower):
        return f"{prefix}model is not available. Please check the model name.".strip()
    if "service unavailable" in lower or "503" in error_str or "502" in error_str:
        return f"{prefix}service is temporarily unavailable. Please try again later.".strip()
    if "connection" in lower or "timeout" in lower or "network" in lower:
        return f"{prefix}connection failed. Please check the base URL and network connectivity.".strip()
    if not error_str:
        return f"{prefix}probe failed.".strip()
    if len(error_str) > 180:
        error_str = error_str[:180] + "..."
    return f"{prefix}probe failed: {error_str}".strip()

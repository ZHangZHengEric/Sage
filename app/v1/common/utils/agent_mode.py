from typing import Any, FrozenSet


SUPPORTED_AGENT_MODES: FrozenSet[str] = frozenset({"simple", "fibre", "team"})


def normalize_persisted_agent_mode(value: Any, default: str = "simple") -> str:
    """Normalize stored/imported agent modes without reviving retired modes."""
    normalized = str(value or "").strip().lower()
    if normalized in SUPPORTED_AGENT_MODES:
        return normalized
    return default

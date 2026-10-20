"""Read an explicitly supplied JSON model catalog for opt-in experiments."""

import json
from pathlib import Path


def load_model_provider(catalog: Path, provider: str | None = None) -> dict:
    """Select a named or default provider without consulting application settings."""
    records = json.loads(catalog.read_text())["model_providers"]
    selected = next(
        (
            row
            for row in records
            if (row["name"] == provider if provider else row.get("is_default"))
        ),
        None,
    )
    if selected is None or not selected.get("api_key"):
        raise ValueError("configured provider with credentials is required")
    return selected

"""YAML 1.2-style loader that rejects duplicate mapping keys.

PyYAML ``safe_load`` silently keeps the last duplicate key. Compose-style
strict parsers fail. Sage manifests already reject duplicates; file
validation should use the same rule.
"""

from __future__ import annotations

from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover - yaml should usually be available
    yaml = None


if yaml is not None:

    class UniqueKeyLoader(yaml.SafeLoader):
        pass

    def _construct_mapping(
        loader: UniqueKeyLoader, node: Any, deep: bool = False
    ) -> dict[Any, Any]:
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in mapping:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found duplicate key {key!r}",
                    key_node.start_mark,
                )
            mapping[key] = loader.construct_object(value_node, deep=deep)
        return mapping

    UniqueKeyLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
    )
else:  # pragma: no cover
    UniqueKeyLoader = None  # type: ignore[misc,assignment]


def load_unique_yaml(content: str) -> Any:
    """Load YAML, rejecting duplicate keys in any mapping."""
    if yaml is None:
        raise RuntimeError("PyYAML is not installed")
    return yaml.load(content, Loader=UniqueKeyLoader)

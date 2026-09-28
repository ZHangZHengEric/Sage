"""Safe YAML loading with duplicate explicit keys rejected.

Merge keys retain PyYAML semantics: explicit values override inherited values.
Keep this implementation local to its package so v2 remains independently usable.
"""

from __future__ import annotations

from typing import Any

import yaml


class UniqueKeyLoader(yaml.SafeLoader):
    def flatten_mapping(self, node: yaml.MappingNode) -> None:
        flattened = getattr(self, "_unique_flattened", None)
        if flattened is None:
            flattened = self._unique_flattened = set()
        if id(node) in flattened:
            return
        # Check before flattening: inherited keys may legally be overridden.
        seen: set[Any] = set()
        for key_node, _ in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                key = "<<"
            else:
                key = self.construct_object(key_node, deep=True)
            try:
                duplicate = key in seen
                seen.add(key)
            except TypeError as exc:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found unhashable key",
                    key_node.start_mark,
                ) from exc
            if duplicate:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found duplicate key {key!r}",
                    key_node.start_mark,
                )
        flattened.add(id(node))
        super().flatten_mapping(node)


def load_unique_yaml(content: str) -> Any:
    """Load safe YAML, including anchors and merges, without duplicate keys."""
    return yaml.load(content, Loader=UniqueKeyLoader)

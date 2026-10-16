"""Keep the three public configuration references aligned with strict schemas."""
import ast
from pathlib import Path
import re

import pytest

from sagents.v2.model.catalog import ModelCatalogConfig
from sagents.v2.package.manifest import SageManifest
from sagents.v2.package.manifest.runtime import RuntimeConfig
from sagents.v2.package.strict_yaml import load_unique_yaml

ROOT = Path(__file__).resolve().parents[3]
DOCS = ("sagents-host-development", "sagents-runtime-reference", "sagents-manifest-reference")


@pytest.mark.parametrize("name", DOCS)
def test_reference_examples_and_local_links(name):
    path = ROOT / "docs/zh/architecture" / f"{name}.md"
    text = path.read_text()
    for target in re.findall(r"\]\(([^)]+)\)", text):
        if "://" not in target and not target.startswith("#"):
            assert (path.parent / target.split("#")[0]).exists(), target
    for language, code in re.findall(r"```([^\n]*)\n(.*?)```", text, re.S):
        if language == "python":
            ast.parse(code)
        elif language == "yaml":
            value = load_unique_yaml(code)
            if not isinstance(value, dict):
                continue
            if "schema_version" in value:
                SageManifest.model_validate(value)
            elif "models" in value or "credentials" in value:
                ModelCatalogConfig.model_validate(value)
            elif set(value) <= set(RuntimeConfig.model_fields):
                RuntimeConfig.model_validate(value)

import pytest
import yaml

from sagents.utils.strict_yaml import load_unique_yaml as v1_load
from sagents.v2.package.strict_yaml import load_unique_yaml as v2_load


@pytest.mark.parametrize("load", [v1_load, v2_load])
def test_merges_preserve_explicit_override_and_reusable_anchors(load):
    content = """defaults: &defaults
  image: alpine
  command: default
service: &service
  <<: *defaults
  command: custom
copy:
  <<: *service
"""
    assert load(content) == yaml.safe_load(content)


@pytest.mark.parametrize("load", [v1_load, v2_load])
@pytest.mark.parametrize(
    "content",
    [
        "a: 1\na: 2\n",
        "x: {a: 1, a: 2}",
        "base: &base {a: 1, a: 2}\nx: {<<: *base}",
    ],
)
def test_explicit_duplicates_are_rejected(load, content):
    with pytest.raises(yaml.YAMLError, match="duplicate key"):
        load(content)


@pytest.mark.parametrize("load", [v1_load, v2_load])
def test_safe_recursive_anchors_and_merge_precedence(load):
    result = load("a: &a {self: *a}")
    assert result["a"]["self"] is result["a"]
    content = "a: &a {x: 1}\nb: &b {x: 2}\nc: {<<: [*a, *b]}"
    assert load(content) == yaml.safe_load(content)
    with pytest.raises(yaml.YAMLError):
        load("!!python/object/apply:os.system ['echo unsafe']")

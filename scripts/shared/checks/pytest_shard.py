"""Opt-in deterministic CI sharding; ordinary local pytest runs stay unchanged."""

import hashlib

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--ci-shard", metavar="INDEX/TOTAL", help="Select one 1-based CI shard"
    )


def pytest_configure(config):
    value = config.getoption("--ci-shard")
    if value is None:
        return
    try:
        index, total = map(int, value.split("/"))
        if not 1 <= index <= total:
            raise ValueError
    except (ValueError, TypeError):
        raise pytest.UsageError(
            "--ci-shard must be INDEX/TOTAL with 1 <= INDEX <= TOTAL"
        ) from None
    config._sage_ci_shard = (index - 1, total)


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    shard = getattr(config, "_sage_ci_shard", None)
    if shard is None:
        return
    index, total = shard
    selected, deselected = [], []
    for item in items:
        digest = hashlib.sha256(item.nodeid.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:8], "big") % total
        (selected if bucket == index else deselected).append(item)
    items[:] = selected
    config.hook.pytest_deselected(items=deselected)

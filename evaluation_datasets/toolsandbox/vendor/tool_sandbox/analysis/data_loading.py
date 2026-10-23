# For licensing see accompanying LICENSE file.
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
"""Load data produced by the tool sandbox."""

import json
import pathlib
from typing import Any, cast

import polars as pl


def extract_scenario_results(results: dict[Any, Any]) -> pl.DataFrame:
    """Extract the per-scenario results from a result summary.

    Args:
        results:  A dictionary containing the data of a `result_summary.json` file.

    Returns:
        A data frame with the per-scenario results.
    """
    # The `strict=False` is necessary because the milestone mapping values mix integers
    # and floats, e.g.:
    #   "milestone_mapping": {
    #       "0": [
    #           5,
    #           1.0
    #       ],
    #       ...
    # We set `infer_schema_length` so that polars scans the complete data before
    # deciding which data types to use. This was needed for the `exceptions` column
    # where the value will be `None` or a string if there was an exception in cases
    # where only some of the later scenarios encountered exceptions.
    df = pl.DataFrame(
        results["per_scenario_results"],
        strict=False,
        infer_schema_length=None,
    )
    return df


def load_result_summary(path: pathlib.Path) -> dict[str, Any]:
    """Load the contents of a `result_summary.json` file."""
    return cast(dict[str, Any], json.load(path.open("rt")))


def get_scenario_artifacts_path(
    result_summary_path: pathlib.Path, *, scenario_name: str
) -> pathlib.Path:
    """Get the path to the artifacts for a specific scenario."""
    assert (
        result_summary_path.suffix == ".json"
    ), f"Expected the path to the `result_summary.json` file, but got '{result_summary_path}'."
    return result_summary_path.parent / "trajectories" / scenario_name


def get_scenario_pretty_print_path(
    result_summary_path: pathlib.Path, *, scenario_name: str
) -> pathlib.Path:
    """Get the path to the `pretty_print.txt` file for a specific scenario."""
    return (
        get_scenario_artifacts_path(result_summary_path, scenario_name=scenario_name)
        / "pretty_print.txt"
    )

# For licensing see accompanying LICENSE file.
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
"""Utility functions for analyzing data produced by the tool sandbox."""

from typing import Any

import polars as pl


def extract_meta_stats(scenarios_df: pl.DataFrame) -> pl.DataFrame:
    """Extract metadata information from the scenario results."""
    num_scenarios = len(scenarios_df)
    num_exceptions = scenarios_df.get_column("traceback").count()
    total_num_turn_counts = scenarios_df.get_column("turn_count").sum()
    df = pl.DataFrame(
        {
            "num_scenarios": num_scenarios,
            "num_exceptions": num_exceptions,
            "total_num_turn_counts": total_num_turn_counts,
            "normalized_total_num_turn_counts": total_num_turn_counts / num_scenarios,
        }
    )
    return df


def extract_aggregated_stats(results: dict[Any, Any]) -> pl.DataFrame:
    """Extract the aggregated statistics from the given results."""
    # The aggregated results look like this:
    # "SINGLE_TOOL_CALL": {
    #     "similarity": 0.891803532509439,
    #     "turn_count": 6.225563909774436
    # },
    # "SINGLE_USER_TURN": {
    #     "similarity": 0.8473655329053461,
    #     "turn_count": 9.506493506493506
    # },
    # ...
    # When converting the dict to a dataframe we have a column for each category and
    # each column stores a struct:
    #    | SINGLE_TOOL_CALL	   | SINGLE_USER_TURN	 | ...
    #    | struct[2]	       | struct[2]	         |
    #    | {0.891804,6.225564} | {0.847366,9.506494} |
    # We want this layout:
    #    | category           | similarity | turn_count |
    #    | str	              | f64	       | f64        |
    #    | "SINGLE_TOOL_CALL" | 0.891804   | 6.225564   |
    #    | "SINGLE_USER_TURN" | 0.847366   | 9.506494   |
    #    | ...                |            |            |
    df = pl.DataFrame(results["category_aggregated_results"])
    df = df.transpose(include_header=True, header_name="category")
    df = df.unnest("column_0")
    return df

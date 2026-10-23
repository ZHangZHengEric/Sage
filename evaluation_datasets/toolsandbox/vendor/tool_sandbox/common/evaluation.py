# For licensing see accompanying LICENSE file.
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
import heapq
import itertools
import json
import math
from collections import OrderedDict
from copy import deepcopy
from logging import getLogger
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple, Union, cast

import networkx
import numpy as np
import polars as pl
from attrs import Factory, define, field
from polars.exceptions import SchemaError
from rouge_score import rouge_scorer  # type: ignore
from scipy.optimize import linear_sum_assignment  # type: ignore
from typing_extensions import Protocol

from tool_sandbox.common.execution_context import (
    DatabaseNamespace,
    ExecutionContext,
    RoleType,
)
from tool_sandbox.common.tool_trace_extractors import ToolTraceExtractorType
from tool_sandbox.common.utils import NOT_GIVEN, all_logging_disabled, is_close

LOGGER = getLogger(__name__)


class ColumnSimilarityMeasureType(Protocol):
    """Callable type def for column similarity measure functions

    Each similarity measure takes a dataframe, column to calculate similarity on and value,
    to return a Dataframe representing similarity between each row in the dataframe and the value
    Similarities are [0, 1] real values.
    """

    def __call__(
        self,
        dataframe: pl.DataFrame,
        column_name: str,
        value: Any,
        atol_dict: Optional[dict[str, float]] = None,
    ) -> pl.DataFrame: ...


def column_exact_match_similarity(
    dataframe: pl.DataFrame,
    column_name: str,
    value: Any,
    atol_dict: Optional[dict[str, float]] = None,
) -> pl.DataFrame:
    """A 0/1 similarity based on exact match.

    Args:
        dataframe:      Dataframe to calculate similarity on
        column_name:    Column name to compare
        value:          Value the column should compare against
        atol_dict:      Absolute tolerance for each argument

    Returns:
        A Dataframe containing similarity score. 0 for no match, 1 for match
    """
    if value is not None:
        return dataframe.select(
            pl.col(column_name).eq(value).cast(pl.Float32).alias("similarity")
        )
    else:
        return dataframe.select(
            pl.col(column_name).is_null().cast(pl.Float32).alias("similarity")
        )


def column_close_similarity(
    dataframe: pl.DataFrame,
    column_name: str,
    value: Any,
    atol_dict: Optional[dict[str, float]] = None,
) -> pl.DataFrame:
    """A 0/1 similarity based on how close values are.

    Only works on int / float, and requires atol_dict.

    Args:
        dataframe:      Dataframe to calculate similarity on
        column_name:    Column name to compare
        value:          Value the column should compare against
        atol_dict:      Absolute tolerance for each argument

    Returns:
        A Dataframe containing similarity score. 0 for no match, 1 for match
    """
    assert isinstance(value, (int, float)) and atol_dict is not None

    def check_close(x: tuple[Optional[str]]) -> float:
        """UDF checking if x [0] is close to value

        Args:
            x:  single value tuple containing a tool trace

        Returns:
            0 / 1 match score
        """
        if is_close(value=value, reference=x[0], atol=atol_dict.get(column_name, None)):
            return 1
        return 0

    return (
        dataframe.select(pl.col(column_name))
        .map_rows(function=check_close, return_dtype=pl.Float32)
        .select(pl.col("map").alias("similarity"))
    )


def column_one_similarity(
    dataframe: pl.DataFrame,
    column_name: str,
    value: Any,
    atol_dict: Optional[dict[str, float]] = None,
) -> pl.DataFrame:
    """A similarity that always returns 1 as similarity score

    Args:
        dataframe:      Dataframe to calculate similarity on
        column_name:    Column name to compare
        value:          Value the column should compare against
        atol_dict:      Absolute tolerance for each argument

    Returns:
        A Dataframe containing similarity score. 0 for no match, 1 for match
    """
    return dataframe.with_columns(pl.lit(1.0).alias("similarity")).select("similarity")


def column_contains_similarity(
    dataframe: pl.DataFrame,
    column_name: str,
    value: Any,
    atol_dict: Optional[dict[str, float]] = None,
) -> pl.DataFrame:
    """A 0/1 similarity whether the value is contained in column value string

    Args:
        dataframe:      Dataframe to calculate similarity on
        column_name:    Column name to compare, must contain string
        value:          Value the column should compare against, must be string value
        atol_dict:      Absolute tolerance for each argument

    Returns:
        A Dataframe containing similarity score. 0 if the column value do not contain target value, 1 if it does
    """
    return dataframe.select(
        pl.col(column_name)
        .str.contains_any([value])
        .cast(pl.Float32)
        .alias("similarity")
    )


def column_tool_trace_exact_match_similarity(
    dataframe: pl.DataFrame,
    column_name: str,
    value: Any,
    atol_dict: Optional[dict[str, float]] = None,
) -> pl.DataFrame:
    """A 0/1 similarity whether a tool trace matches a provided trace.

    Function name and argument in provided trace is always matched. Arguments not provided are ignored

    Provided trace can be a list of possible traces, in which case a match is found
    if any of the provided traces matches.

    Args:
        dataframe:      Dataframe to calculate similarity on
        column_name:    Column name to compare, must contain string
        value:          Json dumped 1 or a list of tool traces.
        atol_dict:      Absolute tolerance for each argument

    Returns:
        A Dataframe containing similarity score. 0 if the column value do not contain target value, 1 if it does
    """
    trace: Union[dict[str, Any], list[dict[str, Any]]] = json.loads(value)
    # Normalize into a list of possible golden traces
    golden_traces: list[dict[str, Any]] = (
        [trace] if not isinstance(trace, Sequence) else list(trace)
    )

    def match_trace(x: tuple[Optional[str]]) -> float:
        """UDF calculating trace matching score

        Args:
            x:  single value tuple containing a tool trace

        Returns:
            0 / 1 match score
        """
        if x[0] is None:
            return 0
        # If any trace matches any golden trace, return 1
        for golden_trace in golden_traces:
            for tool_trace_json in x[0]:
                tool_trace = json.loads(tool_trace_json)
                if tool_trace["tool_name"] == golden_trace["tool_name"] and all(
                    is_close(
                        tool_trace["arguments"].get(argument_name, NOT_GIVEN),
                        golden_trace["arguments"][argument_name],
                        atol=atol_dict.get(argument_name, None)
                        if atol_dict is not None
                        else None,
                    )
                    for argument_name in golden_trace["arguments"]
                ):
                    return 1
        return 0

    return (
        dataframe.select(pl.col(column_name))
        .map_rows(function=match_trace, return_dtype=pl.Float32)
        .select(pl.col("map").alias("similarity"))
    )


def column_rouge_l_similarity(
    dataframe: pl.DataFrame,
    column_name: str,
    value: Any,
    atol_dict: Optional[dict[str, float]] = None,
) -> pl.DataFrame:
    """Similarity defined by ROUGE score. Only applicable for string values

    Args:
        dataframe:      Dataframe to calculate similarity on
        column_name:    Column name to compare, must contain string
        value:          Value the column should compare against, must be string value
        atol_dict:      Absolute tolerance for each argument

    Returns:
        A Dataframe containing similarity score.
    """
    with all_logging_disabled():
        scorer = rouge_scorer.RougeScorer(["rougeL"], use_stemmer=True)

        def rouge_l_score(x: tuple[str]) -> float:
            """UDF calculating rouge L

            Args:
                x:  single value tuple containing the column in question

            Returns:
                float rouge L f score
            """
            return cast(
                float, scorer.score(target=value, prediction=x[0])["rougeL"].fmeasure
            )

        return (
            dataframe.select(pl.col(column_name))
            .map_rows(function=rouge_l_score, return_dtype=pl.Float32)
            .select(pl.col("map").alias("similarity"))
        )


class SnapshotSimilarityMeasureType(Protocol):
    """Callable type def for snapshot similarity measure functions

    Each similarity measure takes a snapshot, target dataframe, column similarities and reference snapshot
    to return a float representing similarity between snapshot and other specified constraints
    Similarities are [0, 1] real values.
    """

    def __call__(
        self,
        snapshot: pl.DataFrame,
        target_dataframe: Optional[pl.DataFrame] = None,
        column_similarities: Optional[Dict[str, ColumnSimilarityMeasureType]] = None,
        reference_snapshot: Optional[pl.DataFrame] = None,
        **kwargs: Union[str, ToolTraceExtractorType],
    ) -> float: ...


def snapshot_similarity(
    snapshot: pl.DataFrame,
    target_dataframe: Optional[pl.DataFrame] = None,
    column_similarities: Optional[Dict[str, ColumnSimilarityMeasureType]] = None,
    reference_snapshot: Optional[pl.DataFrame] = None,
    **kwargs: Union[str, ToolTraceExtractorType],
) -> float:
    """Measures the similarity between each database snapshot and a target_dataframe.

        1. If the number of rows, or column names doesn't match, similarity is always 0
        2. Within each snapshot, calculate a similarity between each row in the target and each row in the snapshot
            2.1 Row-wise similarity is determined by the geo mean of column similarities
            2.2 Only columns provided in target_dataframe was considered
        3. Find a 1 to 1 mapping between snapshot rows and target rows that maximizes geo mean of row similarities.
            Said geo mean is the snapshot similarity

    Args:
        snapshot:                   The dataframe snapshot to calculate similarity for
        target_dataframe:           The dataframe to calculate similarity with
        column_similarities:        A dictionary of column name to column-wise similarity measure
        reference_snapshot:         Not utilized by this similarity

    Returns:
        A [0, 1] similarity score between target_dataframe and snapshot
    """
    assert target_dataframe is not None and column_similarities is not None
    # Check for row number and columns
    if snapshot.select(pl.len())["len"][0] != target_dataframe.select(pl.len())["len"][
        0
    ] or set(target_dataframe.columns) - set(snapshot.columns):
        return 0.0
    # Create N * N cost matrix (- log similarity). This ensures when assignment cost is minimized
    # through hungarian algorithm, row-wise geo metric mean of similarity is maximized
    cost_matrix: list[np.ndarray[Any, np.dtype[np.float64]]] = []
    for row in target_dataframe.to_dicts():
        # - log similarity and column-wise geo mean
        column_cost_df = pl.concat(
            [
                column_similarities[column_name](
                    dataframe=snapshot,
                    column_name=column_name,
                    value=value,
                ).select(-pl.col("similarity").log().alias(f"similarity_{i}"))
                for i, (column_name, value) in enumerate(row.items())
            ],
            how="horizontal",
        )
        cost_matrix.append(
            column_cost_df.select(
                pl.mean_horizontal(*column_cost_df.columns).alias("mean")
            )["mean"].to_numpy()
        )
    numpy_cost_matrix = np.stack(cost_matrix, axis=0)
    try:
        # Solve for assignment that minimizes cost matrix
        row_ind, col_ind = linear_sum_assignment(numpy_cost_matrix)
    except ValueError:
        # cost matrix is infeasible (always results in inf). Return 0
        return 0
    # Calculate similarity
    return cast(float, np.exp(-numpy_cost_matrix[row_ind, col_ind].mean()).tolist())


def addition_similarity(
    snapshot: pl.DataFrame,
    target_dataframe: Optional[pl.DataFrame] = None,
    column_similarities: Optional[Dict[str, ColumnSimilarityMeasureType]] = None,
    reference_snapshot: Optional[pl.DataFrame] = None,
    **kwargs: Union[str, ToolTraceExtractorType],
) -> float:
    """Measures the similarity between each database snapshot and a target_dataframe, if the snapshot is supposed to
    be derived from adding target_dataframe onto reference_snapshot

        1. If snapshot does not fully contain reference_snapshot, similarity is always 0
        2. If it does, the anti join of the two is compared against target_dataframe using snapshot_similarity

    Args:
        snapshot:                   The dataframe snapshot to calculate similarity for
        target_dataframe:           The dataframe to calculate similarity with
        column_similarities:        A dictionary of column name to column-wise similarity measure
        reference_snapshot:         When similarity is 1,
                                    snapshot should be the result of adding target_dataframe into reference_snapshot

    Returns:
        A [0, 1] similarity score between target_dataframe and snapshot
    """
    assert (
        target_dataframe is not None
        and column_similarities is not None
        and reference_snapshot is not None
    )
    # Drop sandbox_message_index
    # Fill null with zero to prevent join failure
    snapshot = snapshot.drop("sandbox_message_index").fill_null(strategy="zero")
    reference_snapshot = reference_snapshot.drop("sandbox_message_index").fill_null(
        strategy="zero"
    )
    target_dataframe = target_dataframe.fill_null(strategy="zero")
    if (
        reference_snapshot.select(pl.len())["len"][0]
        != snapshot.join(reference_snapshot, on=snapshot.columns, how="inner").select(
            pl.len()
        )["len"][0]
    ):
        return 0
    return snapshot_similarity(
        snapshot.join(reference_snapshot, on=snapshot.columns, how="anti"),
        target_dataframe=target_dataframe,
        column_similarities=column_similarities,
        reference_snapshot=reference_snapshot,
    )


def removal_similarity(
    snapshot: pl.DataFrame,
    target_dataframe: Optional[pl.DataFrame] = None,
    column_similarities: Optional[Dict[str, ColumnSimilarityMeasureType]] = None,
    reference_snapshot: Optional[pl.DataFrame] = None,
    **kwargs: Union[str, ToolTraceExtractorType],
) -> float:
    """Measures the similarity between each database snapshot and a target_dataframe, if the snapshot is supposed to
    be derived from removing target_dataframe from reference_snapshot

        This can be implemented by swapping snapshot, reference_snapshot and calling addition_similarity

    Args:
        snapshot:                   The dataframe snapshot to calculate similarity for
        target_dataframe:           The dataframe to calculate similarity with
        column_similarities:        A dictionary of column name to column-wise similarity measure
        reference_snapshot:         When similarity is 1,
                                    snapshot should be the result of removing target_dataframe from reference_snapshot

    Returns:
        A [0, 1] similarity score between target_dataframe and snapshot
    """
    assert (
        target_dataframe is not None
        and column_similarities is not None
        and reference_snapshot is not None
    )
    return addition_similarity(
        snapshot=reference_snapshot,
        target_dataframe=target_dataframe,
        column_similarities=column_similarities,
        reference_snapshot=snapshot,
    )


def update_similarity(
    snapshot: pl.DataFrame,
    target_dataframe: Optional[pl.DataFrame] = None,
    column_similarities: Optional[Dict[str, ColumnSimilarityMeasureType]] = None,
    reference_snapshot: Optional[pl.DataFrame] = None,
    **kwargs: Union[str, ToolTraceExtractorType],
) -> float:
    """Measures the similarity between each database snapshot and a target_dataframe, if the snapshot is supposed to
    be derived from updating the same of number entries from reference_snapshot into target_dataframe

        1. If snapshot and reference_snapshot doesn't match in row count, similarity is always 0
        2. If the number of different rows between snapshot and reference_snapshot doesn't match target_dataframe
            similarity is always 0
        2. If it does, the anti join of the two is compared against target_dataframe using snapshot_similarity

    Args:
        snapshot:                   The dataframe snapshot to calculate similarity for
        target_dataframe:           The dataframe to calculate similarity with
        column_similarities:        A dictionary of column name to column-wise similarity measure
        reference_snapshot:         When similarity is 1,
                                    snapshot should be the result of adding target_dataframe into reference_snapshot

    Returns:
        A [0, 1] similarity score between target_dataframe and snapshot
    """
    assert (
        target_dataframe is not None
        and column_similarities is not None
        and reference_snapshot is not None
    )
    # Drop sandbox_message_index
    # Fill null with zero to prevent join failure
    snapshot = snapshot.drop("sandbox_message_index").fill_null(strategy="zero")
    reference_snapshot = reference_snapshot.drop("sandbox_message_index").fill_null(
        strategy="zero"
    )
    target_dataframe = target_dataframe.fill_null(strategy="zero")
    if (
        reference_snapshot.select(pl.len())["len"][0]
        != snapshot.select(pl.len())["len"][0]
    ):
        return 0
    return snapshot_similarity(
        snapshot.join(reference_snapshot, on=snapshot.columns, how="anti"),
        target_dataframe=target_dataframe,
        column_similarities=column_similarities,
        reference_snapshot=reference_snapshot,
    )


def tool_trace_dependant_similarity(
    snapshot: pl.DataFrame,
    target_dataframe: Optional[pl.DataFrame] = None,
    column_similarities: Optional[Dict[str, ColumnSimilarityMeasureType]] = None,
    reference_snapshot: Optional[pl.DataFrame] = None,
    **kwargs: Union[str, ToolTraceExtractorType],
) -> float:
    """A special similarity only intended to be used for SANDBOX database. Allows one to extract values
    from the tool_trace in reference_snapshot, and fill into target_dataframe. Extractors are allowed to return
    multiple "normalized" version of extracted value, a similarity will be calculated for each, and return the max.

    Args:
        snapshot:               The dataframe snapshot to calculate similarity for
        target_dataframe:       The dataframe to calculate similarity with. Either content or tool_trace column is
                                incomplete, requires value extracted from reference_snapshot to fill in
        column_similarities:    A dictionary of column name to column-wise similarity measure
        reference_snapshot:     Contains tool_trace we wish to extract value from
        **kwargs:               Should contain keyword argument "fill_to", indicating which column to fill extracted
                                value into. Can only choose from Literal["tool_trace", "content"].
                                    - In the case of "tool_trace", extracted values are supplied as kwargs into tool
                                        trace arguments
                                    - In the case of "content", extracted values are supplied to str.format
                                Should contain keyword argument "extractor" of type ToolTraceExtractorType.
                                An extractor function taking 1 tool trace as input, and returns a list of dictionary,
                                containing multiple normalized form of extracted values.
                                Each normalized extracted value will be provided to target_dataframe,
                                calculate similarity, and the max of all normalized forms is taken as final similarity.

    Returns:

    """
    assert (
        target_dataframe is not None
        and column_similarities is not None
        and reference_snapshot is not None
    )
    # Check schema to make sure we are working with SANDBOX database. Allows sandbox_message_index to be dropped
    for current_snapshot in (snapshot, reference_snapshot):
        schema = {**current_snapshot.schema}
        # Add sandbox_message_index if dropped
        schema.update(
            {
                "sandbox_message_index": ExecutionContext.dbs_schemas[
                    DatabaseNamespace.SANDBOX
                ]["sandbox_message_index"]
            }
        )
        if (
            schema != ExecutionContext.dbs_schemas[DatabaseNamespace.SANDBOX]
            or current_snapshot.select(pl.len())["len"][0] != 1
        ):
            raise SchemaError(
                "tool_trace_dependant_similarity can only be used with SANDBOX database with only 1 row"
            )
    # Check kwargs
    if "fill_to" not in kwargs:
        raise KeyError(
            "fill_to kwarg of type Literal['tool_trace', 'content'] "
            "must be provided to tool_trace_dependant_similarity. "
        )
    fill_to = cast(Literal["tool_trace", "content"], kwargs["fill_to"])
    if fill_to not in ("tool_trace", "content"):
        raise ValueError("fill_to must be of type Literal['tool_trace', 'content']")
    if "extractor" not in kwargs:
        raise KeyError(
            "extractor kwarg of type ToolTraceExtractorType "
            "must be provided to tool_trace_dependant_similarity. "
        )
    extractor = cast(ToolTraceExtractorType, kwargs["extractor"])
    # Start extraction
    if reference_snapshot["tool_trace"][0] is None:
        return 0
    tool_traces = cast(
        List[Dict[Literal["tool_name", "arguments", "result"], Any]],
        [json.loads(x) for x in reference_snapshot["tool_trace"][0]],
    )
    # Extract values from all tool traces in snapshot
    extracted_values: List[Dict[str, Any]] = []
    for tool_trace in tool_traces:
        try:
            extracted_values.extend(extractor(tool_trace))
        except (KeyError, IndexError, TypeError, ValueError):
            pass
    # Find the best possible matches
    similarity: float = 0.0
    try:
        for extracted_value in extracted_values:
            # When filling in extracted_value, we consider the following options:
            #   1. Any extracted_value can fill in any trace
            #   2. If an extracted_value overrides an existing kwarg in the trace,
            #       consider the existing kwarg as well.
            if fill_to == "tool_trace":
                trace: Union[dict[str, Any], list[dict[str, Any]]] = json.loads(
                    target_dataframe["tool_trace"][0]
                )
                # Normalize into a list of possible candidate traces
                candidate_traces: list[dict[str, Any]] = (
                    [trace] if not isinstance(trace, Sequence) else list(trace)
                )
                filled_traces: list[dict[str, Any]] = []
                # Filling extracted value to all candidate traces
                for candidate_trace in candidate_traces:
                    # Prefer arguments in extracted_value
                    current_trace = deepcopy(candidate_trace)
                    current_trace["arguments"].update(extracted_value)
                    filled_traces.append(current_trace)
                    # Prefer arguments in candidate_trace
                    current_trace = deepcopy(candidate_trace)
                    extracted_arguments = deepcopy(extracted_value)
                    extracted_arguments.update(current_trace["arguments"])
                    current_trace["arguments"] = extracted_arguments
                    filled_traces.append(current_trace)
                similarity = max(
                    similarity,
                    snapshot_similarity(
                        snapshot=snapshot,
                        target_dataframe=target_dataframe.with_columns(
                            pl.lit(json.dumps(filled_traces, ensure_ascii=False)).alias(
                                "tool_trace"
                            )
                        ),
                        column_similarities=column_similarities,
                        reference_snapshot=reference_snapshot,
                    ),
                )
            elif fill_to == "content":
                candidate_content = cast(str, target_dataframe["content"][0])
                candidate_content = candidate_content.format(**extracted_value)
                similarity = max(
                    similarity,
                    snapshot_similarity(
                        snapshot=snapshot,
                        target_dataframe=target_dataframe.with_columns(
                            pl.lit(candidate_content).alias("content")
                        ),
                        column_similarities=column_similarities,
                        reference_snapshot=reference_snapshot,
                    ),
                )
    except (IndexError, KeyError):
        return 0.0
    return similarity


def guardrail_similarity(
    snapshot: pl.DataFrame,
    target_dataframe: Optional[pl.DataFrame] = None,
    column_similarities: Optional[Dict[str, ColumnSimilarityMeasureType]] = None,
    reference_snapshot: Optional[pl.DataFrame] = None,
    **kwargs: Union[str, ToolTraceExtractorType],
) -> float:
    """Similarity which ensures snapshot is identical to reference. Returns 0 otherwise

    Args:
        snapshot:                   The dataframe snapshot to calculate similarity for
        target_dataframe:           Not utilized by this similarity
        column_similarities:        Not utilized by this similarity
        reference_snapshot:         When similarity is 1,
                                    snapshot identical to reference_snapshot

    Returns:
        A [0, 1] similarity score between target_dataframe and snapshot
    """
    assert reference_snapshot is not None
    return float(snapshot.equals(reference_snapshot))


# Default similarity measures for each column
_default_dbs_column_similarities: dict[str, dict[str, ColumnSimilarityMeasureType]] = {
    DatabaseNamespace.SANDBOX: {
        "sandbox_message_index": column_exact_match_similarity,
        "sender": column_exact_match_similarity,
        "recipient": column_exact_match_similarity,
        "content": column_rouge_l_similarity,
        "openai_tool_call_id": column_one_similarity,
        "openai_function_name": column_one_similarity,
        "conversation_active": column_exact_match_similarity,
        "tool_call_exception": column_one_similarity,
        "tool_trace": column_tool_trace_exact_match_similarity,
        "visible_to": column_exact_match_similarity,
    },
    DatabaseNamespace.SETTING: {
        "sandbox_message_index": column_exact_match_similarity,
        "device_id": column_exact_match_similarity,
        "cellular": column_exact_match_similarity,
        "wifi": column_exact_match_similarity,
        "location_service": column_exact_match_similarity,
        "low_battery_mode": column_exact_match_similarity,
        "latitude": column_exact_match_similarity,
        "longitude": column_exact_match_similarity,
    },
    DatabaseNamespace.CONTACT: {
        "sandbox_message_index": column_exact_match_similarity,
        "person_id": column_exact_match_similarity,
        "name": column_exact_match_similarity,
        "phone_number": column_exact_match_similarity,
        "relationship": column_rouge_l_similarity,
        "is_self": column_exact_match_similarity,
    },
    DatabaseNamespace.MESSAGING: {
        "sandbox_message_index": column_exact_match_similarity,
        "message_id": column_exact_match_similarity,
        "sender_person_id": column_exact_match_similarity,
        "sender_phone_number": column_exact_match_similarity,
        "recipient_person_id": column_exact_match_similarity,
        "recipient_phone_number": column_exact_match_similarity,
        "content": column_rouge_l_similarity,
        "creation_timestamp": column_exact_match_similarity,
    },
    DatabaseNamespace.REMINDER: {
        "sandbox_message_index": column_exact_match_similarity,
        "reminder_id": column_exact_match_similarity,
        "content": column_rouge_l_similarity,
        "creation_timestamp": column_exact_match_similarity,
        "reminder_timestamp": column_exact_match_similarity,
        "latitude": column_exact_match_similarity,
        "longitude": column_exact_match_similarity,
    },
}


@define
class SnapshotConstraint:
    """Constraints between 2 snapshots. These are (optionally) pairwise similarity constraints that are
    applied between 2 milestones and their corresponding snapshots. This constraint should provide a [0, 1]
    constraint score.

    """

    # Which database should this constraint be applied to
    database_namespace: DatabaseNamespace
    # Snapshot constraint function
    snapshot_constraint: SnapshotSimilarityMeasureType
    # Index to the reference milestone node index. The snapshot this milestone maps to is supplied to.
    # Since SnapshotConstraint always lives in a milestone. The milestone's own index is implied
    reference_milestone_node_index: Optional[int] = None
    # Target dataframe to compare against
    target_dataframe: Optional[pl.DataFrame] = None
    # Column similarity measure. if None, uses default values defined in Evaluation
    column_similarity_measure: Optional[Dict[str, ColumnSimilarityMeasureType]] = None

    def __attrs_post_init__(self) -> None:
        """Fill in default values for column_similarity_measure

        Returns:

        """
        column_similarity_measure: Dict[str, ColumnSimilarityMeasureType] = deepcopy(
            _default_dbs_column_similarities[self.database_namespace]
        )
        # When similarity measure is provided, override default for provided entries
        if self.column_similarity_measure is not None:
            column_similarity_measure.update(self.column_similarity_measure)
        self.column_similarity_measure = column_similarity_measure


@define
class Milestone:
    """Constraints defining a milestone"""

    # A List of similarity constraints. All these constraints are applied to databases of the same sandbox_message_index
    snapshot_constraints: List[SnapshotConstraint]
    # One can enforce some database should not have changed comparing to reference. These constraints are called
    # guardrails. By default, when guardrail_database_list is None, guardrail is applied to all non
    # SANDBOX databases that doesn't have an associated SnapshotConstraint in this milestone.
    # Reference is chosen from all reference milestones listed in snapshot_constraints
    guardrail_database_list: Optional[List[DatabaseNamespace]] = None
    # Alternative way to specify guardrail. database listed here will be excluded. Cannot be set with
    # guardrail_database_list at the same time
    guardrail_database_exclusion_list: Optional[List[DatabaseNamespace]] = None

    def __attrs_post_init__(self) -> None:
        """Set default guardrail_database_list

        Returns:

        """
        if (
            self.guardrail_database_list is not None
            and self.guardrail_database_exclusion_list is not None
        ):
            raise ValueError(
                "Only one of guardrail_database_list, guardrail_database_exclusion_list should be set"
            )
        if self.guardrail_database_list is None:
            self.guardrail_database_list = cast(
                List[DatabaseNamespace], list(DatabaseNamespace)
            )
        if self.guardrail_database_exclusion_list is not None:
            self.guardrail_database_list = [
                x
                for x in self.guardrail_database_list
                if x not in self.guardrail_database_exclusion_list
            ]


class Minefield(Milestone):
    """Minefields are the opposite of Milestones.

    A Minefield defines conversation / world state that absolutely shouldn't happen
    in a trajectory. Minefields form a minefield_dag. If a minefield_dag matched with non-zero
    similarity, the entire trajectory is nullified.

    This is particularly useful for Insufficient Information category, where certain tools should
    never be called.
    """


@define
class CachedSimilarityCalculator:
    """Given a fully played out execution_context, attempt to calculate & cache similarity scores

    Each SnapshotConstraint depends on two snapshots, the current snapshot and a reference snapshot.
    Remember that only when database was updated do we create a new snapshot. Meaning for each database,
    snapshot index can be divided into buckets where snapshot within said bucket does not change.
    For a SnapshotConstraint, for all combinations of current snapshot and a reference snapshot that falls into
    the same bucket combination, similarity score should be the same. We take advantage of this to build a cache
    system for SnapshotConstraint
    """

    # The execution_context containing full rollout
    execution_context: ExecutionContext
    # Milestone / Minefield to calculate similarity for
    milestone: Milestone
    # Bucket boundary, constructed in post_init. Adjacent pairs of indices form a left inclusive right exclusive bucket
    database_bucket_boundary: Dict[DatabaseNamespace, List[int]] = field(init=False)
    # Cache for SnapshotConstraint
    snapshot_constraint_similarity_cache: List[
        Dict[Tuple[int, Optional[int]], float]
    ] = field(init=False)
    # Index of the first snapshot, contains initial world state. reference_milestone_node_index == -1 refers to this.
    first_user_message_snapshot_index: int = field(init=False)

    def __attrs_post_init__(self) -> None:
        """Build similarity cache for each SnapshotConstraint within milestone

        Returns:

        """
        # Construct bucket boundary according to execution context
        database_bucket_boundary: Dict[DatabaseNamespace, List[int]] = {}
        for database_namespace in DatabaseNamespace:
            # Make sure not to drop headguard to ensure empty snapshots are represented
            database = self.execution_context.get_database(
                namespace=database_namespace,
                get_all_history_snapshots=True,
                drop_sandbox_message_index=False,
                drop_headguard=False,
            )
            database_bucket_boundary[database_namespace] = (
                database.select(pl.col("sandbox_message_index"))
                .unique()["sandbox_message_index"]
                .to_list()
            )
        self.database_bucket_boundary = database_bucket_boundary
        # Initialize cache
        self.snapshot_constraint_similarity_cache = [
            {} for _ in range(len(self.milestone.snapshot_constraints))
        ]
        # Initialize according to execution context
        self.first_user_message_snapshot_index: int = (
            self.execution_context.first_user_sandbox_message_index
        )

    def calculate_similarity(
        self,
        current_snapshot_index: int,
        milestone_snapshot_mapping: Dict[int, Tuple[int, float]],
    ) -> float:
        """Calculate milestone similarity given the current snapshot index and previous mappings

        Caching happens automatically. Calculates Geometric mean of all SnapshotConstraint similarities.
        Guardrail constraints are an exception. If all guardrail constraint similarities are 1, they are all excluded
        from the mean, in order not to meaninglessly bump up similarity scoring.

        Args:
            current_snapshot_index:         The snapshot this current milestone maps to
            milestone_snapshot_mapping:     A dict of milestone -> snapshot mapping of all previous snapshots

        Returns:
            Similarity score for the current milestone given existing mapping
        """
        similarity: float = 1
        similarity_count: int = 0
        # -1 maps to first snapshot by default. Add entry for None -> None to help with cases where
        # reference snapshot doesn't exist (reference_milestone_node_index == None)
        # Mypy does not allow assigning a `dict[K, V]` to a variable of type
        # `dict[Optional[K], V]` so we use a cast.
        patched_snapshot_mapping = {
            **cast(
                dict[Optional[int], tuple[Optional[int], float]],
                milestone_snapshot_mapping,
            ),
            -1: (self.first_user_message_snapshot_index, 0),
            None: (None, 0),
        }
        for constraint, cache in zip(
            self.milestone.snapshot_constraints,
            self.snapshot_constraint_similarity_cache,
        ):
            # Find snapshots
            reference_snapshot_index, _ = patched_snapshot_mapping[
                constraint.reference_milestone_node_index
            ]
            # Create cache key. (current_snapshot_index, reference_snapshot_index)
            cache_key = (current_snapshot_index, reference_snapshot_index)
            if cache_key not in cache:
                current_snapshot, reference_snapshot = (
                    self.execution_context.get_database(
                        namespace=constraint.database_namespace,
                        sandbox_message_index=current_snapshot_index,
                    ),
                    self.execution_context.get_database(
                        namespace=constraint.database_namespace,
                        sandbox_message_index=reference_snapshot_index,
                    )
                    if reference_snapshot_index is not None
                    else None,
                )
                cache[cache_key] = constraint.snapshot_constraint(
                    snapshot=current_snapshot,
                    target_dataframe=constraint.target_dataframe,
                    column_similarities=constraint.column_similarity_measure,
                    reference_snapshot=reference_snapshot,
                )
            # Multiply accumulation
            similarity *= cache[cache_key]
            # Exclude guardrails from similarity count. Since guardrails are 0 / 1, no adjustment needs to be made
            # on accumulation
            similarity_count += int(
                constraint.snapshot_constraint is not guardrail_similarity
            )
        # Return geometric mean
        return math.pow(similarity, 1 / similarity_count)


def get_effective_turn_count(sandbox_database: pl.DataFrame) -> int:
    """Calculate effective turn count.

    If the execution context ended with exception, sets turn count to None.
    Else, exclude
        1. System messages
        2. User <-> ExecutionEnvironment
        3. User simulator few shot messages (denoted by visible_to == [RoleType.USER])
    Calculate remaining turn counts

    Args:
        sandbox_database:  Sandbox database

    Returns:
        Effective count.
    """
    # Exclude all
    # 1. System messages
    # 2. User <-> ExecutionEnvironment
    # 3. User simulator few shot messages (denoted by visible_to == [RoleType.USER])
    system_message_filter = pl.col("sender") != RoleType.SYSTEM
    user_exec_env_filter = ~(
        (
            (pl.col("sender") == RoleType.USER)
            & (pl.col("recipient") == RoleType.EXECUTION_ENVIRONMENT)
        )
        | (
            (pl.col("sender") == RoleType.EXECUTION_ENVIRONMENT)
            & (pl.col("recipient") == RoleType.USER)
        )
    )
    user_sim_few_shot_filter = pl.col("visible_to") != [RoleType.USER]
    filtered_df = sandbox_database.filter(
        system_message_filter & user_exec_env_filter & user_sim_few_shot_filter
    )
    if filtered_df.is_empty():
        return 0
    return cast(
        int,
        filtered_df.with_columns(pl.len())["len"][0],
    )


@define
class EvaluationResult:
    """Contains results about milestone mapping, coarse / finegrained similarity"""

    # ith object in this list contains (snapshot_index, similarity score) for ith milestone
    milestone_mapping: OrderedDict[int, Tuple[int, float]] = Factory(OrderedDict)
    # ith object in this list contains (snapshot_index, similarity score) for ith minefield
    minefield_mapping: OrderedDict[int, Tuple[int, float]] = Factory(OrderedDict)
    # The arithmetic mean similarity score across all milestones
    milestone_similarity: float = 0
    # The arithmetic mean similarity score across all minefields
    minefield_similarity: float = 0
    # Similarity combining minefield_similarity and milestone_similarity.
    # It is set in __attrs_post_init__
    similarity: float = field(init=False)
    # Total turn count, excluding system messages
    turn_count: int = 0

    def __attrs_post_init__(self) -> None:
        # Combine milestone and minefield. If minefield_similarity != 0, nullify everything.
        self.similarity = (
            int(self.minefield_similarity == 0) * self.milestone_similarity
        )


@define
class MilestoneMatcher:
    """Defines Milestone / Minefield for a test scenario, and provide utilities for matching against a trajectory."""

    # A list of milestones. Index of milestones in this list shall be the node index in the milestone DAG
    milestones: Union[list[Milestone], list[Minefield]] = Factory(list)
    # Milestone edge list. If it is None, will construct a linked list between milestones by default
    edge_list: Optional[list[tuple[int, int]]] = None
    # Milestone DAG, constructed in post init
    milestone_dag: "networkx.DiGraph[int]" = field(init=False)

    def _add_guardrail_constraints(self) -> None:
        """Add guardrail constraints to existing milestones

        Guardrails are applied between current milestone and its reference nodes, as well as its predecessors.

        Returns:

        """
        for i in self.milestone_dag.nodes:
            # Guardrails are applied between current milestone and its reference nodes, as well as
            # its predecessors
            reference_nodes = {
                constraint.reference_milestone_node_index
                for constraint in self.milestones[i].snapshot_constraints
                if constraint.reference_milestone_node_index is not None
            }
            predecessor_nodes = set(self.milestone_dag.predecessors(i))
            # The `cast` is necessary because somehow Mypy does not understand that we
            # explicitly checked the case where
            # `self.milestones[i].guardrail_database_list is None`.
            guardrail_database_set = (
                set()
                if self.milestones[i].guardrail_database_list is None
                else set(
                    cast(
                        list[DatabaseNamespace],
                        self.milestones[i].guardrail_database_list,
                    )
                )
            )
            # Remove sandbox and database that have been constrained in current milestone, reference and predecessor
            guardrail_database_set.discard(DatabaseNamespace.SANDBOX)
            for j in {i} | reference_nodes | predecessor_nodes:
                for constraint in self.milestones[j].snapshot_constraints:
                    if constraint.snapshot_constraint != guardrail_similarity:
                        guardrail_database_set.discard(constraint.database_namespace)
            for reference_milestone_node_index, database_namespace in itertools.product(
                reference_nodes | predecessor_nodes, guardrail_database_set
            ):
                self.milestones[i].snapshot_constraints.append(
                    SnapshotConstraint(
                        reference_milestone_node_index=reference_milestone_node_index,
                        database_namespace=database_namespace,
                        snapshot_constraint=guardrail_similarity,
                    )
                )

    def __attrs_post_init__(self) -> None:
        if self.edge_list is None:
            self.edge_list = [(i, i + 1) for i in range(len(self.milestones) - 1)]
        # if milestones contain only 1 node, create a graph with 1 node and no edges, otherwise create one with
        # edges using edge_list
        if len(self.milestones) == 1:
            self.milestone_dag: "networkx.DiGraph[int]" = networkx.DiGraph()
            self.milestone_dag.add_node(0)
        else:
            self.milestone_dag = networkx.DiGraph(self.edge_list)
        # Add guardrail constraints
        self._add_guardrail_constraints()

    def _dfs(
        self,
        assigned_mapping: OrderedDict[int, Tuple[int, float]],
        similarity_calculators: List[CachedSimilarityCalculator],
        assigned_similarity_sum: float,
        remaining_graph: "networkx.DiGraph[int]",
        current_best_similarity_sum: float,
        min_snapshot_index: int,
        max_snapshot_index: int,
    ) -> Tuple[OrderedDict[int, Tuple[int, float]], float]:
        """Solve for best mapping using dfs + max heap

        Prunes a branch if there's no chance for the branch to match better than current best similarity.

        Args:
            assigned_mapping:               Current already assigned mappings.
            similarity_calculators:         Similarity calculator which computes milestone similarity.
                                            against trajectory. Automatically caches seen similarities.
            assigned_similarity_sum:        Sum of similarity scores across already assigned milestones.
            remaining_graph:                Remaining milestones dag.
            current_best_similarity_sum:    Currently known best similarity sum. Used to prune branches.
            min_snapshot_index:             Minimum snapshot index to match to
            max_snapshot_index:             Maximum snapshot index to match to

        Returns:
            Best assigned mapping and best sum similarity score across milestones
        """
        # DFS end, return
        if networkx.number_of_nodes(remaining_graph) == 0:  # type: ignore[no-untyped-call]
            return assigned_mapping, assigned_similarity_sum
        # The most recent assignment. Next assignment must larger than this
        last_assigned_snapshot_index = (
            assigned_mapping[next(reversed(assigned_mapping))][0]
            if assigned_mapping
            else min_snapshot_index
        )
        # Best mapping and best similarity sum across all possible next mappings
        best_assigned_mapping: OrderedDict[int, Tuple[int, float]] = OrderedDict()
        best_assigned_similarity_sum: float = -1
        # Max heap for milestone / snapshot pairs.
        # Each element is (-similarity, milestone_index, snapshot_index) to ensure similarity is maximized
        max_heap: List[Tuple[float, int, int]] = []
        # Take the next milestone with 0 in degree
        for current_milestone_index, in_degree in remaining_graph.in_degree():
            if in_degree > 0:
                continue
            # Iterate through possible assignments
            # Going from the back ensures that when multiple index have the same current similarity,
            # latter ones gets prioritized.
            for current_snapshot_index in reversed(
                range(last_assigned_snapshot_index, max_snapshot_index + 1)
            ):
                # Get similarity
                current_similarity: float = similarity_calculators[
                    current_milestone_index
                ].calculate_similarity(
                    current_snapshot_index=current_snapshot_index,
                    milestone_snapshot_mapping=assigned_mapping,
                )
                # Push heap, again elements are (-similarity, milestone_index, snapshot_index)
                heapq.heappush(
                    max_heap,
                    (
                        -current_similarity,
                        current_milestone_index,
                        current_snapshot_index,
                    ),
                )
        # Start popping heap, again elements are (-similarity, milestone_index, snapshot_index)
        while max_heap:
            (
                negative_current_similarity,
                current_milestone_index,
                current_snapshot_index,
            ) = heapq.heappop(max_heap)
            current_similarity = -negative_current_similarity
            # Prune branches. If it is impossible for this branch to beat current_best_similarity_sum, prune
            if (
                assigned_similarity_sum
                + current_similarity
                + remaining_graph.number_of_nodes()
                - 1
                <= best_assigned_similarity_sum
            ):
                continue
            # If we couldn't prune this, Prepare input for next level
            current_assigned_mapping = deepcopy(assigned_mapping)
            current_assigned_mapping[current_milestone_index] = (
                current_snapshot_index,
                current_similarity,
            )
            current_remaining_graph = remaining_graph.copy()
            current_remaining_graph.remove_node(current_milestone_index)
            # Get best result from next level
            current_assigned_mapping, current_similarity_sum = self._dfs(
                current_assigned_mapping,
                similarity_calculators,
                assigned_similarity_sum + current_similarity,
                current_remaining_graph,
                max(current_best_similarity_sum, best_assigned_similarity_sum),
                min_snapshot_index,
                max_snapshot_index,
            )
            # Update best results
            if current_similarity_sum > best_assigned_similarity_sum:
                best_assigned_mapping = current_assigned_mapping
                best_assigned_similarity_sum = current_similarity_sum
        return best_assigned_mapping, best_assigned_similarity_sum

    def compute_mapping_and_similarity(
        self, execution_context: ExecutionContext
    ) -> Tuple[OrderedDict[int, Tuple[int, float]], Optional[float]]:
        """Calculate milestone / minefield mapping and similarity against a trajectory.

        The best matches between milestones and execution_context
        are found by maximizing the total arithmatic mean of similarity score, under the constraint that milestones
        sorted based on sandbox_message_index should be one of the possible topological sorts of milestone_dag
        Milestone and snapshots form a 1:1 mapping.

        Since many Milestones (like guardrail) depends on the matching snapshot of other milestones,
        I couldn't think of a very quick solution to this. Here we implement a brute force solution
        with an adequate amount of pruning + memorization. Should revisit this if this is too slow.

        Args:
            execution_context:      ExecutionContext containing the trajectory to be evaluated.


        Returns:
            An EvaluationResult object containing the mean similarity, as well as milestone mapping and finegrained
            similarity. When no milestones are found, return None as similarity and an empty dict.

        """
        # When milestone_dag is empty, default to perfect score
        if networkx.number_of_nodes(self.milestone_dag) == 0:  # type: ignore[no-untyped-call]
            return OrderedDict(), None
        # Construct similarity calculators. These calculators have caching built in
        milestone_similarity_calculators: List[CachedSimilarityCalculator] = [
            CachedSimilarityCalculator(
                execution_context=execution_context, milestone=milestone
            )
            for milestone in self.milestones
        ]
        # Minimum / Maximum snapshot index to match to
        min_snapshot_index: int = execution_context.first_user_sandbox_message_index
        max_snapshot_index: int = execution_context.max_sandbox_message_index
        # Brute force DFS
        milestone_mapping, milestone_similarity_sum = self._dfs(
            assigned_mapping=OrderedDict(),
            similarity_calculators=milestone_similarity_calculators,
            assigned_similarity_sum=0,
            remaining_graph=self.milestone_dag,
            current_best_similarity_sum=0,
            min_snapshot_index=min_snapshot_index,
            max_snapshot_index=max_snapshot_index,
        )
        milestone_similarity = milestone_similarity_sum / len(self.milestones)
        return milestone_mapping, milestone_similarity


@define
class Evaluation:
    """Defining the process needed for evaluating a completed ExecutionContext"""

    # A Milestone Matcher. Contains milestone definition for this Evaluation, as well as utilities for matching
    # milestones against a trajectory
    milestone_matcher: MilestoneMatcher = Factory(MilestoneMatcher)
    # A Minefield Matcher. Contains minefield definition for this Evaluation, as well as utilities for matching
    # minefields against a trajectory
    minefield_matcher: MilestoneMatcher = Factory(MilestoneMatcher)

    def evaluate(
        self, execution_context: ExecutionContext, max_turn_count: int
    ) -> EvaluationResult:
        """Evaluate a completed ExecutionContext

        Calculate Milestone and Minefield similarities, combine them.
        Calculate effective turn count.

        Args:
            execution_context:      ExecutionContext to be evaluated
            max_turn_count:         Maximum number of turns allowed. Overrides turn count when the session ended
                                    with an exception

        Returns:
            An EvaluationResult object containing the mean similarity, as well as milestone mapping and finegrained
            similarity

        Raises:
            IndexError: No Milestone found
        """
        milestone_mapping, milestone_similarity = (
            self.milestone_matcher.compute_mapping_and_similarity(
                execution_context=execution_context
            )
        )
        # If no milestones are found, the default milestone_similarity is 1
        milestone_similarity = (
            1 if milestone_similarity is None else milestone_similarity
        )

        minefield_mapping, minefield_similarity = (
            self.minefield_matcher.compute_mapping_and_similarity(
                execution_context=execution_context
            )
        )
        # If no minefields are found, the default minefield_similarity is 0
        minefield_similarity = (
            0 if minefield_similarity is None else minefield_similarity
        )

        # Calculate turn count
        turn_count = get_effective_turn_count(
            execution_context.get_database(
                DatabaseNamespace.SANDBOX, get_all_history_snapshots=True
            )
        )
        # Sort mapping according to milestone index
        return EvaluationResult(
            milestone_mapping=OrderedDict(sorted(milestone_mapping.items())),
            minefield_mapping=minefield_mapping,
            milestone_similarity=milestone_similarity,
            minefield_similarity=minefield_similarity,
            turn_count=turn_count,
        )

# For licensing see accompanying LICENSE file.
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
from __future__ import annotations

import datetime
import functools
import json
import logging
import uuid
from contextlib import contextmanager
from inspect import getsource, isfunction, signature
from typing import Any, Callable, Iterator, Literal, Optional, TypeVar, Union

import polars as pl
from decorator import decorate
from rapidfuzz import fuzz, process, utils
from strenum import StrEnum
from typing_extensions import Protocol

from tool_sandbox.common.execution_context import (
    DatabaseNamespace,
    RoleType,
    get_current_context,
    new_context_with_attribute,
)
from tool_sandbox.common.tool_discovery import ToolBackend

T = TypeVar("T")

LOGGER = logging.getLogger(__name__)


# Taken from openai._types
# Sentinel class used until PEP 0661 is accepted
class NotGiven:
    """
    A sentinel singleton class used to distinguish omitted keyword arguments
    from those passed in with the value None (which may have different behavior).

    For example:

    ```py
    def search(
        a: Union[int, NotGiven, None] = NotGiven(),
        b: Union[int, NotGiven, None] = NotGiven(),
    ): ...


    search(a=1, b=2)  # Search in database with constraint a == 1, b==2
    search(a=None, b=3)  # Search in database with constraint a == None, b==3
    search(b=4)  # Search in database with constraint b==4
    ```
    """

    def __bool__(self) -> Literal[False]:
        return False

    def __repr__(self) -> str:
        return "NOT_GIVEN"


NOT_GIVEN = NotGiven()


class DataframeFilterMethodType(Protocol):
    """Callable type def for Dataframe filtering functions."""

    def __call__(
        self,
        dataframe: pl.DataFrame,
        column_name: str,
        value: Any,
        **kwargs: Union[int, Any],
    ) -> pl.DataFrame: ...


def exact_match_filter_dataframe(
    dataframe: pl.DataFrame, column_name: str, value: Any, **kwargs: Union[int, Any]
) -> pl.DataFrame:
    """Filter dataframe by exact matching value on 1 column

    Args:
    ----
        dataframe:      Dataframe to filter
        column_name:    Name of column
        value:          Value to match against

    Returns:
    -------
        Filtered dataframe

    """
    return dataframe.filter(pl.col(column_name) == value)


def subsequence_filter_dataframe(
    dataframe: pl.DataFrame, column_name: str, value: Any, **kwargs: Union[int, Any]
) -> pl.DataFrame:
    """Filter dataframe for rows that contains value as a subsequence in column_name

    Args:
    ----
        dataframe:      Dataframe to filter
        column_name:    Name of column
        value:          Value to match against

    Returns:
    -------
        Filtered dataframe

    """
    return dataframe.filter(pl.col(column_name).str.contains(str(value)))


def range_filter_dataframe(
    dataframe: pl.DataFrame, column_name: str, value: Any, **kwargs: Union[int, Any]
) -> pl.DataFrame:
    """Filter dataframe for rows whose column_name value fits in a range. The value must implement __lt__ __gt__ __eq__
        __add__. Boundary included.

    Args:
    ----
        dataframe:      Dataframe to filter
        column_name:    Name of column
        value:          Lower or upperbound of the range
        **kwargs:       Must contain value_delta, value + value_delta provides the other end of the bound

    Returns:
    -------
        Filtered dataframe

    """
    try:
        value_delta = kwargs.get("value_delta")
    except KeyError:
        raise KeyError("**kwargs must contain 'value_delta'")
    lower_bound, upperbound = (
        min(value, value + value_delta),
        max(value, value + value_delta),
    )
    return dataframe.filter(
        (pl.col(column_name) >= lower_bound) & (pl.col(column_name) <= upperbound)
    )


def lt_eq_filter_dataframe(
    dataframe: pl.DataFrame, column_name: str, value: Any, **kwargs: Union[int, Any]
) -> pl.DataFrame:
    """Filter dataframe for rows whose column_name are less than or equal to value. The value must implement __lt__.

    Args:
    ----
        dataframe:      Dataframe to filter
        column_name:    Name of column
        value:          Upperbound of column value

    Returns:
    -------
        Filtered dataframe

    """
    return dataframe.filter(pl.col(column_name) <= value)


def gt_eq_filter_dataframe(
    dataframe: pl.DataFrame, column_name: str, value: Any, **kwargs: Union[int, Any]
) -> pl.DataFrame:
    """Filter dataframe for rows whose column_name are greater than or equal to value. The value must implement __gt__.

    Args:
    ----
        dataframe:      Dataframe to filter
        column_name:    Name of column
        value:          Lowerbound of column value

    Returns:
    -------
        Filtered dataframe

    """
    return dataframe.filter(pl.col(column_name) >= value)


def fuzzy_match_filter_dataframe(
    dataframe: pl.DataFrame, column_name: str, value: Any, **kwargs: Union[int, Any]
) -> pl.DataFrame:
    """Filter dataframe by fuzzy matching string value on 1 column. Backed by fuzz.WRatio

    Args:
    ----
        dataframe:      Dataframe to filter
        column_name:    Name of column
        value:          Value to match against
        **kwargs:       Additional kwargs for matching, for example
                        threshold for fuzz.WRatio, only entries above the threshold are selected

    Returns:
    -------
        Filtered dataframe
    """
    threshold = kwargs.get("threshold", 90)
    # Find the indices of top scored rows, process.extract returns a tuple of (string, score, index)
    matches = process.extract(
        query=value,
        choices=dataframe.get_column(column_name),
        processor=utils.default_process,
        scorer=fuzz.WRatio,
        score_cutoff=threshold,
    )
    return dataframe[[x[-1] for x in matches]]


def filter_dataframe(
    dataframe: pl.DataFrame,
    filter_criteria: list[tuple[str, Any, DataframeFilterMethodType]],
) -> pl.DataFrame:
    """Filter dataframe given a filter method, column name and target value

    Args:
        dataframe:          Dataframe to filter
        filter_criteria:    A list of filter constraints on each column,
                                each tuple contains [column_name, value, filter_method]

    Returns:
        Filtered dataframe
    """
    if all(x[1] is NOT_GIVEN for x in filter_criteria):
        raise ValueError(
            f"No search criteria are given. At least one search criteria should be provided among "
            f"{tuple(x[0] for x in filter_criteria)}"
        )
    for column_name, filter_value, filter_method in filter_criteria:
        if filter_value is not NOT_GIVEN:
            dataframe = filter_method(
                dataframe=dataframe,
                column_name=column_name,
                value=filter_value,
            )
    return dataframe


def polars_multiply_columns_expression(column_names: list[str]) -> pl.Expr:
    """Returns a polars expression that multiplies all columns in column_names

    Args:
        column_names:   Columns to multiply

    Returns:
        A polars expression that multiplies all columns in column_names
    """
    expression = pl.col(column_names[0])
    for column_name in column_names[1:]:
        expression = expression.mul(pl.col(column_name))
    return expression


def add_tool_trace(
    f: Callable[..., Any],
    result: Any,
    *args: Union[NotGiven, Any],
    **kwargs: Union[NotGiven, Any],
) -> None:
    """Add the trace of a tool: tool_name, arguments, execution results into current message in execution_context

    Args:
        f:          Tool callable
        result:     Return value of tool
        *args:      Positional arguments of tool
        **kwargs:   Keyword arguments of tool

    """
    current_context = get_current_context()
    if current_context.trace_tool:
        # Add tool trace to current SANDBOX snapshot. Unfortunately polars doesn't support
        # Very complex objects, and we'll need to json dump the trace into string. This adds
        # a restriction on tool definition (must be json serializable)
        # Note that a trace won't exist if tool execution raised exception
        message_entry: pl.DataFrame = current_context.get_database(
            namespace=DatabaseNamespace.SANDBOX
        )
        existing_tool_trace_series: Optional[pl.Series] = message_entry["tool_trace"][0]
        if existing_tool_trace_series is None:
            existing_tool_trace: list[str] = []
        else:
            existing_tool_trace = existing_tool_trace_series.to_list()
        # Convert positional arguments into keyword arguments. Signature.parameters is an ordered dict
        argument_names = list(signature(f).parameters.keys())
        all_arguments = {argument_names[i]: args[i] for i in range(len(args))}
        all_arguments = {**all_arguments, **kwargs}
        # Skip sentinels
        all_arguments = {k: v for k, v in all_arguments.items() if v is not NOT_GIVEN}
        existing_tool_trace.append(
            json.dumps(
                {
                    "tool_name": f.__name__,
                    "arguments": all_arguments,
                    "result": result,
                },
                ensure_ascii=False,
            )
        )
        new_message_entry = message_entry.with_columns(
            pl.lit(pl.Series("tool_trace", [existing_tool_trace]))
        )
        current_context.update_database(
            namespace=DatabaseNamespace.SANDBOX, dataframe=new_message_entry
        )


def register_as_tool(
    visible_to: Optional[tuple[RoleType]] = None,
    backend: ToolBackend = ToolBackend.DEFAULT,
) -> Callable[..., Any]:
    """Decorator factory, making decorator with arguments possible

    Args:
        visible_to:     Which roles are this tool visible to. Defaults to Agent.
        backend:        Backend implementation of the tool.

    Returns:
        decorator function
    """

    def internal_decorator(func: Callable[..., T]) -> Callable[..., T]:
        """Necessary to make decorator factory work. Returns a decorator which marks a function as tool,
        available for Roles to use

        Make use of decorator.decorate to keep function signature intact

        Args:
            func:   function to decorate

        Returns:
            decorated function
        """

        def _f(f: Callable[..., T], *args: Any, **kwargs: Any) -> T:
            # Disable tracing for any tool call happened inside another tool's scope
            with new_context_with_attribute(trace_tool=False):
                result = f(*args, **kwargs)
            # Add tool trace to messages
            add_tool_trace(f, result, *args, **kwargs)
            return result

        dec = decorate(func, _f)
        setattr(dec, "is_tool", True)
        setattr(
            dec,
            "visible_to",
            visible_to if visible_to is not None else (RoleType.AGENT,),
        )
        setattr(dec, "backend", backend)
        return dec

    return internal_decorator


@contextmanager
def all_logging_disabled(highest_level: int = logging.CRITICAL) -> Iterator[None]:
    """A context manager that will prevent any logging messages
    triggered during the body from being processed.

    This is useful when a known package constantly emits necessary warnings.
    """
    previous_level = logging.root.manager.disable
    logging.disable(highest_level)
    try:
        yield
    finally:
        logging.disable(previous_level)


def attrs_serialize(inst: Any, field: Any, value: Any) -> Any:
    """Serialize troublesome values for attrs. Note almost all below are irreversible operations"""
    if isinstance(value, functools.partial):
        return value.func.__name__
    if isfunction(value):
        if value.__name__ == "<lambda>":
            return getsource(value).strip()
        else:
            return value.__name__
    if isinstance(value, pl.DataFrame):
        return value.to_dicts()
    if isinstance(value, StrEnum):
        return str(value)
    return value


def deterministic_uuid(payload: str) -> str:
    """Simple helper used to generate a deterministic uuid string

    Args:
        payload:    Payload string. Any uuid derived from the same payload is guaranteed to be the same

    Returns:
        String uuid
    """
    return str(uuid.uuid5(namespace=uuid.NAMESPACE_URL, name=payload))


def is_close(value: T, reference: T, atol: Optional[float] = None) -> bool:
    """Checks if value is close the reference.

    Allows for near identity comparison for different data types.

    In the case of float values, allow for a diff of at max atol.

    Args:
        value:      Value to compare.
        reference:  Value to compare against.
        atol:       Absolute tolerance, only needed for numerical values

    Returns:
        Boolean indicating if the values are close
    """
    if (
        atol is not None
        and isinstance(value, (float, int))
        and isinstance(reference, (float, int))
    ):
        return abs(value - reference) <= atol
    return value == reference


def get_tomorrow_datetime() -> datetime.datetime:
    """Get a datetime object for exactly 1 day from now in the future.

    Returns:
        datetime object for exactly 1 day from now in the future.
    """
    return datetime.datetime.now() + datetime.timedelta(days=1)


def get_next_iso_weekday_datetime(next_iso_weekday: int) -> datetime.datetime:
    """Get a datetime object for next weekday.

    Args:
        next_iso_weekday:   1 based integer. 1 for Monday.

    Returns:
        datetime object for next weekday.
    """
    current_datetime = datetime.datetime.now()
    return current_datetime + datetime.timedelta(
        (next_iso_weekday - current_datetime.isoweekday()) % 7
    )

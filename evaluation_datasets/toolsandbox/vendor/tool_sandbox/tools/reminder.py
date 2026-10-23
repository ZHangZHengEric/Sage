# For licensing see accompanying LICENSE file.
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
"""A collection of tools which simulates common functions used for reminder."""

import datetime
import functools
from typing import Dict, List, Literal, Optional, Union, cast
from uuid import uuid4

import polars as pl
from polars.exceptions import DuplicateError, NoDataError

from tool_sandbox.common.execution_context import (
    DatabaseNamespace,
    RoleType,
    get_current_context,
)
from tool_sandbox.common.utils import (
    NOT_GIVEN,
    NotGiven,
    exact_match_filter_dataframe,
    filter_dataframe,
    fuzzy_match_filter_dataframe,
    gt_eq_filter_dataframe,
    lt_eq_filter_dataframe,
    register_as_tool,
)
from tool_sandbox.common.validators import (
    typechecked,
    validate_latitude,
    validate_longitude,
    validate_timestamp,
)


@register_as_tool(visible_to=(RoleType.AGENT,))
@typechecked
def add_reminder(
    content: str,
    reminder_timestamp: float,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
) -> str:
    """Add a reminder

    Args:
        content:                Content of the reminder
        reminder_timestamp:     When the user wants to be reminded. Expressed in POSIX timestamp
        latitude:               Optional. Latitude of the location associated with this reminder
        longitude:              Optional. Longitude of the location associated with this reminder


    Returns:
        String format unique identifier for the reminder, this can be passed to other functions
        which require a unique identifier for this reminder

    """
    validate_timestamp(reminder_timestamp, "reminder_timestamp", float)
    validate_latitude(latitude, "latitude", Optional[float])
    validate_longitude(longitude, "longitude", Optional[float])

    current_context = get_current_context()
    # Create reminder uuid
    reminder_id = str(uuid4())
    current_context.add_to_database(
        namespace=DatabaseNamespace.REMINDER,
        rows=[
            {
                "reminder_id": reminder_id,
                "content": content,
                "creation_timestamp": datetime.datetime.now().timestamp(),
                "reminder_timestamp": reminder_timestamp,
                "latitude": latitude,
                "longitude": longitude,
            }
        ],
    )
    return reminder_id


@register_as_tool(visible_to=(RoleType.AGENT,))
@typechecked
def modify_reminder(
    reminder_id: str,
    content: Union[str, NotGiven] = NOT_GIVEN,
    reminder_timestamp: Union[float, NotGiven] = NOT_GIVEN,
    latitude: Union[Optional[float], NotGiven] = NOT_GIVEN,
    longitude: Union[Optional[float], NotGiven] = NOT_GIVEN,
) -> None:
    """Modify a reminder with new information provided.

    Creation timestamp is updated automatically.

    Args:
        reminder_id:            String format unique identifier of the reminder to be modified
        content:                New content
        reminder_timestamp:     When the user wants to be reminded. Expressed in POSIX timestamp
        latitude:               Optional. Latitude of the location associated with this reminder
        longitude:              Optional. Longitude of the location associated with this reminder

    Raises:
        ValueError:     When all arguments were None
        NoDataError:    When the reminder_id cannot be found in database
        DuplicateError: When multiple entries with the same id were found

    """
    validate_timestamp(reminder_timestamp, "reminder_timestamp", Union[float, NotGiven])
    validate_latitude(latitude, "latitude", Union[Optional[float], NotGiven])
    validate_longitude(longitude, "longitude", Union[Optional[float], NotGiven])

    if all(x is NOT_GIVEN for x in [content, reminder_timestamp, latitude, longitude]):
        raise ValueError(
            "No update information given. At least one new field should be provided among "
            "[content, reminder_timestamp, latitude, longitude] in order to modify reminder"
        )
    current_context = get_current_context()
    reminder_database = current_context.get_database(DatabaseNamespace.REMINDER)
    # Check if entry exists
    target_entry = reminder_database.filter(pl.col("reminder_id") == reminder_id)
    if target_entry.is_empty():
        raise NoDataError(f"No db entry matching {reminder_id=} found")
    # Check if entry is unique
    target_entry_dicts = target_entry.to_dicts()
    if len(target_entry_dicts) > 1:
        raise DuplicateError(f"More than 1 entry with {reminder_id=} found")
    target_entry_dict = target_entry_dicts[0]
    # Create updated entry
    for name, value in [
        ("content", content),
        ("creation_timestamp", datetime.datetime.now().timestamp()),
        ("reminder_timestamp", reminder_timestamp),
        ("latitude", latitude),
        ("longitude", longitude),
    ]:
        if value is not NOT_GIVEN:
            target_entry_dict[name] = value
    # Update database
    current_context.remove_from_database(
        namespace=DatabaseNamespace.REMINDER,
        predicate=pl.col("reminder_id") == reminder_id,
    )
    current_context.add_to_database(
        namespace=DatabaseNamespace.REMINDER,
        rows=[target_entry_dict],
    )


@register_as_tool(visible_to=(RoleType.AGENT,))
@typechecked
def search_reminder(
    reminder_id: Union[str, NotGiven] = NOT_GIVEN,
    content: Union[str, NotGiven] = NOT_GIVEN,
    creation_timestamp_lowerbound: Union[float, NotGiven] = NOT_GIVEN,
    creation_timestamp_upperbound: Union[float, NotGiven] = NOT_GIVEN,
    reminder_timestamp_lowerbound: Union[float, NotGiven] = NOT_GIVEN,
    reminder_timestamp_upperbound: Union[float, NotGiven] = NOT_GIVEN,
    latitude: Union[float, NotGiven] = NOT_GIVEN,
    longitude: Union[float, NotGiven] = NOT_GIVEN,
) -> List[
    Dict[
        Literal[
            "reminder_id",
            "content",
            "creation_timestamp",
            "reminder_timestamp",
            "latitude",
            "longitude",
        ],
        Union[str, float],
    ]
]:
    """Search for a reminder based on provided arguments

    Each field has a search criteria of either
    1. Exact value matching
    2. Fuzzy string matching with a predefined threshold
    3. Range matching timestamp with upperbound or lowerbound
    Search results contains all reminder entries that matched all criteria

    Args:
        reminder_id:                    String format unique identifier for the reminder person, will be exact matched
        content:                        Content of the reminder, will be fuzzy matched
        creation_timestamp_lowerbound:  Lowerbound of the POSIX timestamp of the time the reminder is created.
        creation_timestamp_upperbound:  Upperbound of the POSIX timestamp of the time the reminder is created.
        reminder_timestamp_lowerbound:  Lowerbound of the POSIX timestamp of the time the reminder should be reminded.
        reminder_timestamp_upperbound:  Upperbound of the POSIX timestamp of the time the reminder should be reminded.
        latitude:                       Latitude of the location associated with the reminder. Will be exact matched.
        longitude:                      Longitude of the location associated with the reminder. Will be exact matched.

    Returns:
        A List of matching reminders. An empty List if no matching contacts were found

    Raises:
        ValueError: When all arguments were not provided

    """
    validate_timestamp(
        creation_timestamp_lowerbound,
        "creation_timestamp_lowerbound",
        Union[float, NotGiven],
    )
    validate_timestamp(
        creation_timestamp_upperbound,
        "creation_timestamp_upperbound",
        Union[float, NotGiven],
    )
    validate_timestamp(
        reminder_timestamp_lowerbound,
        "reminder_timestamp_lowerbound",
        Union[float, NotGiven],
    )
    validate_timestamp(
        reminder_timestamp_upperbound,
        "reminder_timestamp_upperbound",
        Union[float, NotGiven],
    )
    validate_latitude(latitude, "latitude", Union[float, NotGiven])
    validate_longitude(longitude, "longitude", Union[float, NotGiven])

    current_context = get_current_context()
    reminder_dataframe = filter_dataframe(
        dataframe=current_context.get_database(namespace=DatabaseNamespace.REMINDER),
        filter_criteria=[
            ("reminder_id", reminder_id, exact_match_filter_dataframe),
            (
                "content",
                content,
                functools.partial(fuzzy_match_filter_dataframe, threshold=50),
            ),
            (
                "creation_timestamp",
                creation_timestamp_lowerbound,
                gt_eq_filter_dataframe,
            ),
            (
                "creation_timestamp",
                creation_timestamp_upperbound,
                lt_eq_filter_dataframe,
            ),
            (
                "reminder_timestamp",
                reminder_timestamp_lowerbound,
                gt_eq_filter_dataframe,
            ),
            (
                "reminder_timestamp",
                reminder_timestamp_upperbound,
                lt_eq_filter_dataframe,
            ),
            ("latitude", latitude, exact_match_filter_dataframe),
            ("longitude", longitude, exact_match_filter_dataframe),
        ],
    )
    return cast(
        List[
            Dict[
                Literal[
                    "reminder_id",
                    "content",
                    "creation_timestamp",
                    "reminder_timestamp",
                    "latitude",
                    "longitude",
                ],
                Union[str, float],
            ]
        ],
        reminder_dataframe.to_dicts(),
    )


@register_as_tool(visible_to=(RoleType.AGENT,))
@typechecked
def remove_reminder(
    reminder_id: str,
) -> None:
    """Remove a reminder given its unique identifier

    Args:
        reminder_id:    String format unique identifier of the reminder to be removed

    Returns:
        String format unique identifier for the reminder, this can be passed to other functions
        which require a unique identifier for this reminder

    Raises:
        NoDataError:    If the provided reminder_id was not found

    """
    current_context = get_current_context()
    current_context.remove_from_database(
        namespace=DatabaseNamespace.REMINDER,
        predicate=(pl.col("reminder_id") == reminder_id),
    )

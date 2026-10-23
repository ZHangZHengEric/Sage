# For licensing see accompanying LICENSE file.
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
"""A collection of tools which simulates utility functions."""

import datetime
from typing import Dict, Literal, Optional, cast

import geopy.distance  # type: ignore
import holidays
import pint
from pint import UndefinedUnitError
from rapidfuzz import fuzz, utils

from tool_sandbox.common.execution_context import RoleType
from tool_sandbox.common.utils import register_as_tool
from tool_sandbox.common.validators import (
    typechecked,
    validate_latitude,
    validate_longitude,
    validate_timestamp,
)
from tool_sandbox.tools.setting import get_wifi_status


@register_as_tool(visible_to=(RoleType.AGENT,))
@typechecked
def get_current_timestamp() -> float:
    """Get current POSIX timestamp

    Returns:
        Float value POSIX timestamp
    """
    return datetime.datetime.now().timestamp()


@register_as_tool(visible_to=(RoleType.AGENT,))
@typechecked
def timestamp_to_datetime_info(
    timestamp: float,
) -> Dict[
    Literal["year", "month", "day", "hour", "minute", "second", "isoweekday"], int
]:
    """Convert POSIX timestamp to a dictionary of date time information, including
        ["year", "month", "day", "hour", "minute", "second", "isoweekday"]
        isoweekday ranges from [1, 7]

    Args:
        timestamp:  Float representing POSIX timestamp

    Returns:
        A dictionary of current date time information
    """
    validate_timestamp(timestamp, "timestamp", float)

    target_datetime = datetime.datetime.fromtimestamp(timestamp)
    return {
        "year": target_datetime.year,
        "month": target_datetime.month,
        "day": target_datetime.day,
        "hour": target_datetime.hour,
        "minute": target_datetime.minute,
        "second": target_datetime.second,
        "isoweekday": target_datetime.isoweekday(),
    }


@register_as_tool(visible_to=(RoleType.AGENT,))
@typechecked
def datetime_info_to_timestamp(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    second: int,
) -> float:
    """Convert  date time information to POSIX timestamp

    Args:
        year:       Year of timestamp
        month:      Month of timestamp
        day:        Day of timestamp
        hour:       Hour of timestamp in 24hr format
        minute:     Minute of timestamp
        second:     Second of timestamp

    Returns:
        POSIX timestamp
    """
    return datetime.datetime(
        year=year, month=month, day=day, hour=hour, minute=minute, second=second
    ).timestamp()


@register_as_tool(visible_to=(RoleType.AGENT,))
@typechecked
def shift_timestamp(
    timestamp: float,
    weeks: int = 0,
    days: int = 0,
    hours: int = 0,
    minutes: int = 0,
    seconds: int = 0,
) -> float:
    """Shifts a POSIX timestamp by provided deltas. Delta can be positive or negative.

    Args:
        timestamp:      POSIX timestamp to be shifted
        weeks:          Number of weeks to add or subtract
        days:           Number of days to add or subtract
        hours:          Number of hours to add or subtract
        minutes:        Number of minutes to add or subtract
        seconds:        Number of seconds to add or subtract


    Returns:
        A shifted POSIX timestamp with deltas applied
    """
    validate_timestamp(timestamp, "timestamp", float)

    target_datetime = datetime.datetime.fromtimestamp(timestamp) + datetime.timedelta(
        weeks=weeks, days=days, hours=hours, minutes=minutes, seconds=seconds
    )
    return target_datetime.timestamp()


@register_as_tool(visible_to=(RoleType.AGENT,))
@typechecked
def timestamp_diff(
    timestamp_0: float,
    timestamp_1: float,
) -> Dict[Literal["days", "seconds"], int]:
    """Calculates the difference between two timestamps, timestamp_1 - timestamp_0, return the difference
    represented in days and seconds

    Args:
        timestamp_0:    Timestamp to subtract
        timestamp_1:    Timestamp to subtract from


    Returns:
        A dictionary containing the difference between timestamp in days and seconds
    """
    validate_timestamp(timestamp_0, "timestamp_0", float)
    validate_timestamp(timestamp_1, "timestamp_1", float)

    time_delta = datetime.datetime.fromtimestamp(
        timestamp_1
    ) - datetime.datetime.fromtimestamp(timestamp_0)
    return {"days": time_delta.days, "seconds": time_delta.seconds}


@register_as_tool(visible_to=(RoleType.AGENT,))
@typechecked
def seconds_to_hours_minutes_seconds(
    seconds: float,
) -> Dict[Literal["hour", "minute", "second"], int]:
    """Convert total number of seconds past 0:00 into hours, minutes and seconds

    Args:
        seconds:    Number of seconds past 0:00

    Returns:
        A dictionary of hours, minutes and seconds
    """
    target_datetime = datetime.datetime.fromtimestamp(seconds)
    return {
        "hour": target_datetime.hour,
        "minute": target_datetime.minute,
        "second": target_datetime.second,
    }


@register_as_tool(visible_to=(RoleType.AGENT,))
@typechecked
def unit_conversion(amount: float, from_unit: str, to_unit: str) -> float:
    """Convert a certain amount from one unit to another

    You can use common english names to represent the from and to units

    Args:
        amount:     Float point amount in from_unit
        from_unit:  Unit to convert from. For example celsius
        to_unit:    Unit to convert to. For example fahrenheit

    Returns:
        Converted amount

    Raises:
        UndefinedUnitError:     If unable to parse the unit names provided
        ValueError:             If unable to convert between provided units
    """
    # Perform slight normalization
    try:
        return cast(float, pint.Quantity(amount, from_unit).to(to_unit).magnitude)
    except UndefinedUnitError:
        return cast(
            float,
            pint.Quantity(amount, from_unit.lower()).to(to_unit.lower()).magnitude,
        )


@register_as_tool(visible_to=(RoleType.AGENT,))
@typechecked
def calculate_lat_lon_distance(
    latitude_0: float, longitude_0: float, latitude_1: float, longitude_1: float
) -> float:
    """Calculate the distance between 2 pairs of latitude and longitude.

    Args:
        latitude_0:     First Latitude.
        longitude_0:    First Longitude.
        latitude_1:     Second Latitude.
        longitude_1:    Second Longitude.

    Returns:
        Distance between the 2 pairs in kilometer.

    """
    validate_latitude(latitude_0, name="latitude_0", expected_type=float)
    validate_latitude(latitude_1, name="latitude_1", expected_type=float)
    validate_longitude(longitude_0, name="longitude_0", expected_type=float)
    validate_longitude(longitude_1, name="longitude_1", expected_type=float)
    return cast(
        float,
        geopy.distance.distance(
            (latitude_0, longitude_0), (latitude_1, longitude_1)
        ).kilometers,
    )


@register_as_tool(visible_to=(RoleType.AGENT,))
@typechecked
def search_holiday(
    holiday_name: str,
    year: Optional[int] = None,
) -> Optional[float]:
    """Search for a holiday by name in the US.

    Canonicalize return value into corresponding POSIX timestamp.

    Args:
        holiday_name:   Name of the holiday in surface form string
        year:           Optional. Year to search the holiday in. When not provided defaults to current year.


    Returns:
        POSIX timestamp of holiday if the holiday can be found, otherwise return None
    """
    # Simulate a tool backed by web services. Check for wifi status
    if not get_wifi_status():
        raise ConnectionError("Wifi is not enabled")
    if year is None:
        year = datetime.datetime.now().year
    # Sort holidays by decreasing name partial match score against database.
    # Apply string normalization with default_process
    holiday_matches: list[tuple[float, datetime.date, str]] = list(
        sorted(
            (
                (
                    fuzz.partial_ratio(
                        holiday_name,
                        name,
                        processor=utils.default_process,
                    ),
                    date,
                    name,
                )
                for date, name in holidays.country_holidays(
                    country="US", years=year
                ).items()
            ),
            reverse=True,
        )
    )
    # Threshold at 90 for top match
    if holiday_matches and holiday_matches[0][0] > 90:
        return datetime.datetime.combine(
            holiday_matches[0][1], datetime.datetime.min.time()
        ).timestamp()
    return None

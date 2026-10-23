# For licensing see accompanying LICENSE file.
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
"""Validation utilities for common data types"""

import inspect
from functools import wraps
from typing import Any, Callable, Optional, TypeVar, Union, cast, get_args, get_origin

import ccy  # type: ignore
import phonenumbers

from tool_sandbox.common.utils import NOT_GIVEN, NotGiven

T = TypeVar("T")
Numeric = TypeVar("Numeric", int, float)


def validate_currency_code(currency_code: str) -> Any:
    """Validation for 3 letter currency code conforming to ISO 4217

    Args:
        currency_code:  String to be validated as currency code

    Returns:

    Raises:
        ValueError: When currency_code is not a known currency code

    """
    if ccy.currency(currency_code) is None:
        raise ValueError(
            f"{currency_code} is not a known 3 letter ISO 4217 currency code"
        )


def validate_type(value: Any, value_name: str, expected_type: T) -> None:
    """Validate that `value` is of type `expected_type`.

    Args:
      value:         Value to validate the type of.
      value_name:    Name of value to show in error message.
      expected_type: Expected type of value.

    Raises:
      TypeError if `value` is not of the expected type(s).
    """
    expected_types = set(
        get_args(expected_type)
        if get_origin(expected_type) is Union
        else (expected_type,)
    )
    expected_types = {get_origin(t) or t for t in expected_types}
    if type(value) in expected_types:
        return

    # We allow the same upcasting that occurs naturally in Python (e.g. upcasting an
    # `int` to a `float` when performing an addition). Also based on PEP 484:
    #    "when an argument is annotated as having type float, an argument of type "
    #    "int is acceptable;"
    # , see https://peps.python.org/pep-0484/#the-numeric-tower .
    if isinstance(value, int) and float in expected_types:
        return

    # Booleans are a subclass of integers.
    if isinstance(value, bool) and (int in expected_types or float in expected_types):
        return

    raise TypeError(
        f"Parameter '{value_name}' is of type '{type(value)}', but expected "
        f"'{expected_type}'."
    )


def typechecked(function: Callable[..., T]) -> Callable[..., T]:
    """Validate the parameter types of a function.

    Args:
      function: Function to check types of.
    Raises:
      TypeError if any parameter is not of the expected type(s).
    """

    @wraps(function)
    def typechecker(*args: Any, **kwargs: Any) -> Any:
        params = inspect.signature(function).parameters
        # Check positional arguments.
        for arg, param in zip(args, params.values()):
            validate_type(arg, param.name, param.annotation)
        # Check keyword arguments.
        for name, kwarg in kwargs.items():
            param = params[name]
            validate_type(kwarg, param.name, param.annotation)
        return function(*args, **kwargs)

    return typechecker


def validate_range(
    value: Numeric,
    value_name: str,
    *,
    min_val: Optional[Numeric] = None,
    max_val: Optional[Numeric] = None,
) -> None:
    """Validate that `value` is between the optional min and max values (inclusive).

    Args:
      value:      Value to validate the range of.
      value_name: Name of value to show in error message.
      min_val:    Optional minimum of value range to validate.
      max_val:    Optional maximum of value range to validate.
    Raises:
      ValueError if `value` is outside the expected range.
    """
    if min_val is not None and value < min_val:
        raise ValueError(
            f"Parameter '{value_name}' is smaller than its valid range minimum of {min_val}."
        )
    if max_val is not None and value > max_val:
        raise ValueError(
            f"Parameter '{value_name}' is larger than its valid range maximum of {max_val}."
        )


def validate_type_range(
    value: Any,
    value_name: str,
    expected_type: T,
    *,
    min_val: Optional[Numeric] = None,
    max_val: Optional[Numeric] = None,
) -> None:
    """Validate parameter type and range.

    Args:
      value:         Value to validate the type and range of.
      value_name:    Name of value to show in error message.
      expected_type: Expected type of value.
      min_val:       Optional minimum of value range to validate.
      max_val:       Optional maximum of value range to validate.
    Raises:
      TypeError if `value` is not of the expected type(s).
      ValueError if `value` is outside the expected range.
    """
    validate_type(value, value_name, expected_type)
    # Don't check the range if the value is not numeric (e.g. NotGiven, None).
    if isinstance(value, (float, int)):
        validate_range(
            cast(Numeric, value), value_name, min_val=min_val, max_val=max_val
        )


def validate_timestamp(timestamp: T, name: str, expected_type: T) -> None:
    """Validate the range of timestamps so a unit mistake is caught (s vs ms/us/ns).

    Args:
        timestamp: Timestamp to validate.
        timestamp_name: Name of variable to validate.
        expected_type: Expected type of timestamp.
    Raises:
        TypeError if timestamp is not of the expected type(s).
        ValueError if timestamp is outside the expected range.
    """
    TS_JAN_1_1980 = 315529200.0  # in seconds
    TS_JAN_1_2050 = 2524604400.0  # in seconds
    validate_type_range(
        timestamp, name, expected_type, min_val=TS_JAN_1_1980, max_val=TS_JAN_1_2050
    )


def validate_latitude(latitude: T, name: str, expected_type: T) -> None:
    """Validate the type and range of latitude in degrees.

    Args:
        latitude: Latitude value to validate.
        name: Name of variable to validate.
        expected_type: Expected type of latitude.
    Raises:
        TypeError if latitude is not of the expected type(s).
        ValueError if latitude is outside the expected range.
    """
    MIN_LAT = -90.0  # degrees
    MAX_LAT = 90.0  # degrees
    validate_type_range(latitude, name, expected_type, min_val=MIN_LAT, max_val=MAX_LAT)


def validate_longitude(longitude: T, name: str, expected_type: T) -> None:
    """Validate the type and range of longitude in degrees.

    Args:
        longitude: Longitude value to validate.
        name: Name of variable to validate.
        expected_type: Expected type of longitude.
    Raises:
      TypeError if longitude is not of the expected type(s).
      ValueError if longitude is outside the expected range.
    """
    MIN_LON = -180.0  # degrees
    MAX_LON = 180.0  # degrees
    validate_type_range(
        longitude, name, expected_type, min_val=MIN_LON, max_val=MAX_LON
    )


def validate_phone_number(phone_number: Union[str, NotGiven]) -> None:
    """Validate if a string is a phone number.

    Args:
        phone_number: Phone number to be validated. If it is NOT_GIVEN, validation is ignored

    Raises:
        NumberParseException:  If phone number cannot be parsed.
    """
    if phone_number is not NOT_GIVEN:
        assert not isinstance(phone_number, NotGiven)
        phonenumbers.parse(phone_number)

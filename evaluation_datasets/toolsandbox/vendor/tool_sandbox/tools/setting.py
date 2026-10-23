# For licensing see accompanying LICENSE file.
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
"""A collection of tools which simulates common functions used for setting."""

from typing import Dict, Literal, cast

import polars as pl

from tool_sandbox.common.execution_context import (
    DatabaseNamespace,
    RoleType,
    get_current_context,
)
from tool_sandbox.common.utils import register_as_tool
from tool_sandbox.common.validators import validate_type


def set_boolean_settings(setting_name: str, on: bool) -> None:
    """Utility function for setting boolean settings. DO NOT expose this as a tool

    Args:
        setting_name:       Name of the settings column
        on:                 Whether to turn on or off

    Returns:

    """
    validate_type(setting_name, "setting_name", str)
    validate_type(on, "on", bool)

    current_context = get_current_context()
    setting_database = current_context.get_database(DatabaseNamespace.SETTING)
    if setting_database.schema.get(setting_name, pl.Null) != pl.Boolean:
        raise KeyError(f"{setting_name} is not a boolean column")
    if bool(setting_database[setting_name][0]) == on:
        raise ValueError(f"{setting_name} already {('disabled', 'enabled')[int(on)]}")
    current_context.update_database(
        namespace=DatabaseNamespace.SETTING,
        dataframe=setting_database.with_columns(~pl.col(setting_name)),
    )


def get_boolean_settings(setting_name: str) -> bool:
    """Utility function for getting boolean settings. DO NOT expose this as a tool

    Args:
        setting_name:       Name of the settings column

    Returns:

    """
    validate_type(setting_name, "setting_name", str)

    current_context = get_current_context()
    setting_database = current_context.get_database(DatabaseNamespace.SETTING)
    if setting_database.schema.get(setting_name, pl.Null) != pl.Boolean:
        raise KeyError(f"{setting_name} is not a boolean column")
    return cast(bool, setting_database[setting_name][0])


@register_as_tool(visible_to=(RoleType.AGENT,))
def set_low_battery_mode_status(on: bool) -> None:
    """Enable / Disable low battery mode

    Args:
        on: If we want to turn on low battery mode

    Returns:

    Raises:
        ValueError: If low battery mode is already turned on / off
    """
    validate_type(on, "on", bool)

    set_boolean_settings(setting_name="low_battery_mode", on=on)
    # Automatically turn off other dependent services if low battery mode is on
    if on:
        for dependent_setting in ["cellular", "wifi", "location_service"]:
            try:
                set_boolean_settings(dependent_setting, on=False)
            except ValueError:
                pass


@register_as_tool(visible_to=(RoleType.AGENT,))
def get_low_battery_mode_status() -> bool:
    """Request low battery mode status

    Returns:
        Boolean indicating if the low battery mode is on
    """
    return get_boolean_settings("low_battery_mode")


@register_as_tool(visible_to=(RoleType.AGENT,))
def set_location_service_status(on: bool) -> None:
    """Enable / Disable location service

    Args:
        on: If we want to turn on location service

    Returns:

    Raises:
        ValueError:         If location service is already turned on / off
        PermissionError:    If low battery mode is on, in which case we are not allowed to turn on location service
    """
    if on and get_low_battery_mode_status():
        raise PermissionError(
            "Location service cannot be turned on in low battery mode"
        )
    set_boolean_settings(setting_name="location_service", on=on)


@register_as_tool(visible_to=(RoleType.AGENT,))
def get_location_service_status() -> bool:
    """Request location service status

    Returns:
        Boolean indicating if the location service is on
    """
    return get_boolean_settings("location_service")


@register_as_tool(visible_to=(RoleType.AGENT,))
def set_cellular_service_status(on: bool) -> None:
    """Enable / Disable cellular service

    Args:
        on: If we want to turn on cellular service

    Returns:

    Raises:
        ValueError:         If cellular service is already turned on / off
        PermissionError:    If low battery mode is on, in which case we are not allowed to turn on cellular service
    """
    validate_type(on, "on", bool)

    if on and get_low_battery_mode_status():
        raise PermissionError(
            "Cellular service cannot be turned on in low battery mode"
        )
    set_boolean_settings(setting_name="cellular", on=on)


@register_as_tool(visible_to=(RoleType.AGENT,))
def get_cellular_service_status() -> bool:
    """Request cellular service status

    Returns:
        Boolean indicating if the cellular service is on
    """
    return get_boolean_settings("cellular")


@register_as_tool(visible_to=(RoleType.AGENT,))
def set_wifi_status(on: bool) -> None:
    """Enable / Disable wifi

    Args:
        on: If we want to turn on wifi

    Returns:

    Raises:
        ValueError:         If wifi is already turned on / off
        PermissionError:    If low battery mode is on, in which case we are not allowed to turn on wifi
    """
    validate_type(on, "on", bool)

    if on and get_low_battery_mode_status():
        raise PermissionError("Wifi cannot be turned on in low battery mode")
    set_boolean_settings(setting_name="wifi", on=on)


@register_as_tool(visible_to=(RoleType.AGENT,))
def get_wifi_status() -> bool:
    """Request wifi status

    Returns:
        Boolean indicating if the wifi is on
    """
    return get_boolean_settings("wifi")


@register_as_tool(visible_to=(RoleType.AGENT,))
def get_current_location() -> Dict[Literal["latitude", "longitude"], float]:
    """Request current location latitude and longitude

    Returns:
        A dictionary of latitude and longitude

    Raises:
        PermissionError:    If location_service is not turned on, we are not allowed to access current location
    """
    if not get_location_service_status():
        raise PermissionError("Location service is not enabled.")
    current_context = get_current_context()
    setting_database = current_context.get_database(DatabaseNamespace.SETTING)
    return {
        "latitude": setting_database["latitude"][0],
        "longitude": setting_database["longitude"][0],
    }

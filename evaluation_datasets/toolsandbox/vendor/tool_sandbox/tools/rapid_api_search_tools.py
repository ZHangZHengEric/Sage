# For licensing see accompanying LICENSE file.
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
"""
A collection of tools which simulates common functions used for searching over an index.
Tools listed in this category are backed by RapidAPI hosted web service requests.
"""

import os
from typing import Any, Optional, Union, cast

import requests

from tool_sandbox.common.execution_context import RoleType
from tool_sandbox.common.utils import NOT_GIVEN, register_as_tool
from tool_sandbox.common.validators import (
    typechecked,
    validate_currency_code,
    validate_latitude,
    validate_longitude,
)
from tool_sandbox.tools.setting import (
    get_current_location,
    get_location_service_status,
    get_wifi_status,
)


@typechecked
def maybe_get_current_lat_lon(
    latitude: Optional[float] = None, longitude: Optional[float] = None
) -> tuple[float, float]:
    """No-op if latitude and longitude are both provided. Otherwise return current location latitude longitude

    Args:
        latitude:           Defaults to current latitude if not provided
        longitude:          Defaults to current longitude if not provided

    Returns:
        A Tuple of latitude and longitude

    Raises:
        ValueError:         If 1 and only 1 of latitude and longitude is not provided
        PermissionError:    If location service is not enabled

    """
    validate_latitude(latitude, "latitude", Optional[float])
    validate_longitude(longitude, "longitude", Optional[float])

    if (latitude is None) ^ (longitude is None):
        raise ValueError(
            "Latitude and Longitude must be either both provided, or both not provided"
        )
    if latitude is None and longitude is None:
        if not get_location_service_status():
            raise PermissionError("Location service is not enabled.")
        current_location = get_current_location()
        latitude = current_location["latitude"]
        longitude = current_location["longitude"]
    assert latitude is not None and longitude is not None
    return latitude, longitude


def rapid_api_get_request(
    url: str, params: dict[str, Any], headers: dict[str, Any]
) -> dict[str, Any]:
    """Make a Rapid API Get request and get the response.

    Args:
        url:            URL to make the request to.
        params:         Dict object containing request parameters.
        headers:        Request headers, including "X-RapidAPI-Host". "X-RapidAPI-Key" is
                        extracted from environ. Doesn't need to be provided.

    Returns:
        Rapid API Response
    """
    if not get_wifi_status():
        raise ConnectionError("Wifi is not enabled")
    if "RAPID_API_KEY" not in os.environ:
        raise PermissionError(
            "Please provide 'RAPID_API_KEY' in environment variable. "
            "You can find your API key by following https://docs.rapidapi.com/v1.0/docs/keys"
        )
    return cast(
        dict[str, Any],
        requests.get(
            url=url,
            headers={**headers, "X-RapidAPI-Key": os.environ["RAPID_API_KEY"]},
            params=params,
        ).json(),
    )


@register_as_tool(visible_to=(RoleType.AGENT,))
@typechecked
def search_lat_lon(
    latitude: float,
    longitude: float,
) -> Optional[str]:
    """Search for the address corresponding to a latitude and longitude

    Args:
        latitude:       Latitude to search
        longitude:      Longitude to search

    Returns:
        Address string if the address can be found, otherwise return None
    """
    validate_latitude(latitude, "latitude", float)
    validate_longitude(longitude, "longitude", float)

    rapid_api_response = rapid_api_get_request(
        url="https://trueway-geocoding.p.rapidapi.com/ReverseGeocode",
        params={
            "location": f"{latitude},{longitude}",
            "language": "en",
        },
        headers={"X-RapidAPI-Host": "trueway-geocoding.p.rapidapi.com"},
    )
    try:
        return cast(str, rapid_api_response["results"][0]["address"])
    except (KeyError, IndexError):
        return None


# A simple dict mapping rapid api weather api response keys to a more readable format.
# Mapping to None means said key should be removed.
_weather_key_mapping: dict[str, Optional[str]] = {
    "temp_c": "current_temperature",
    "temp_f": None,
    "feelslike_c": "perceived_temperature",
    "feelslike_f": None,
    "vis_km": "visibility_distance",
    "vis_miles": None,
    "wind_kph": "wind_speed",
    "wind_mph": None,
    "maxtemp_c": "max_temperature",
    "maxtemp_f": None,
    "mintemp_c": "min_temperature",
    "mintemp_f": None,
    "avgtemp_c": "average_temperature",
    "avgtemp_f": None,
    "maxwind_kph": "max_wind_speed",
    "maxwind_mph": None,
    "avgvis_km": "average_visibility_distance",
    "avgvis_miles": None,
    "pressure_mb": "barometric_pressure",
    "pressure_in": None,
    "precip_mm": None,
    "precip_in": None,
    "totalprecip_mm": None,
    "totalprecip_in": None,
    "avghumidity": "average_humidity",
}


@register_as_tool(visible_to=(RoleType.AGENT,))
@typechecked
def search_location_around_lat_lon(
    location: str,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
) -> list[dict[str, Any]]:
    """Search for a location around a latitude and longitude

    location is a surface form query defining the location. This can be a business name like McDonald's,
    a point of interest like restaurant, a city / state,
    or a full address. When latitude and longitude are not provided, defaults to search around current location.

    Search results contains various optional information including but not limited to
        - name
        - address
        - category / type
        - business hours
        - price
        - phone_number
        - url
        - location lat lon

    Args:
        location:       Surface form query defining the location
        latitude:       Latitude to search around. Defaults to current latitude if not provided
        longitude:      Longitude to search around. Defaults to current longitude if not provided

    Returns:
        A List of dictionary containing various information about the location if found, otherwise return empty list

    Raises:
        ValueError      If 1 and only 1 of latitude and longitude is not provided
    """
    latitude, longitude = maybe_get_current_lat_lon(
        latitude=latitude, longitude=longitude
    )
    validate_latitude(latitude, "latitude", Optional[float])
    validate_longitude(longitude, "longitude", Optional[float])
    rapid_api_response = rapid_api_get_request(
        url="https://maps-data.p.rapidapi.com/searchmaps.php",
        params={
            "query": location,
            "lat": latitude,
            "lng": longitude,
            "limit": 4,
            "country": "us",
            "lang": "en",
        },
        headers={"X-RapidAPI-Host": "maps-data.p.rapidapi.com"},
    )
    try:
        results: list[dict[str, Any]] = rapid_api_response["data"]
        # Drop unnecessary fields
        for result in results:
            for unnecessary_key in [
                "business_id",
                "place_id",
                "place_link",
                "verified",
                "photos",
            ]:
                result.pop(unnecessary_key, None)
        return results
    except KeyError:
        pass
    return []


@register_as_tool(visible_to=(RoleType.AGENT,))
@typechecked
def search_weather_around_lat_lon(
    days: int = 0,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
) -> Optional[dict[str, Any]]:
    """Search for weather information around a latitude and longitude, right now or sometime in the future

    Search results contains weather forcast various optional information, including but not limited to
        - condition: RAIN / CLOUDY ...
        - temperature:  In Celsius
        - humidity
        - country
        - state
        - timezone

    Args:
        days:       Number of days to search for past the current time. Defaults to current day if not provided.
        latitude:   Latitude to search around. Defaults to current latitude if not provided
        longitude:  Longitude to search around. Defaults to current longitude if not provided

    Returns:
        A dictionary containing weather forcast information if found, otherwise return None

    Raises:
        ValueError:     When days or hours are negative
    """
    validate_latitude(latitude, "latitude", Optional[float])
    validate_longitude(longitude, "longitude", Optional[float])
    latitude, longitude = maybe_get_current_lat_lon(
        latitude=latitude, longitude=longitude
    )
    if days < 0 or not isinstance(days, int):
        raise ValueError(f"Days must be positive integer, found {days=}.")
    rapid_api_response = rapid_api_get_request(
        url="https://weatherapi-com.p.rapidapi.com/forecast.json",
        params={
            "q": f"{latitude}, {longitude}",
            "days": days + 1,
        },
        headers={"X-RapidAPI-Host": "weatherapi-com.p.rapidapi.com"},
    )
    try:
        # Flatten forecast
        forecast: dict[str, Any] = rapid_api_response["forecast"]["forecastday"][days]
        flattened_forecast: dict[str, Any] = {
            **forecast["day"],
            **forecast["astro"],
            **rapid_api_response["location"],
            "temperature_unit": "Celsius",
            "distance_unit": "Kilometer",
        }
        # Merge in current observation if days == 0
        if days == 0:
            flattened_forecast.update(rapid_api_response["current"])
        # Process keys
        for key, new_key in _weather_key_mapping.items():
            # If key is not found, value will be NOT_GIVEN, otherwise the original key value will be popped.
            value: Any = flattened_forecast.pop(key, NOT_GIVEN)
            if new_key is not None and value is not NOT_GIVEN:
                flattened_forecast[new_key] = value
        return flattened_forecast
    except (KeyError, IndexError):
        pass
    return None


@register_as_tool(visible_to=(RoleType.AGENT,))
@typechecked
def search_stock(query: str) -> Optional[dict[str, Union[str, float]]]:
    """Search for various information about a stock given a query.

    The query can be a company name (Apple), stock symbol (AAPL) exchange name (NASDAQ)

    Search results contains various optional information about the stock, including but not limited to

        - name:             The written name of the stock, e.g. Apple
        - symbol:           The code for the stock, e.g. AAPL
        - exchange:         The exchange the stock is in, e.g. NASDAQ
        - price:            Current price of the stock
        - change:           Absolute diff between current price of the stock and last opening day
        - percent_change:   Relative diff between current price of the stock and last opening day
        - currency:         ISO currency of the currency this stock trades in, e.g. USD

    Args:
        query:  a company name (Apple), stock symbol (AAPL) exchange name (NASDAQ)

    Returns:
        A dictionary containing various optional information about the stock if found, otherwise return None
    """
    rapid_api_response = rapid_api_get_request(
        url="https://real-time-finance-data.p.rapidapi.com/search",
        params={
            "query": query,
        },
        headers={"X-RapidAPI-Host": "real-time-finance-data.p.rapidapi.com"},
    )
    try:
        stock_info: dict[str, Any] = rapid_api_response["data"]["stock"][0]
        # Remove exchange from symbol
        stock_info["symbol"] = stock_info["symbol"].split(":")[0]
        return stock_info
    except (KeyError, IndexError):
        return None


# Note: This tool only accepts canonical form. This pairs nicely with tools that accepts surface form, e.g.
# `unit_conversion` to test model behavior in both cases
@register_as_tool(visible_to=(RoleType.AGENT,))
@typechecked
def convert_currency(
    amount: Union[float, int], from_currency_code: str, to_currency_code: str
) -> float:
    """Converts currency amount from a one currency to another given on their ISO 4217 currency code

    Args:
        amount:             Amount of currency to convert
        from_currency_code: ISO 4217 currency code `amount` corresponds to
        to_currency_code:   ISO 4217 currency code return value corresponds to

    Returns:
        A float amount in to_currency_code
    """
    validate_currency_code(from_currency_code)
    validate_currency_code(to_currency_code)
    rapid_api_response = rapid_api_get_request(
        url="https://currency-converter18.p.rapidapi.com/api/v1/convert",
        params={
            "from": from_currency_code.upper(),
            "to": to_currency_code.upper(),
            "amount": amount,
        },
        headers={"X-RapidAPI-Host": "currency-converter18.p.rapidapi.com"},
    )
    try:
        return float(rapid_api_response["result"]["convertedAmount"])
    except KeyError:
        raise RuntimeError("Conversion failed")

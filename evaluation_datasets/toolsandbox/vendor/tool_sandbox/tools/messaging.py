# For licensing see accompanying LICENSE file.
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
"""A collection of tools which simulates common functions used for messaging."""

import datetime
import functools
from typing import Dict, List, Literal, Union, cast
from uuid import uuid4

from polars.exceptions import DuplicateError

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
    validate_phone_number,
    validate_timestamp,
)
from tool_sandbox.tools.contact import search_contacts
from tool_sandbox.tools.setting import get_cellular_service_status


@register_as_tool(visible_to=(RoleType.AGENT,))
@typechecked
def send_message_with_phone_number(phone_number: str, content: str) -> str:
    """Send a message to a recipient using phone_number

    Args:
        phone_number:   String format phone number to send the message to
        content:        Message payload text

    Returns:
        String format unique identifier for the message, this can be passed to other functions
        which require a unique identifier for this message

    Raises:
        ValueError:         If less than or more than 1 self entry was found
        ConnectionError:    If cellular service is not on

    """
    # Validate phone number
    validate_phone_number(phone_number)
    current_context = get_current_context()
    if not get_cellular_service_status():
        raise ConnectionError("Cellular service is not enabled")
    # Create message uuid
    message_id = str(uuid4())
    # Find self
    self_data = search_contacts(is_self=True)
    if len(self_data) != 1:
        raise DuplicateError(
            f"1 and only 1 self entry should exist in contacts database, instead found {len(self_data)}"
        )
    # Find recipient, not guaranteed to exist
    recipient_data = search_contacts(phone_number=phone_number)
    recipient_person_id = (
        None if len(recipient_data) == 0 else recipient_data[0]["person_id"]
    )
    current_context.add_to_database(
        namespace=DatabaseNamespace.MESSAGING,
        rows=[
            {
                "message_id": message_id,
                "sender_person_id": self_data[0]["person_id"],
                "sender_phone_number": self_data[0]["phone_number"],
                "recipient_person_id": recipient_person_id,
                "recipient_phone_number": phone_number,
                "content": content,
                "creation_timestamp": datetime.datetime.now().timestamp(),
            }
        ],
    )
    return message_id


@register_as_tool(visible_to=(RoleType.AGENT,))
@typechecked
def search_messages(
    message_id: Union[str, NotGiven] = NOT_GIVEN,
    sender_person_id: Union[str, NotGiven] = NOT_GIVEN,
    sender_phone_number: Union[str, NotGiven] = NOT_GIVEN,
    recipient_person_id: Union[str, NotGiven] = NOT_GIVEN,
    recipient_phone_number: Union[str, NotGiven] = NOT_GIVEN,
    content: Union[str, NotGiven] = NOT_GIVEN,
    creation_timestamp_lowerbound: Union[float, NotGiven] = NOT_GIVEN,
    creation_timestamp_upperbound: Union[float, NotGiven] = NOT_GIVEN,
) -> List[
    Dict[
        Literal[
            "message_id",
            "sender_person_id",
            "sender_phone_number",
            "recipient_person_id",
            "recipient_phone_number",
            "content",
            "creation_timestamp",
        ],
        Union[str, float],
    ]
]:
    """Search for a message based on provided arguments

    Each field has a search criteria of one of the below
    1. Exact value matching
    2. Fuzzy string matching with a predefined threshold
    3. Range matching timestamp with upperbound or lowerbound
    Search results contains all contact entries that matched all criteria

    Args:
        message_id:                     String format unique identifier for message, will be exact matched
        sender_person_id:               String format unique identifier for the sender, will be exact matched
        sender_phone_number:            Phone number for the sender, will be exact matched
        recipient_person_id:            String format unique identifier for the recipient, will be exact matched
        recipient_phone_number:         Phone number for the recipient, will be exact matched
        content:                        Message content, will be fuzzy matched
        creation_timestamp_lowerbound:  Lowerbound of the POSIX timestamp of the time the message is created.
        creation_timestamp_upperbound:  Upperbound of the POSIX timestamp of the time the message is created.


    Returns:
        A List of matching messages. An empty List if no matching contacts were found

    Raises:
        ValueError: When all arguments were not provided

    """
    # Validate phone number
    validate_phone_number(sender_phone_number)
    validate_phone_number(recipient_phone_number)
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

    current_context = get_current_context()
    messaging_dataframe = filter_dataframe(
        dataframe=current_context.get_database(namespace=DatabaseNamespace.MESSAGING),
        filter_criteria=[
            ("message_id", message_id, exact_match_filter_dataframe),
            ("sender_person_id", sender_person_id, exact_match_filter_dataframe),
            ("sender_phone_number", sender_phone_number, exact_match_filter_dataframe),
            ("recipient_person_id", recipient_person_id, exact_match_filter_dataframe),
            (
                "recipient_phone_number",
                recipient_phone_number,
                exact_match_filter_dataframe,
            ),
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
        ],
    )
    return cast(
        List[
            Dict[
                Literal[
                    "message_id",
                    "sender_person_id",
                    "sender_phone_number",
                    "recipient_person_id",
                    "recipient_phone_number",
                    "content",
                    "creation_timestamp",
                ],
                Union[str, float],
            ]
        ],
        messaging_dataframe.to_dicts(),
    )

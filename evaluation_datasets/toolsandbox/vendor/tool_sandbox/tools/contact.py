# For licensing see accompanying LICENSE file.
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
"""A collection of tools which simulates common functions used for contact book."""

import functools
from logging import getLogger
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
    register_as_tool,
)
from tool_sandbox.common.validators import (
    typechecked,
    validate_phone_number,
    validate_type,
)

LOGGER = getLogger(__name__)


@register_as_tool(visible_to=(RoleType.AGENT,))
@typechecked
def add_contact(
    name: str,
    phone_number: str,
    relationship: Optional[str] = None,
    is_self: bool = False,
) -> str:
    """Add a new contact person to contact database. Entries with identical information are allowed,
    and will be assigned different person_ids.

    Args:
        name:           Name of contact person
        phone_number:   Phone number of contact person
        relationship:   Optional, relationship between user and this contact
        is_self:        Optional. Defaults to False. Should be set to True if the contact corresponds to the current user.

    Returns:
        String format unique identifier for the contact person, this can be passed to other functions
        which require a unique identifier for this contact person

    Raises:
        DuplicateError:     When self entry already exists, and we are adding a new one

    """
    # Validate phone number
    validate_phone_number(phone_number)
    person_id = str(uuid4())
    current_context = get_current_context()
    if is_self and search_contacts(is_self=True):
        raise DuplicateError("Self entry already exists. Cannot add another one.")
    current_context.add_to_database(
        namespace=DatabaseNamespace.CONTACT,
        rows=[
            {
                "person_id": person_id,
                "name": name,
                "phone_number": phone_number,
                "relationship": relationship,
                "is_self": is_self,
            }
        ],
    )
    return person_id


@register_as_tool(visible_to=(RoleType.AGENT,))
@typechecked
def modify_contact(
    person_id: str,
    name: Union[str, NotGiven] = NOT_GIVEN,
    phone_number: Union[str, NotGiven] = NOT_GIVEN,
    relationship: Union[str, NotGiven] = NOT_GIVEN,
    is_self: Union[bool, NotGiven] = NOT_GIVEN,
) -> None:
    """Modify a contact entry with new information provided

    Args:
        person_id:      String unique identifier for the contact person
        name:           New name for the person
        phone_number:   New phone number for the person
        relationship:   New relationship for the person
        is_self:        Optional. Defaults to False. Should be set to True if the contact corresponds to the current user.

    Returns:

    Raises:
        ValueError:     When all arguments were None
        NoDataError:    When the person_id cannot be found in database
        DuplicateError: When multiple entries with the same id were found
                        or when modifying an entry to self with existing self

    """
    if all(x is NOT_GIVEN for x in [name, phone_number, relationship, is_self]):
        raise ValueError(
            "No update information given. At least one new field should be provided among "
            "[name, phone_number, relationship, is_self] in order to modify contact"
        )
    # Validate phone number
    validate_phone_number(phone_number)
    # Make sure there won't be duplicate self
    self_entries = search_contacts(is_self=True)
    if self_entries and is_self and self_entries[0]["person_id"] != person_id:
        raise DuplicateError("Self entry already exists. Cannot add another one.")
    current_context = get_current_context()
    contact_database = current_context.get_database(DatabaseNamespace.CONTACT)
    # Check if entry exists
    target_entry = contact_database.filter(pl.col("person_id") == person_id)
    if target_entry.is_empty():
        raise NoDataError(f"No db entry matching {person_id=} found")
    # Check if entry is unique
    target_entry_dicts = target_entry.to_dicts()
    if len(target_entry_dicts) > 1:
        raise DuplicateError(f"More than 1 entry with {person_id=} found")
    target_entry_dict = target_entry_dicts[0]
    # Create updated entry
    for name, value in [
        ("name", name),
        ("phone_number", phone_number),
        ("relationship", relationship),
        ("is_self", is_self),
    ]:
        if value is not NOT_GIVEN:
            target_entry_dict[name] = value
    # Update database
    current_context.remove_from_database(
        namespace=DatabaseNamespace.CONTACT,
        predicate=pl.col("person_id") == person_id,
    )
    current_context.add_to_database(
        namespace=DatabaseNamespace.CONTACT,
        rows=[target_entry_dict],
    )


@register_as_tool(visible_to=(RoleType.AGENT,))
@typechecked
def remove_contact(person_id: str) -> None:
    """Remove an existing contact person to contact database.

    Args:
        person_id:      String format unique identifier of the person to be deleted

    Returns:

    Raises:
        NoDataError:    If the provided person_id was not found
    """
    validate_type(person_id, "person_id", str)

    current_context = get_current_context()
    current_context.remove_from_database(
        namespace=DatabaseNamespace.CONTACT, predicate=pl.col("person_id") == person_id
    )


@register_as_tool(visible_to=(RoleType.AGENT,))
def search_contacts(
    person_id: Union[str, NotGiven] = NOT_GIVEN,
    name: Union[str, NotGiven] = NOT_GIVEN,
    phone_number: Union[str, NotGiven] = NOT_GIVEN,
    relationship: Union[str, NotGiven] = NOT_GIVEN,
    is_self: Union[bool, NotGiven] = NOT_GIVEN,
) -> List[
    Dict[
        Literal["person_id", "name", "phone_number", "relationship", "is_self"],
        str,
    ]
]:
    """Search for a contact person based on provided arguments

    Each field has a search criteria of either
    1. Exact value matching
    2. Fuzzy string matching with a predefined threshold
    Search results contains all contact entries that matched all criteria

    Args:
        person_id:      String format unique identifier for the contact person, will be exact matched
        name:           Name of contact person, will be fuzzy matched
        phone_number:   Phone number of contact person, will be exact matched
        relationship:   Relationship between user and this contact, will be fuzzy matched
        is_self:        If the requested contact corresponds to the current user. Will be exact matched

    Returns:
        A List of matching contacts. An empty List if no matching contacts were found

    Raises:
        ValueError: When all arguments were not provided

    """
    # Validate phone number
    validate_phone_number(phone_number)
    current_context = get_current_context()
    contacts_dataframe = filter_dataframe(
        dataframe=current_context.get_database(namespace=DatabaseNamespace.CONTACT),
        filter_criteria=[
            ("person_id", person_id, exact_match_filter_dataframe),
            ("name", name, fuzzy_match_filter_dataframe),
            ("phone_number", phone_number, exact_match_filter_dataframe),
            (
                "relationship",
                relationship,
                functools.partial(fuzzy_match_filter_dataframe, threshold=90),
            ),
            ("is_self", is_self, exact_match_filter_dataframe),
        ],
    )
    return cast(
        List[
            Dict[
                Literal["person_id", "name", "phone_number", "relationship", "is_self"],
                str,
            ]
        ],
        contacts_dataframe.to_dicts(),
    )

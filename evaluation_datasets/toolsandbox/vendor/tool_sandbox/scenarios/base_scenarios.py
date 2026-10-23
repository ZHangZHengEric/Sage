# For licensing see accompanying LICENSE file.
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
import copy
import datetime
import itertools
from collections import defaultdict
from inspect import getmodule
from typing import Any, Callable, Dict, List

import polars as pl

import tool_sandbox.tools
from tool_sandbox.common.execution_context import DatabaseNamespace, RoleType
from tool_sandbox.common.scenario import Scenario
from tool_sandbox.common.tool_discovery import ToolBackend, find_tools_by_module
from tool_sandbox.common.utils import deterministic_uuid
from tool_sandbox.scenarios.user_simulator_few_shot_examples import (
    named_user_simulator_few_shot_examples,
)


def named_base_scenarios(preferred_tool_backend: ToolBackend) -> Dict[str, Scenario]:
    """Define the base scenario containing boilerplate info other scenarios could expand upon

    Note that this scenario does not contain Evaluation, and is in complete.

    Args:
        preferred_tool_backend: Which backend should be chosen in face of conflicting tool names.

    Returns:
        A Dict containing scenario name and scenario
    """
    scenarios: Dict[str, Scenario] = dict()
    # Find all available tools and form an import. Key is function name, value is function callable object
    tools: Dict[str, Callable[..., Any]] = find_tools_by_module(
        tool_sandbox.tools, preferred_tool_backend=preferred_tool_backend
    )
    # A dict with module name as key, A list of tool function name as value
    module_name_to_tool_names: Dict[str, List[str]] = defaultdict(list)
    for tool_name, tool_callable in tools.items():
        module = getmodule(tool_callable)
        assert module is not None
        module_name_to_tool_names[module.__name__].append(tool_name)
    # Create import statement
    import_statement: str = "import json\n"
    for module_name, tool_names in module_name_to_tool_names.items():
        import_statement += f"from {module_name} import {', '.join(tool_names)}\n"
    # Create base scenario
    scenario = Scenario()
    # Turn on tool tracing
    scenario.starting_context.trace_tool = True
    # Set preferred backend
    scenario.starting_context.preferred_tool_backend = preferred_tool_backend
    # Add starting messages, and a representative few-shot example for user simulator
    user_simulator_few_shot_examples = named_user_simulator_few_shot_examples()
    scenario.starting_context.add_to_database(
        namespace=DatabaseNamespace.SANDBOX,
        rows=[
            {
                "sender": RoleType.SYSTEM,
                "recipient": RoleType.EXECUTION_ENVIRONMENT,
                "content": import_statement,
            },
            {
                "sender": RoleType.SYSTEM,
                "recipient": RoleType.AGENT,
                "content": "Don't make assumptions about what values to plug into functions. "
                "Ask for clarification if a user request is ambiguous.",
            },
            *user_simulator_few_shot_examples[
                "send_message_with_contact_content_cellular_off_multiple_user_turn"
            ],
        ],
    )
    # Add starting database entries
    scenario.starting_context.add_to_database(
        namespace=DatabaseNamespace.CONTACT,
        rows=[
            {
                "person_id": deterministic_uuid(payload="Tomas Haake"),
                "name": "Tomas Haake",
                "phone_number": "+11233344455",
                "relationship": "self",
                "is_self": True,
            },
            {
                "person_id": deterministic_uuid(payload="Fredrik Thordendal"),
                "name": "Fredrik Thordendal",
                "phone_number": "+12453344098",
                "relationship": "friend",
                "is_self": False,
            },
            {
                "person_id": deterministic_uuid(payload="John Petrucci"),
                "name": "John Petrucci",
                "phone_number": "+1234560987",
                "relationship": "friend",
                "is_self": False,
            },
            {
                "person_id": deterministic_uuid(payload="Homer S"),
                "name": "Homer S",
                "phone_number": "+10000000000",
                "relationship": "boss",
                "is_self": False,
            },
        ],
    )
    scenario.starting_context.add_to_database(
        namespace=DatabaseNamespace.MESSAGING,
        rows=[
            {
                "message_id": deterministic_uuid(payload="message_0"),
                "sender_person_id": None,
                "sender_phone_number": "+18307976530",
                "recipient_person_id": deterministic_uuid(payload="Tomas Haake"),
                "recipient_phone_number": "+11233344455",
                "content": "Hey kid, you want some GPU?",
                "creation_timestamp": (
                    datetime.datetime.now()
                    - datetime.timedelta(days=3, hours=4, minutes=5, seconds=6)
                ).timestamp(),
            },
            {
                "message_id": deterministic_uuid(payload="message_1"),
                "sender_person_id": deterministic_uuid(payload="Tomas Haake"),
                "sender_phone_number": "+11233344455",
                "recipient_person_id": None,
                "recipient_phone_number": "+18307976530",
                "content": "No leave me alone",
                "creation_timestamp": (
                    datetime.datetime.now()
                    - datetime.timedelta(days=3, hours=3, minutes=5, seconds=6)
                ).timestamp(),
            },
            {
                "message_id": deterministic_uuid(payload="message_4"),
                "sender_person_id": deterministic_uuid(payload="Homer S"),
                "sender_phone_number": "+10000000000",
                "recipient_person_id": deterministic_uuid(payload="Tomas Haake"),
                "recipient_phone_number": "+11233344455",
                "content": "How's it going",
                "creation_timestamp": (
                    datetime.datetime.now()
                    - datetime.timedelta(hours=1, minutes=3, seconds=3)
                ).timestamp(),
            },
            {
                "message_id": deterministic_uuid(payload="message_2"),
                "sender_person_id": deterministic_uuid(payload="Tomas Haake"),
                "sender_phone_number": "+11233344455",
                "recipient_person_id": deterministic_uuid(payload="Homer S"),
                "recipient_phone_number": "+10000000000",
                "content": "Things are proceeding as expected",
                "creation_timestamp": (
                    datetime.datetime.now()
                    - datetime.timedelta(hours=1, minutes=2, seconds=3)
                ).timestamp(),
            },
            {
                "message_id": deterministic_uuid(payload="message_4"),
                "sender_person_id": deterministic_uuid(payload="Homer S"),
                "sender_phone_number": "+10000000000",
                "recipient_person_id": deterministic_uuid(payload="Tomas Haake"),
                "recipient_phone_number": "+11233344455",
                "content": "Good, keep me posted",
                "creation_timestamp": (
                    datetime.datetime.now() - datetime.timedelta(minutes=1, seconds=2)
                ).timestamp(),
            },
        ],
    )
    scenario.starting_context.add_to_database(
        namespace=DatabaseNamespace.REMINDER,
        rows=[
            {
                "reminder_id": deterministic_uuid(payload="reminder_0"),
                "content": "Look for Company SF tickets",
                "creation_timestamp": (
                    datetime.datetime.now() - datetime.timedelta(days=3)
                ).timestamp(),
                "reminder_timestamp": (
                    datetime.datetime.now() - datetime.timedelta(days=1)
                ).timestamp(),
                "latitude": None,
                "longitude": None,
            },
            {
                "reminder_id": deterministic_uuid(payload="reminder_1"),
                "content": "Buy tickets for Merrily next week",
                "creation_timestamp": (
                    datetime.datetime.now() - datetime.timedelta(days=1)
                ).timestamp(),
                "reminder_timestamp": (
                    datetime.datetime.now() - datetime.timedelta(minutes=1)
                ).timestamp(),
                "latitude": None,
                "longitude": None,
            },
            {
                "reminder_id": deterministic_uuid(payload="reminder_2"),
                "content": "Buy a nice rich navy bathing dress",
                "creation_timestamp": (
                    datetime.datetime.now() - datetime.timedelta(hours=1)
                ).timestamp(),
                "reminder_timestamp": (
                    datetime.datetime.now() + datetime.timedelta(hours=1)
                ).timestamp(),
                "latitude": 37.3237926356735,
                "longitude": -122.03961770355414,
            },
        ],
    )
    # end_conversation should always be allowed
    scenario.starting_context.tool_allow_list = ["end_conversation"]
    # Base scenario
    scenarios["base"] = scenario
    # Create variants that flips low_battery_mode / wifi / location_service / cellular comparing to base scenario
    # Remember that when low_battery_mode is on, all other services must be off
    base_scenario_name = "base"
    for flipped_columns in [
        x
        for i in range(1, 4)
        for x in itertools.combinations(("wifi", "location_service", "cellular"), i)
    ] + [("low_battery_mode", "wifi", "location_service", "cellular")]:
        scenario = copy.deepcopy(scenarios[base_scenario_name])

        scenario.starting_context.update_database(
            namespace=DatabaseNamespace.SETTING,
            dataframe=scenario.starting_context.get_database(
                namespace=DatabaseNamespace.SETTING
            ).with_columns(
                [~pl.col(column).alias(column) for column in flipped_columns]
            ),
        )
        setting_database = scenario.starting_context.get_database(
            namespace=DatabaseNamespace.SETTING
        )
        # Figure out a name for this scenario.
        # Should look something like base_low_battery_mode_on_wifi_off_location_service_off_cellular_off
        scenario_name = (
            base_scenario_name
            + "_"
            + "_".join(
                [
                    f"{column}_{('off', 'on')[int(setting_database[column][0])]}"
                    for column in flipped_columns
                ]
            )
        )
        scenarios[scenario_name] = scenario
    return scenarios

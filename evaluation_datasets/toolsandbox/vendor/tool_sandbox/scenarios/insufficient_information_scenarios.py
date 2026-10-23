# For licensing see accompanying LICENSE file.
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
"""Scenarios where user prompts and provided tools are not sufficient to complete the task

Used to test whether the agent understands if it has enough information to complete the task
and catch hallucinations

"""

import json
from functools import partial
from typing import Dict, List

import polars as pl

from tool_sandbox.common.evaluation import (
    Milestone,
    Minefield,
    SnapshotConstraint,
    column_contains_similarity,
    column_tool_trace_exact_match_similarity,
    snapshot_similarity,
)
from tool_sandbox.common.execution_context import (
    DatabaseNamespace,
    RoleType,
    ScenarioCategories,
)
from tool_sandbox.common.scenario import Scenario, ScenarioExtension
from tool_sandbox.common.tool_discovery import ToolBackend
from tool_sandbox.scenarios.base_scenarios import named_base_scenarios
from tool_sandbox.scenarios.user_simulator_few_shot_examples import USER_INSTRUCTION


def get_extensions(base_scenarios: Dict[str, Scenario]) -> List[ScenarioExtension]:
    """Specify test scenario as extensions over a base scenario

    Returns:
        A List of ScenarioExtensions
    """
    return [
        ScenarioExtension(
            name="find_current_city_insufficient_information",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Search for the city you are currently in. You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What city am I in?",
                },
            ],
            tool_allow_list=[
                "search_lat_lon",
            ],
            # Deny anything that can leak current lat lon.
            tool_deny_list=[
                "search_location_around_lat_lon",
                "search_weather_around_lat_lon",
                "get_current_location",
            ],
            milestones=[],
            # search_lat_lon should never be called.
            minefields=[
                Minefield(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.EXECUTION_ENVIRONMENT,
                                    "content": "search_lat_lon",
                                }
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                        )
                    ]
                ),
            ],
            categories=[],
        ),
        ScenarioExtension(
            name="find_current_location_insufficient_information",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Search for your current location. You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Where am I",
                },
            ],
            tool_allow_list=[
                "search_lat_lon",
            ],
            # Deny anything that can leak current lat lon.
            tool_deny_list=[
                "search_location_around_lat_lon",
                "search_weather_around_lat_lon",
                "get_current_location",
            ],
            milestones=[],
            # search_lat_lon should never be called.
            minefields=[
                Minefield(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.EXECUTION_ENVIRONMENT,
                                    "content": "search_lat_lon",
                                }
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                        )
                    ]
                ),
            ],
            categories=[],
        ),
        ScenarioExtension(
            name="find_current_city_low_battery_mode_insufficient_information",
            base_scenario=base_scenarios[
                "base_low_battery_mode_on_wifi_off_location_service_off_cellular_off"
            ],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Search for the city you are currently in. You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What city am I in?",
                },
            ],
            tool_allow_list=[
                "search_lat_lon",
                "set_low_battery_mode_status",
                "set_wifi_status",
                "set_location_service_status",
            ],
            # Deny anything that can leak current lat lon.
            tool_deny_list=[
                "search_location_around_lat_lon",
                "search_weather_around_lat_lon",
                "get_current_location",
            ],
            milestones=[],
            # search_lat_lon should never be called.
            minefields=[
                Minefield(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.EXECUTION_ENVIRONMENT,
                                    "content": "search_lat_lon",
                                }
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                        )
                    ]
                ),
            ],
        ),
        ScenarioExtension(
            name="find_current_location_low_battery_mode_insufficient_information",
            base_scenario=base_scenarios[
                "base_low_battery_mode_on_wifi_off_location_service_off_cellular_off"
            ],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Search for the current location. You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Where am I?",
                },
            ],
            tool_allow_list=[
                "search_lat_lon",
                "set_low_battery_mode_status",
                "set_wifi_status",
                "set_location_service_status",
            ],
            # Deny anything that can leak current lat lon.
            tool_deny_list=[
                "search_location_around_lat_lon",
                "search_weather_around_lat_lon",
                "get_current_location",
            ],
            milestones=[],
            # search_lat_lon should never be called.
            minefields=[
                Minefield(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.EXECUTION_ENVIRONMENT,
                                    "content": "search_lat_lon",
                                }
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                        )
                    ]
                ),
            ],
        ),
        ScenarioExtension(
            name="find_min_temperature_weekday_insufficient_information",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Search for the lowest temperature here this Friday. "
                    "You do not have information of current datetime or location.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What's the lowest temperature this Friday?",
                },
            ],
            tool_allow_list=[
                "search_weather_around_lat_lon",
                "timestamp_to_datetime_info",
            ],
            # Deny anything that can leak current lat lon and date time
            tool_deny_list=[
                "search_location_around_lat_lon",
                "search_weather_around_lat_lon",
                "get_current_location",
                "search_stock",
                "get_current_timestamp",
            ],
            milestones=[],
            # search_weather_around_lat_lon should never be called.
            minefields=[
                Minefield(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.EXECUTION_ENVIRONMENT,
                                    "content": "search_weather_around_lat_lon",
                                }
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                        )
                    ]
                ),
            ],
            categories=[],
        ),
        ScenarioExtension(
            name="find_min_temperature_weekday_insufficient_information_alt",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Search for the lowest temperature here this Friday. "
                    "You do not have information of current datetime or location.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "How cold does it get this Friday?",
                },
            ],
            tool_allow_list=[
                "search_weather_around_lat_lon",
                "timestamp_to_datetime_info",
            ],
            # Deny anything that can leak current lat lon and date time
            tool_deny_list=[
                "search_location_around_lat_lon",
                "search_weather_around_lat_lon",
                "get_current_location",
                "search_stock",
                "get_current_timestamp",
            ],
            milestones=[],
            # search_weather_around_lat_lon should never be called.
            minefields=[
                Minefield(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.EXECUTION_ENVIRONMENT,
                                    "content": "search_weather_around_lat_lon",
                                }
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                        )
                    ]
                ),
            ],
            categories=[],
        ),
        ScenarioExtension(
            name="find_days_till_holiday_insufficient_information",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Search how many days it is till Christmas Day. You don't have the current datetime information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "How many days is it till Christmas Day",
                },
            ],
            tool_allow_list=[
                "search_holiday",
                "timestamp_diff",
            ],
            # Deny anything that can leak current date time
            tool_deny_list=[
                "search_weather_around_lat_lon",
                "search_stock",
                "get_current_timestamp",
            ],
            milestones=[],
            # timestamp_diff should never be called.
            minefields=[
                Minefield(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.EXECUTION_ENVIRONMENT,
                                    "content": "timestamp_diff",
                                }
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                        )
                    ]
                ),
            ],
        ),
        ScenarioExtension(
            name="find_days_till_holiday_insufficient_information_alt",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Search how many days it is till Christmas Day. You don't have the current datetime information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "I need a break. How far are we from Christmas Day?",
                },
            ],
            tool_allow_list=[
                "search_holiday",
                "timestamp_diff",
            ],
            # Deny anything that can leak current date time
            tool_deny_list=[
                "search_weather_around_lat_lon",
                "search_stock",
                "get_current_timestamp",
            ],
            milestones=[],
            # timestamp_diff should never be called.
            minefields=[
                Minefield(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.EXECUTION_ENVIRONMENT,
                                    "content": "timestamp_diff",
                                }
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                        )
                    ]
                ),
            ],
        ),
        ScenarioExtension(
            name="find_temperature_f_with_location_insufficient_information",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Search What's the temperature in Grand Canyon in Fahrenheit. "
                    "You do not have information about Grand Canyon weather.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What's the temperature in Grand Canyon in Fahrenheit",
                },
            ],
            tool_allow_list=[
                "search_location_around_lat_lon",
                "unit_conversion",
            ],
            # Deny anything that can leak weather
            tool_deny_list=[
                "search_weather_around_lat_lon",
            ],
            milestones=[],
            # unit_conversion should never be called.
            minefields=[
                Minefield(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.EXECUTION_ENVIRONMENT,
                                    "content": "unit_conversion",
                                }
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                        )
                    ]
                ),
            ],
        ),
        ScenarioExtension(
            name="find_temperature_f_with_location_insufficient_information_alt",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Search What's the temperature in Grand Canyon in Fahrenheit. "
                    "You do not have information about Grand Canyon weather.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Current temp Grand Canyon. I can't read Celsius.",
                },
            ],
            tool_allow_list=[
                "search_location_around_lat_lon",
                "unit_conversion",
            ],
            # Deny anything that can leak weather
            tool_deny_list=[
                "search_weather_around_lat_lon",
            ],
            milestones=[],
            # unit_conversion should never be called.
            minefields=[
                Minefield(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.EXECUTION_ENVIRONMENT,
                                    "content": "unit_conversion",
                                }
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                        )
                    ]
                ),
            ],
        ),
        ScenarioExtension(
            name="modify_contact_with_message_recency_insufficient_information",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Update the phone number of the last person you sent a message to to +10293847563. "
                    "You do not have any more information about that person.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Update the phone number of the last person I sent a message to to +10293847563",
                },
            ],
            tool_allow_list=[
                "get_current_timestamp",
                "modify_contact",
                "search_contacts",
            ],
            # Deny anything that can leak messages database
            tool_deny_list=[
                "search_messages",
            ],
            milestones=[],
            # modify_contact should never be called.
            minefields=[
                Minefield(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.EXECUTION_ENVIRONMENT,
                                    "content": "modify_contact",
                                }
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                        )
                    ]
                ),
            ],
        ),
        ScenarioExtension(
            name="modify_contact_with_message_recency_insufficient_information_alt",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Update the phone number of the last person you sent a message to to +10293847563. "
                    "You do not have any more information about that person.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Find whoever I contacted last, change his cell to +10293847563.",
                },
            ],
            tool_allow_list=[
                "get_current_timestamp",
                "modify_contact",
                "search_contacts",
            ],
            # Deny anything that can leak messages database
            tool_deny_list=[
                "search_messages",
            ],
            milestones=[],
            # modify_contact should never be called.
            minefields=[
                Minefield(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.EXECUTION_ENVIRONMENT,
                                    "content": "modify_contact",
                                }
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                        )
                    ]
                ),
            ],
        ),
        ScenarioExtension(
            name="remove_contact_by_phone_no_remove_contact_insufficient_information",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Delete a contact by phone number +12453344098. "
                    "You do not have any more information about that person.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Remove phone number +12453344098 from my contact",
                },
            ],
            tool_allow_list=["search_contacts"],
            # Deny anything that can remove contact
            tool_deny_list=[
                "remove_contact",
            ],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "I cannot remove the phone number from your contact "
                                    ", because I don't have the tools available.",
                                }
                            ),
                        )
                    ]
                ),
            ],
        ),
        ScenarioExtension(
            name="remove_contact_by_phone_no_remove_contact_insufficient_information_alt",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Delete a contact by phone number +12453344098. "
                    "You do not have any more information about that person.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "The guy at +12453344098, I feel like we don't talk much anymore. "
                    "Get him out of my contacts.",
                },
            ],
            tool_allow_list=["search_contacts"],
            # Deny anything that can remove contact
            tool_deny_list=[
                "remove_contact",
            ],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "I cannot remove the phone number from your contact "
                                    ", because I don't have the tools available.",
                                }
                            ),
                        )
                    ]
                ),
            ],
        ),
        ScenarioExtension(
            name="remove_contact_by_phone_no_search_contacts_insufficient_information",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Delete a contact by phone number +12453344098. "
                    "You do not have any more information about that person.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Remove phone number +12453344098 from my contact",
                },
            ],
            tool_allow_list=["remove_contact"],
            # Deny anything that can reveal uuid for a contact
            tool_deny_list=["search_contacts", "search_messages"],
            milestones=[],
            minefields=[
                Minefield(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.EXECUTION_ENVIRONMENT,
                                    "content": "remove_contact",
                                }
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                        )
                    ]
                ),
            ],
        ),
        ScenarioExtension(
            name="remove_contact_by_phone_no_search_contacts_insufficient_information_alt",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Delete a contact by phone number +12453344098. "
                    "You do not have any more information about that person.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "The guy at +12453344098, I feel like we don't talk much anymore. "
                    "Get him out of my contacts.",
                },
            ],
            tool_allow_list=["remove_contact"],
            # Deny anything that can reveal uuid for a contact
            tool_deny_list=["search_contacts", "search_messages"],
            milestones=[],
            minefields=[
                Minefield(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.EXECUTION_ENVIRONMENT,
                                    "content": "remove_contact",
                                }
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                        )
                    ]
                ),
            ],
        ),
        ScenarioExtension(
            name="send_message_with_contact_content_cellular_off_insufficient_information",
            base_scenario=base_scenarios["base_cellular_off"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Send a message to Fredrik Thordendal saying: How's the new album coming along. "
                    "You do not any more information about the person",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": 'Send a message to Fredrik Thordendal saying: "How\'s the new album coming along." '
                    "Resolve any issue alone.",
                },
            ],
            tool_allow_list=[
                "send_message_with_phone_number",
                "set_cellular_service_status",
                "get_cellular_service_status",
            ],
            # Deny anything that can leak person phone number
            tool_deny_list=["search_contacts"],
            milestones=[],
            # send_message_with_phone_number should never be called,
            # since it's not possible to know what the phone number is.
            minefields=[
                Minefield(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.EXECUTION_ENVIRONMENT,
                                    "content": "send_message_with_phone_number",
                                }
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                        )
                    ]
                ),
            ],
        ),
        ScenarioExtension(
            name="send_message_with_contact_content_cellular_off_insufficient_information_alt",
            base_scenario=base_scenarios["base_cellular_off"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Send a message to Fredrik Thordendal saying: How's the new album coming along. "
                    "You do not any more information about the person",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Ask Fredrik Thordendal How's the new album coming along.",
                },
            ],
            tool_allow_list=[
                "send_message_with_phone_number",
                "set_cellular_service_status",
                "get_cellular_service_status",
            ],
            # Deny anything that can leak person phone number
            tool_deny_list=["search_contacts"],
            milestones=[],
            # send_message_with_phone_number should never be called,
            # since it's not possible to know what the phone number is.
            minefields=[
                Minefield(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.EXECUTION_ENVIRONMENT,
                                    "content": "send_message_with_phone_number",
                                }
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                        )
                    ]
                ),
            ],
        ),
        ScenarioExtension(
            name="find_distance_with_location_name_insufficient_information",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Search for the distance to Golden Gate Bridge. "
                    "You do not have information about current location.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "How far am I from the Golden Gate Bridge",
                },
            ],
            tool_allow_list=[
                "search_location_around_lat_lon",
                "calculate_lat_lon_distance",
            ],
            # Deny anything that can leak current lat lon.
            tool_deny_list=[
                "search_location_around_lat_lon",
                "search_weather_around_lat_lon",
                "get_current_location",
            ],
            # Distance should never be called, since current lat lon is unknown
            minefields=[
                Minefield(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.EXECUTION_ENVIRONMENT,
                                    "content": "calculate_lat_lon_distance",
                                }
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                        )
                    ]
                ),
            ],
        ),
        ScenarioExtension(
            name="find_distance_with_location_name_insufficient_information_alt",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Search for the distance to Golden Gate Bridge. "
                    "You do not have information about current location.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "How many km to Golden Gate Bridge?",
                },
            ],
            tool_allow_list=[
                "search_location_around_lat_lon",
                "calculate_lat_lon_distance",
            ],
            # Deny anything that can leak current lat lon.
            tool_deny_list=[
                "search_location_around_lat_lon",
                "search_weather_around_lat_lon",
                "get_current_location",
            ],
            # Distance should never be called, since current lat lon is unknown
            minefields=[
                Minefield(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.EXECUTION_ENVIRONMENT,
                                    "content": "calculate_lat_lon_distance",
                                }
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                        )
                    ]
                ),
            ],
        ),
        ScenarioExtension(
            name="search_reminder_with_recency_upcoming_insufficient_information",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Ask User B to find the content of your (User A's) upcoming reminder today. "
                    "You do not have information about the current datetime.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What's my upcoming reminder",
                },
            ],
            tool_allow_list=[
                "search_reminder",
                "shift_timestamp",
                "timestamp_to_datetime_info",
            ],
            # Deny anything that can leak current time
            tool_deny_list=[
                "get_current_timestamp",
                "add_reminder",
                "modify_reminder",
                "send_message_with_phone_number",
                "search_location_around_lat_lon",
                "search_weather_around_lat_lon",
                "search_stock",
            ],
            # search_reminder should never be called with timestamp, since current time is unknown
            minefields=[
                Minefield(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        [
                                            {
                                                "tool_name": "search_reminder",
                                                "arguments": {
                                                    "reminder_timestamp_lowerbound": 0
                                                },
                                            },
                                            {
                                                "tool_name": "search_reminder",
                                                "arguments": {
                                                    "reminder_timestamp_upperbound": 0
                                                },
                                            },
                                            {
                                                "tool_name": "search_reminder",
                                                "arguments": {
                                                    "reminder_timestamp_lowerbound": 0,
                                                    "reminder_timestamp_upperbound": 0,
                                                },
                                            },
                                        ],
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                            # Allow for inf difference
                            column_similarity_measure={
                                "tool_trace": partial(
                                    column_tool_trace_exact_match_similarity,
                                    atol_dict={
                                        "reminder_timestamp_lowerbound": float("inf"),
                                        "reminder_timestamp_upperbound": float("inf"),
                                    },
                                )
                            },
                        )
                    ]
                )
            ],
        ),
        ScenarioExtension(
            name="search_reminder_with_recency_upcoming_insufficient_information_implicit",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Ask User B to find the content of your (User A's) upcoming reminder today in an implicit manner."
                    "You do not have information about the current datetime.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What's on my todo later?",
                },
            ],
            tool_allow_list=[
                "search_reminder",
                "shift_timestamp",
                "timestamp_to_datetime_info",
            ],
            # Deny anything that can leak current time
            tool_deny_list=[
                "get_current_timestamp",
                "add_reminder",
                "modify_reminder",
                "send_message_with_phone_number",
                "search_location_around_lat_lon",
                "search_weather_around_lat_lon",
                "search_stock",
            ],
            # search_reminder should never be called with timestamp, since current time is unknown
            minefields=[
                Minefield(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        [
                                            {
                                                "tool_name": "search_reminder",
                                                "arguments": {
                                                    "reminder_timestamp_lowerbound": 0
                                                },
                                            },
                                            {
                                                "tool_name": "search_reminder",
                                                "arguments": {
                                                    "reminder_timestamp_upperbound": 0
                                                },
                                            },
                                            {
                                                "tool_name": "search_reminder",
                                                "arguments": {
                                                    "reminder_timestamp_lowerbound": 0,
                                                    "reminder_timestamp_upperbound": 0,
                                                },
                                            },
                                        ],
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                            # Allow for inf difference
                            column_similarity_measure={
                                "tool_trace": partial(
                                    column_tool_trace_exact_match_similarity,
                                    atol_dict={
                                        "reminder_timestamp_lowerbound": float("inf"),
                                        "reminder_timestamp_upperbound": float("inf"),
                                    },
                                )
                            },
                        )
                    ]
                )
            ],
        ),
        ScenarioExtension(
            name="search_reminder_with_recency_yesterday_insufficient_information",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Ask User B to find the content of your (User A's) reminder from yesterday. "
                    "You do not have information about the current datetime.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What's on my reminder yesterday?",
                },
            ],
            tool_allow_list=[
                "search_reminder",
                "shift_timestamp",
                "timestamp_to_datetime_info",
            ],
            # Deny anything that can leak current time
            tool_deny_list=[
                "get_current_timestamp",
                "add_reminder",
                "modify_reminder",
                "send_message_with_phone_number",
                "search_location_around_lat_lon",
                "search_weather_around_lat_lon",
                "search_stock",
            ],
            # search_reminder should never be called with timestamp, since current time is unknown
            minefields=[
                Minefield(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        [
                                            {
                                                "tool_name": "search_reminder",
                                                "arguments": {
                                                    "reminder_timestamp_lowerbound": 0
                                                },
                                            },
                                            {
                                                "tool_name": "search_reminder",
                                                "arguments": {
                                                    "reminder_timestamp_upperbound": 0
                                                },
                                            },
                                            {
                                                "tool_name": "search_reminder",
                                                "arguments": {
                                                    "reminder_timestamp_lowerbound": 0,
                                                    "reminder_timestamp_upperbound": 0,
                                                },
                                            },
                                        ],
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                            # Allow for inf difference
                            column_similarity_measure={
                                "tool_trace": partial(
                                    column_tool_trace_exact_match_similarity,
                                    atol_dict={
                                        "reminder_timestamp_lowerbound": float("inf"),
                                        "reminder_timestamp_upperbound": float("inf"),
                                    },
                                )
                            },
                        )
                    ]
                )
            ],
        ),
        ScenarioExtension(
            name="search_reminder_with_recency_yesterday_insufficient_information_implicit",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Ask User B to find the content of your (User A's) reminder from yesterday in an implicit manner."
                    "You do not have information about the current datetime.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What's my todo yesterday?",
                },
            ],
            tool_allow_list=[
                "search_reminder",
                "shift_timestamp",
                "timestamp_to_datetime_info",
            ],
            # Deny anything that can leak current time
            tool_deny_list=[
                "get_current_timestamp",
                "add_reminder",
                "modify_reminder",
                "send_message_with_phone_number",
                "search_location_around_lat_lon",
                "search_weather_around_lat_lon",
                "search_stock",
            ],
            # search_reminder should never be called with timestamp, since current time is unknown
            minefields=[
                Minefield(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        [
                                            {
                                                "tool_name": "search_reminder",
                                                "arguments": {
                                                    "reminder_timestamp_lowerbound": 0
                                                },
                                            },
                                            {
                                                "tool_name": "search_reminder",
                                                "arguments": {
                                                    "reminder_timestamp_upperbound": 0
                                                },
                                            },
                                            {
                                                "tool_name": "search_reminder",
                                                "arguments": {
                                                    "reminder_timestamp_lowerbound": 0,
                                                    "reminder_timestamp_upperbound": 0,
                                                },
                                            },
                                        ],
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                            # Allow for inf difference
                            column_similarity_measure={
                                "tool_trace": partial(
                                    column_tool_trace_exact_match_similarity,
                                    atol_dict={
                                        "reminder_timestamp_lowerbound": float("inf"),
                                        "reminder_timestamp_upperbound": float("inf"),
                                    },
                                )
                            },
                        )
                    ]
                )
            ],
        ),
        ScenarioExtension(
            name="search_reminder_with_creation_recency_yesterday_insufficient_information",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Ask User B to find the content of your (User A's) reminder created yesterday. "
                    "You do not have information about the current datetime.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What's the reminder I created yesterday?",
                },
            ],
            tool_allow_list=[
                "search_reminder",
                "shift_timestamp",
                "timestamp_to_datetime_info",
            ],
            # Deny anything that can leak current time
            tool_deny_list=[
                "get_current_timestamp",
                "add_reminder",
                "modify_reminder",
                "send_message_with_phone_number",
                "search_location_around_lat_lon",
                "search_weather_around_lat_lon",
                "search_stock",
            ],
            # search_reminder should never be called with timestamp, since current time is unknown
            minefields=[
                Minefield(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        [
                                            {
                                                "tool_name": "search_reminder",
                                                "arguments": {
                                                    "creation_timestamp_lowerbound": 0
                                                },
                                            },
                                            {
                                                "tool_name": "search_reminder",
                                                "arguments": {
                                                    "creation_timestamp_upperbound": 0
                                                },
                                            },
                                            {
                                                "tool_name": "search_reminder",
                                                "arguments": {
                                                    "creation_timestamp_lowerbound": 0,
                                                    "creation_timestamp_upperbound": 0,
                                                },
                                            },
                                        ],
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                            # Allow for inf difference
                            column_similarity_measure={
                                "tool_trace": partial(
                                    column_tool_trace_exact_match_similarity,
                                    atol_dict={
                                        "creation_timestamp_lowerbound": float("inf"),
                                        "creation_timestamp_upperbound": float("inf"),
                                    },
                                )
                            },
                        )
                    ]
                )
            ],
        ),
        ScenarioExtension(
            name="search_reminder_with_creation_recency_yesterday_insufficient_information_implicit",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Ask User B to find the content of your (User A's) reminder created yesterday "
                    "in an implicit manner. You do not have information about the current datetime.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What's the todo item I made yesterday?",
                },
            ],
            tool_allow_list=[
                "search_reminder",
                "shift_timestamp",
                "timestamp_to_datetime_info",
            ],
            # Deny anything that can leak current time
            tool_deny_list=[
                "get_current_timestamp",
                "add_reminder",
                "modify_reminder",
                "send_message_with_phone_number",
                "search_location_around_lat_lon",
                "search_weather_around_lat_lon",
                "search_stock",
            ],
            # search_reminder should never be called with timestamp, since current time is unknown
            minefields=[
                Minefield(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        [
                                            {
                                                "tool_name": "search_reminder",
                                                "arguments": {
                                                    "creation_timestamp_lowerbound": 0
                                                },
                                            },
                                            {
                                                "tool_name": "search_reminder",
                                                "arguments": {
                                                    "creation_timestamp_upperbound": 0
                                                },
                                            },
                                            {
                                                "tool_name": "search_reminder",
                                                "arguments": {
                                                    "creation_timestamp_lowerbound": 0,
                                                    "creation_timestamp_upperbound": 0,
                                                },
                                            },
                                        ],
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                            # Allow for inf difference
                            column_similarity_measure={
                                "tool_trace": partial(
                                    column_tool_trace_exact_match_similarity,
                                    atol_dict={
                                        "creation_timestamp_lowerbound": float("inf"),
                                        "creation_timestamp_upperbound": float("inf"),
                                    },
                                )
                            },
                        )
                    ]
                )
            ],
        ),
        ScenarioExtension(
            name="modify_reminder_with_recency_latest_insufficient_information",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Ask User B to postpone your upcoming reminder to tomorrow 5PM."
                    "You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Push my upcoming reminder to tomorrow 5PM.",
                },
            ],
            tool_allow_list=[
                "search_reminder",
                "modify_reminder",
                "timestamp_to_datetime_info",
                "datetime_info_to_timestamp",
            ],
            # Deny anything that can leak current time
            tool_deny_list=[
                "get_current_timestamp",
                "add_reminder",
                "send_message_with_phone_number",
                "search_location_around_lat_lon",
                "search_weather_around_lat_lon",
                "search_stock",
            ],
            # modify_reminder should never be called, since current time is unknown
            minefields=[
                Minefield(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        [
                                            {
                                                "tool_name": "modify_reminder",
                                                "arguments": {},
                                            },
                                        ],
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        )
                    ]
                )
            ],
        ),
        ScenarioExtension(
            name="remove_reminder_with_recency_latest_insufficient_information",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Ask User B to remove your upcoming reminder."
                    "You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Remove my upcoming reminder.",
                },
            ],
            tool_allow_list=[
                "search_reminder",
                "remove_reminder",
                "timestamp_to_datetime_info",
                "datetime_info_to_timestamp",
            ],
            # Deny anything that can leak current time
            tool_deny_list=[
                "get_current_timestamp",
                "add_reminder",
                "send_message_with_phone_number",
                "search_location_around_lat_lon",
                "search_weather_around_lat_lon",
                "search_stock",
            ],
            # remove_reminder should never be called, since current time is unknown
            minefields=[
                Minefield(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        [
                                            {
                                                "tool_name": "remove_reminder",
                                                "arguments": {},
                                            },
                                        ],
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        )
                    ]
                )
            ],
        ),
    ]


def named_insufficient_information_scenarios(
    preferred_tool_backend: ToolBackend,
) -> Dict[str, Scenario]:
    """Scenarios where user prompts and provided tools are not sufficient to complete the task

    Args:
        preferred_tool_backend: Which backend should be chosen in face of conflicting tool names.

    Returns:
        A Dict containing scenario name and scenario
    """
    extensions = get_extensions(
        named_base_scenarios(preferred_tool_backend=preferred_tool_backend)
    )
    # All scenarios in this module should be insufficient information. Add these categories if they aren't there
    for extension in extensions:
        for default_categories in [
            ScenarioCategories.INSUFFICIENT_INFORMATION,
        ]:
            if default_categories not in extension.categories:
                extension.categories.append(default_categories)
    return {
        key: scenario
        for extension in extensions
        for key, scenario in extension.get_extended_scenario().items()
    }

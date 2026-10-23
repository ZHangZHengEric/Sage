# For licensing see accompanying LICENSE file.
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
"""Simple Scenarios which only requires 1 tool call to be issued"""


import json
from functools import partial
from typing import Dict, List

import polars as pl

from tool_sandbox.common.evaluation import (
    Milestone,
    SnapshotConstraint,
    addition_similarity,
    column_contains_similarity,
    column_exact_match_similarity,
    removal_similarity,
    snapshot_similarity,
    tool_trace_dependant_similarity,
    update_similarity,
)
from tool_sandbox.common.execution_context import (
    DatabaseNamespace,
    RoleType,
    ScenarioCategories,
)
from tool_sandbox.common.scenario import Scenario, ScenarioExtension
from tool_sandbox.common.tool_discovery import ToolBackend
from tool_sandbox.common.tool_trace_extractors import (
    search_weather_around_lat_lon_temperature_extractor,
)
from tool_sandbox.common.utils import deterministic_uuid
from tool_sandbox.scenarios.base_scenarios import named_base_scenarios
from tool_sandbox.scenarios.user_simulator_few_shot_examples import USER_INSTRUCTION


def get_extensions(base_scenarios: Dict[str, Scenario]) -> List[ScenarioExtension]:
    """Specify test scenario as extensions over a base scenario

    Returns:
        A List of ScenarioExtensions
    """
    return [
        ScenarioExtension(
            name="cellular_off",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION + "Turn off cellular service",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Turn off cellular",
                },
            ],
            tool_allow_list=["set_cellular_service_status"],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SETTING,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "cellular": False,
                                }
                            ),
                        )
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "Cellular service is turned off",
                                }
                            ),
                        )
                    ]
                ),
            ],
        ),
        ScenarioExtension(
            name="get_cellular",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION + "Check cellular service",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Is my cellular service on?",
                },
            ],
            tool_allow_list=["get_cellular_service_status"],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        {
                                            "tool_name": "get_cellular_service_status",
                                            "arguments": {},
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        )
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "Cellular service is on",
                                }
                            ),
                        )
                    ]
                ),
            ],
        ),
        ScenarioExtension(
            name="wifi_off",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION + "Turn off wifi",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Turn off wifi",
                },
            ],
            tool_allow_list=["set_wifi_status"],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SETTING,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "wifi": False,
                                }
                            ),
                        )
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "Wifi is turned off",
                                }
                            ),
                        )
                    ]
                ),
            ],
        ),
        ScenarioExtension(
            name="get_wifi",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION + "Check wifi status",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Is my wifi on?",
                },
            ],
            tool_allow_list=["get_wifi_status"],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        {
                                            "tool_name": "get_wifi_status",
                                            "arguments": {},
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        )
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "Wifi is on",
                                }
                            ),
                        )
                    ]
                ),
            ],
        ),
        ScenarioExtension(
            name="search_phone_number_with_name",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Search for Homer S's phone number. It should be +10000000000. "
                    "Do not leak this information. You do not have more information about Homer S.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What is Homer S's phone number?",
                },
            ],
            tool_allow_list=["search_contacts"],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        {
                                            "tool_name": "search_contacts",
                                            "arguments": {"name": "Homer S"},
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        )
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "I found Homer S's phone number: +10000000000",
                                }
                            ),
                        ),
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "+10000000000",
                                },
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                        ),
                    ]
                ),
            ],
        ),
        ScenarioExtension(
            name="search_name_with_relationship",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Search for your (User A's) boss's name. It should be Homer S. "
                    "Do not leak this information. You do not have more information about your boss.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What is the name of my boss?",
                },
            ],
            tool_allow_list=["search_contacts"],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        {
                                            "tool_name": "search_contacts",
                                            "arguments": {"relationship": "boss"},
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        )
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "Your boss is Homer S",
                                }
                            ),
                        )
                    ]
                ),
            ],
        ),
        ScenarioExtension(
            name="search_relationship_with_phone_number",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Find out your (User A's) relationship with the person who's phone number is +10000000000. "
                    "It should be boss. "
                    "Do not leak this information. You do not have more information about this person.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What's my relationship with +10000000000",
                },
            ],
            tool_allow_list=["search_contacts"],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        {
                                            "tool_name": "search_contacts",
                                            "arguments": {
                                                "phone_number": "+10000000000"
                                            },
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        )
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "+10000000000 is your boss",
                                }
                            ),
                        )
                    ]
                ),
            ],
        ),
        ScenarioExtension(
            name="add_contact_with_name_and_phone_number",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Add a contact named Stephen Sondheim with phone number +19876543210. "
                    "You do not have more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Add Stephen Sondheim to my contact, his phone_number is +19876543210",
                },
            ],
            tool_allow_list=["add_contact"],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.CONTACT,
                            snapshot_constraint=addition_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "name": "Stephen Sondheim",
                                    "phone_number": "+19876543210",
                                    "relationship": None,
                                },
                                schema={
                                    "name": pl.String,
                                    "phone_number": pl.String,
                                    "relationship": pl.String,
                                },
                            ),
                            column_similarity_measure={
                                "relationship": column_exact_match_similarity
                            },
                            reference_milestone_node_index=-1,
                        )
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "Stephen Sondheim has been added to your contact",
                                }
                            ),
                        )
                    ]
                ),
            ],
        ),
        ScenarioExtension(
            name="remove_contact_with_id",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Delete a contact by id "
                    + deterministic_uuid(payload="Fredrik Thordendal")
                    + ". You do not have more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": f"Remove id {deterministic_uuid(payload='Fredrik Thordendal')} "
                    f"from my contact",
                },
            ],
            tool_allow_list=["remove_contact"],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.CONTACT,
                            snapshot_constraint=removal_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "person_id": deterministic_uuid(
                                        payload="Fredrik Thordendal",
                                    ),
                                }
                            ),
                            reference_milestone_node_index=-1,
                        )
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": f"{deterministic_uuid(payload='Fredrik Thordendal')} "
                                    f"has been removed from your contact",
                                }
                            ),
                        )
                    ]
                ),
            ],
        ),
        ScenarioExtension(
            name="update_contact_with_id_and_phone_number",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Update the phone number of contact by id "
                    + deterministic_uuid(payload="Fredrik Thordendal")
                    + " to +19876543210. "
                    "You do not have more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": f"Update phone number of the person with id "
                    f"{deterministic_uuid(payload='Fredrik Thordendal')} "
                    f" to +19876543210",
                },
            ],
            tool_allow_list=["modify_contact"],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.CONTACT,
                            snapshot_constraint=update_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "person_id": deterministic_uuid(
                                        payload="Fredrik Thordendal",
                                    ),
                                    "name": "Fredrik Thordendal",
                                    "phone_number": "+19876543210",
                                    "relationship": "friend",
                                    "is_self": False,
                                },
                            ),
                            reference_milestone_node_index=-1,
                        )
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": f"{deterministic_uuid(payload='Fredrik Thordendal')}'s "
                                    f" phone number have been updated to +19876543210",
                                }
                            ),
                        )
                    ]
                ),
            ],
        ),
        ScenarioExtension(
            name="search_sender_phone_number_with_content",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Find which phone number asked you (User A) if you want some GPUs. It should be +18307976530. "
                    "Do not leak this information. You do not have more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Which phone number asked me if I want some GPUs?",
                },
            ],
            tool_allow_list=["search_messages"],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        {
                                            "tool_name": "search_messages",
                                            "arguments": {},
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        )
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "+18307976530 asked you if you want some GPUs",
                                }
                            ),
                        )
                    ]
                ),
            ],
        ),
        ScenarioExtension(
            name="send_message_with_phone_number_and_content",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Send a message to +12453344098 saying: How's the new album coming along. "
                    "You do not have more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Send a message to +12453344098 saying: How's the new album coming along",
                },
            ],
            tool_allow_list=["send_message_with_phone_number"],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.MESSAGING,
                            snapshot_constraint=addition_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "recipient_phone_number": "+12453344098",
                                    "content": "How's the new album coming along",
                                },
                            ),
                            reference_milestone_node_index=-1,
                        )
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "Your message to +12453344098 has been sent saying: "
                                    "How's the new album coming along",
                                }
                            ),
                        )
                    ]
                ),
            ],
        ),
        ScenarioExtension(
            name="find_thanksgiving_timestamp",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Search what is the timestamp for Thanksgiving. "
                    "You do not have more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What is the timestamp for Thanksgiving",
                },
            ],
            tool_allow_list=["search_holiday"],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        {
                                            "tool_name": "search_holiday",
                                            "arguments": {
                                                "holiday_name": "Thanksgiving",
                                                "year": None,
                                            },
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        )
                    ]
                ),
            ],
        ),
        ScenarioExtension(
            name="find_address_with_lat_lon",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Search for the address of lattitude: 37.334606, longitude: -122.009102. "
                    "You do not have more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What is the address of lattitude: 37.334606, longitude: -122.009102",
                },
            ],
            tool_allow_list=["search_lat_lon"],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        {
                                            "tool_name": "search_lat_lon",
                                            "arguments": {
                                                "latitude": 37.334606,
                                                "longitude": -122.009102,
                                            },
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        )
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "The address for lattitude: 37.334606, longitude: -122.009102 is "
                                    "Apple Park 1 Apple Park Way Cupertino, CA 95014 United States",
                                }
                            ),
                        )
                    ]
                ),
            ],
        ),
        ScenarioExtension(
            name="find_phone_number_with_location_name",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Search for the phone number of Apple Park. It should be +14089961010. "
                    "Do not leak this information. You do not have more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What's the phone number of Apple Park",
                },
            ],
            tool_allow_list=["search_location_around_lat_lon"],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        {
                                            "tool_name": "search_location_around_lat_lon",
                                            "arguments": {
                                                "location": "Apple Park",
                                                "latitude": None,
                                                "longitude": None,
                                            },
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        )
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "The phone number for Apple Park is +14089961010",
                                }
                            ),
                        )
                    ]
                ),
            ],
            categories=[ScenarioCategories.CANONICALIZATION],
        ),
        ScenarioExtension(
            name="find_temperature",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Search for current temperature. You do not have information about current location or time.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What's the temperature here right now",
                },
            ],
            tool_allow_list=["search_weather_around_lat_lon"],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        {
                                            "tool_name": "search_weather_around_lat_lon",
                                            "arguments": {
                                                "days": 0,
                                                "latitude": None,
                                                "longitude": None,
                                            },
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        )
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=partial(
                                tool_trace_dependant_similarity,
                                fill_to="content",
                                extractor=search_weather_around_lat_lon_temperature_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "The current temperature is {temperature} Celsius",
                                }
                            ),
                            reference_milestone_node_index=0,
                        )
                    ]
                ),
            ],
            categories=[ScenarioCategories.CANONICALIZATION],
        ),
        ScenarioExtension(
            name="find_stock_symbol_with_company_name",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION + "Search for stock symbol for Apple. "
                    "You do not have more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What's the stock symbol for Apple",
                },
            ],
            tool_allow_list=["search_stock"],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        {
                                            "tool_name": "search_stock",
                                            "arguments": {
                                                "query": "Apple",
                                            },
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        )
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "The stock symbol for Apple is AAPL",
                                }
                            ),
                        )
                    ]
                ),
            ],
        ),
        ScenarioExtension(
            name="convert_currency",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Convert 2048 USD to CNY. You do not have more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "How much is 2048 USD in CNY",
                },
            ],
            tool_allow_list=["convert_currency"],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        {
                                            "tool_name": "convert_currency",
                                            "arguments": {
                                                "amount": 2048,
                                                "from_currency_code": "USD",
                                                "to_currency_code": "CNY",
                                            },
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        )
                    ]
                ),
            ],
            categories=[ScenarioCategories.CANONICALIZATION],
        ),
        ScenarioExtension(
            name="convert_currency_canonicalize",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Convert 2048 USD to CNY. You do not have more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "How much is $2.048k in CNY",
                },
            ],
            tool_allow_list=["convert_currency"],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        {
                                            "tool_name": "convert_currency",
                                            "arguments": {
                                                "amount": 2048,
                                                "from_currency_code": "USD",
                                                "to_currency_code": "CNY",
                                            },
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        )
                    ]
                ),
            ],
            categories=[ScenarioCategories.CANONICALIZATION],
        ),
    ]


def named_single_tool_call_scenarios(
    preferred_tool_backend: ToolBackend,
) -> Dict[str, Scenario]:
    """Scenarios where only 1 tool call is required to get the job done

    Note that this differs from the simple / multi definition of Gorilla. All scenarios below have only the necessary
    tools provided to the model. Additional scenarios will be created to introduce distractions as well.

    Args:
        preferred_tool_backend: Which backend should be chosen in face of conflicting tool names.

    Returns:
        A Dict containing scenario name and scenario
    """
    extensions = get_extensions(
        named_base_scenarios(preferred_tool_backend=preferred_tool_backend)
    )
    # All scenarios in this module should be single user turn, single tool. Add these categories if they aren't there
    for extension in extensions:
        for default_categories in [
            ScenarioCategories.SINGLE_TOOL_CALL,
            ScenarioCategories.SINGLE_USER_TURN,
        ]:
            if default_categories not in extension.categories:
                extension.categories.append(default_categories)
    return {
        key: scenario
        for extension in extensions
        for key, scenario in extension.get_extended_scenario().items()
    }

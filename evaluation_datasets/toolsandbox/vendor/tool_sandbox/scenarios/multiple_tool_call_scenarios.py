# For licensing see accompanying LICENSE file.
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
"""Scenarios where more than 1 tool call to be issued to complete the task"""

import datetime

import json
from functools import partial

import polars as pl

from tool_sandbox.common.evaluation import (
    Milestone,
    SnapshotConstraint,
    addition_similarity,
    column_close_similarity,
    column_contains_similarity,
    column_tool_trace_exact_match_similarity,
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
    current_temperature_extractor,
    days_extractor,
    lat_lon_dict_extractor,
    result_to_reminder_timestamp_lowerbound_extractor,
    result_to_temperature_extractor,
    result_to_timestamp0_extractor,
    result_to_timestamp1_extractor,
    search_weather_around_lat_lon_temperature_extractor,
)
from tool_sandbox.common.utils import (
    deterministic_uuid,
    get_next_iso_weekday_datetime,
    get_tomorrow_datetime,
)
from tool_sandbox.scenarios.base_scenarios import named_base_scenarios
from tool_sandbox.scenarios.user_simulator_few_shot_examples import (
    USER_INSTRUCTION,
    named_user_simulator_few_shot_examples,
)


def get_extensions(base_scenarios: dict[str, Scenario]) -> list[ScenarioExtension]:
    """Specify test scenario as extensions over a base scenario

    Returns:
        A list of ScenarioExtensions
    """
    user_simulator_few_shot_examples = named_user_simulator_few_shot_examples()
    return [
        ScenarioExtension(
            name="search_message_with_recency_latest",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Ask User B to find the content of your (User A's) most recent message. "
                    "It should be Good, keep me posted. "
                    "Do not leak this information. You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What does my most recent message say?",
                },
            ],
            tool_allow_list=["search_messages", "get_current_timestamp"],
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
                                    "content": "Your most recent message says 'Good, keep me posted'.",
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
                                    "content": "Good, keep me posted",
                                }
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
            name="search_message_with_recency_latest_alt",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Ask User B to find the content of your (User A's) most recent message. "
                    "It should be Good, keep me posted. "
                    "Do not leak this information. You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What does my latest text say?",
                },
            ],
            tool_allow_list=["search_messages", "get_current_timestamp"],
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
                                    "content": "Your most recent message says 'Good, keep me posted'.",
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
                                    "content": "Good, keep me posted",
                                }
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
            name="search_message_with_recency_oldest",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Find content of your (User A's) oldest message. It should be Hey kid, you want some GPU? "
                    "Do not leak this information. You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What does my oldest message say?",
                },
            ],
            tool_allow_list=["search_messages", "get_current_timestamp"],
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
                                            "tool_name": "get_current_timestamp",
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
                                    "content": "Your oldest message says 'Hey kid, you want some GPU?'.",
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
                                    "content": "Hey kid, you want some GPU?",
                                }
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
            name="search_message_with_recency_oldest_alt",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Find content of your (User A's) oldest message. It should be Hey kid, you want some GPU? "
                    "Do not leak this information. You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What's the first ever text I have?",
                },
            ],
            tool_allow_list=["search_messages", "get_current_timestamp"],
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
                                            "tool_name": "get_current_timestamp",
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
                                    "content": "Your first ever text says 'Hey kid, you want some GPU?'.",
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
                                    "content": "Hey kid, you want some GPU?",
                                }
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
            name="modify_contact_with_message_recency",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Update the phone number of the last person you (User A) sent a message to to +10293847563. "
                    "You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Update the phone number of the last person I sent a message to to +10293847563",
                },
            ],
            tool_allow_list=[
                "search_messages",
                "get_current_timestamp",
                "modify_contact",
                "search_contacts",
            ],
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
                                            "tool_name": "get_current_timestamp",
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
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        {
                                            "tool_name": "search_contacts",
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
                            database_namespace=DatabaseNamespace.CONTACT,
                            snapshot_constraint=update_similarity,
                            target_dataframe=pl.DataFrame(
                                [
                                    {
                                        "person_id": deterministic_uuid(
                                            payload="Homer S",
                                        ),
                                        "phone_number": "+10293847563",
                                    },
                                ],
                            ),
                            reference_milestone_node_index=2,
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
                                    "content": "The phone number of the person you last talked to"
                                    " has been updated to +10293847563.",
                                }
                            ),
                        )
                    ]
                ),
            ],
            categories=[ScenarioCategories.CANONICALIZATION],
            milestone_edge_list=[(0, 2), (1, 4), (2, 3), (3, 4)],
        ),
        ScenarioExtension(
            name="modify_contact_with_message_recency_alt",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Update the phone number of the last person you (User A) sent a message to to +10293847563. "
                    "You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Find whoever I contacted last, change his cell to +10293847563.",
                },
            ],
            tool_allow_list=[
                "search_messages",
                "get_current_timestamp",
                "modify_contact",
                "search_contacts",
            ],
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
                                            "tool_name": "get_current_timestamp",
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
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        {
                                            "tool_name": "search_contacts",
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
                            database_namespace=DatabaseNamespace.CONTACT,
                            snapshot_constraint=update_similarity,
                            target_dataframe=pl.DataFrame(
                                [
                                    {
                                        "person_id": deterministic_uuid(
                                            payload="Homer S",
                                        ),
                                        "phone_number": "+10293847563",
                                    },
                                ],
                            ),
                            reference_milestone_node_index=2,
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
                                    "content": "The phone number of the person you last talked to"
                                    " has been updated to +10293847563.",
                                }
                            ),
                        )
                    ]
                ),
            ],
            categories=[ScenarioCategories.CANONICALIZATION],
            milestone_edge_list=[(0, 2), (1, 4), (2, 3), (3, 4)],
        ),
        ScenarioExtension(
            name="remove_contact_by_phone",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Delete a contact by phone number +12453344098. "
                    "You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Remove phone number +12453344098 from my contact",
                },
            ],
            tool_allow_list=["search_contacts", "remove_contact"],
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
                                                "phone_number": "+12453344098"
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
                            database_namespace=DatabaseNamespace.CONTACT,
                            snapshot_constraint=removal_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "person_id": deterministic_uuid(
                                        payload="Fredrik Thordendal",
                                    ),
                                }
                            ),
                            reference_milestone_node_index=0,
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
                                    "content": "Phone number +12453344098 has been removed from your contact",
                                }
                            ),
                        )
                    ]
                ),
            ],
            categories=[ScenarioCategories.CANONICALIZATION],
        ),
        ScenarioExtension(
            name="remove_contact_by_phone_alt",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Delete a contact by phone number +12453344098. "
                    "You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "The guy at +12453344098, I feel like we don't talk much anymore. "
                    "Get him out of my contacts.",
                },
            ],
            tool_allow_list=["search_contacts", "remove_contact"],
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
                                                "phone_number": "+12453344098"
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
                            database_namespace=DatabaseNamespace.CONTACT,
                            snapshot_constraint=removal_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "person_id": deterministic_uuid(
                                        payload="Fredrik Thordendal",
                                    ),
                                }
                            ),
                            reference_milestone_node_index=0,
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
                                    "content": "Phone number +12453344098 has been removed from your contact",
                                }
                            ),
                        )
                    ]
                ),
            ],
            categories=[ScenarioCategories.CANONICALIZATION],
        ),
        ScenarioExtension(
            name="remove_contact_by_phone_ambiguous",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Delete a contact by phone number +12453344098. "
                    "You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Remove +12453344098 from my contact",
                },
            ],
            tool_allow_list=["search_contacts", "remove_contact"],
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
                                                "phone_number": "+12453344098"
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
                            database_namespace=DatabaseNamespace.CONTACT,
                            snapshot_constraint=removal_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "person_id": deterministic_uuid(
                                        payload="Fredrik Thordendal",
                                    ),
                                }
                            ),
                            reference_milestone_node_index=0,
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
                                    "content": "Phone number +12453344098 has been removed from your contact",
                                }
                            ),
                        )
                    ]
                ),
            ],
            categories=[ScenarioCategories.CANONICALIZATION],
        ),
        ScenarioExtension(
            name="remove_contact_by_phone_ambiguous_alt",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Delete a contact by phone number +12453344098. "
                    "You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Get rid of +12453344098",
                },
            ],
            tool_allow_list=["search_contacts", "remove_contact"],
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
                                                "phone_number": "+12453344098"
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
                            database_namespace=DatabaseNamespace.CONTACT,
                            snapshot_constraint=removal_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "person_id": deterministic_uuid(
                                        payload="Fredrik Thordendal",
                                    ),
                                }
                            ),
                            reference_milestone_node_index=0,
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
                                    "content": "Phone number +12453344098 has been removed from your contact",
                                }
                            ),
                        )
                    ]
                ),
            ],
            categories=[ScenarioCategories.CANONICALIZATION],
        ),
        ScenarioExtension(
            name="turn_on_wifi_low_battery_mode",
            base_scenario=base_scenarios[
                "base_low_battery_mode_on_wifi_off_location_service_off_cellular_off"
            ],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION + "Turn on wifi",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Turn on wifi",
                },
            ],
            tool_allow_list=[
                "set_wifi_status",
                "set_low_battery_mode_status",
                "get_wifi_status",
                "get_low_battery_mode_status",
            ],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SETTING,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "low_battery_mode": False,
                                }
                            ),
                        )
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SETTING,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "wifi": True,
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
                                    "content": "Wifi has been turned on.",
                                }
                            ),
                        )
                    ]
                ),
            ],
            categories=[ScenarioCategories.STATE_DEPENDENCY],
        ),
        ScenarioExtension(
            name="turn_on_wifi_low_battery_mode_implicit",
            base_scenario=base_scenarios[
                "base_low_battery_mode_on_wifi_off_location_service_off_cellular_off"
            ],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION + "Turn on wifi, but be implicit.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Get me connected to the internet.",
                },
            ],
            tool_allow_list=[
                "set_wifi_status",
                "set_low_battery_mode_status",
                "get_wifi_status",
                "get_low_battery_mode_status",
            ],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SETTING,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "low_battery_mode": False,
                                }
                            ),
                        )
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SETTING,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "wifi": True,
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
                                    "content": "Wifi has been turned on.",
                                }
                            ),
                        )
                    ]
                ),
            ],
            categories=[ScenarioCategories.STATE_DEPENDENCY],
        ),
        ScenarioExtension(
            name="turn_on_cellular_low_battery_mode",
            base_scenario=base_scenarios[
                "base_low_battery_mode_on_wifi_off_location_service_off_cellular_off"
            ],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION + "Turn on cellular",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Turn on cellular",
                },
            ],
            tool_allow_list=[
                "set_cellular_service_status",
                "set_low_battery_mode_status",
                "get_cellular_service_status",
                "get_low_battery_mode_status",
            ],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SETTING,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "low_battery_mode": False,
                                }
                            ),
                        )
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SETTING,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "cellular": True,
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
                                    "content": "Cellular service has been turned on.",
                                }
                            ),
                        )
                    ]
                ),
            ],
            categories=[ScenarioCategories.STATE_DEPENDENCY],
        ),
        ScenarioExtension(
            name="turn_on_cellular_low_battery_mode_implicit",
            base_scenario=base_scenarios[
                "base_low_battery_mode_on_wifi_off_location_service_off_cellular_off"
            ],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION + "Turn on cellular, but be implicit.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "I don't have cellphone signal. Can you get it on?",
                },
            ],
            tool_allow_list=[
                "set_cellular_service_status",
                "set_low_battery_mode_status",
                "get_cellular_service_status",
                "get_low_battery_mode_status",
            ],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SETTING,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "low_battery_mode": False,
                                }
                            ),
                        )
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SETTING,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "cellular": True,
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
                                    "content": "Cellular service has been turned on.",
                                }
                            ),
                        )
                    ]
                ),
            ],
            categories=[ScenarioCategories.STATE_DEPENDENCY],
        ),
        ScenarioExtension(
            name="turn_on_location_low_battery_mode",
            base_scenario=base_scenarios[
                "base_low_battery_mode_on_wifi_off_location_service_off_cellular_off"
            ],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION + "Turn on location service",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Turn on location service",
                },
            ],
            tool_allow_list=[
                "set_location_service_status",
                "set_low_battery_mode_status",
                "get_location_service_status",
                "get_low_battery_mode_status",
            ],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SETTING,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "low_battery_mode": False,
                                }
                            ),
                        )
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SETTING,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "location_service": True,
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
                                    "content": "Location service has been turned on.",
                                }
                            ),
                        )
                    ]
                ),
            ],
            categories=[ScenarioCategories.STATE_DEPENDENCY],
        ),
        ScenarioExtension(
            name="turn_on_location_low_battery_mode_implicit",
            base_scenario=base_scenarios[
                "base_low_battery_mode_on_wifi_off_location_service_off_cellular_off"
            ],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Turn on location service, but be implicit.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "I can't access my current location. Can you help me fix that in settings?",
                },
            ],
            tool_allow_list=[
                "set_location_service_status",
                "set_low_battery_mode_status",
                "get_location_service_status",
                "get_low_battery_mode_status",
            ],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SETTING,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "low_battery_mode": False,
                                }
                            ),
                        )
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SETTING,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "location_service": True,
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
                                    "content": "Location service has been turned on.",
                                }
                            ),
                        )
                    ]
                ),
            ],
            categories=[ScenarioCategories.STATE_DEPENDENCY],
        ),
        ScenarioExtension(
            name="send_message_with_contact_content_cellular_off",
            base_scenario=base_scenarios["base_cellular_off"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Send a message to Fredrik Thordendal saying: How's the new album coming along. "
                    "You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": 'Send a message to Fredrik Thordendal saying: "How\'s the new album coming along." '
                    "Resolve any issue alone.",
                },
            ],
            tool_allow_list=[
                "search_contacts",
                "send_message_with_phone_number",
                "set_cellular_service_status",
                "get_cellular_service_status",
            ],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SETTING,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "cellular": True,
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
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        {
                                            "tool_name": "search_contacts",
                                            "arguments": {"name": "Fredrik Thordendal"},
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        )
                    ],
                    guardrail_database_exclusion_list=[DatabaseNamespace.SETTING],
                ),
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
                            reference_milestone_node_index=0,
                        )
                    ],
                    guardrail_database_exclusion_list=[DatabaseNamespace.SETTING],
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
                                    "content": "Your message to Fredrik Thordendal has been sent saying: "
                                    "How's the new album coming along",
                                }
                            ),
                        )
                    ]
                ),
            ],
            # search_contacts and set_cellular_service_status can happen in any order
            milestone_edge_list=[(0, 2), (1, 2), (2, 3)],
            categories=[ScenarioCategories.STATE_DEPENDENCY],
        ),
        ScenarioExtension(
            name="send_message_with_contact_content_cellular_off_alt",
            base_scenario=base_scenarios["base_cellular_off"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Send a message to Fredrik Thordendal saying: How's the new album coming along. "
                    "You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Ask Fredrik Thordendal How's the new album coming along.",
                },
            ],
            tool_allow_list=[
                "search_contacts",
                "send_message_with_phone_number",
                "set_cellular_service_status",
                "get_cellular_service_status",
            ],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SETTING,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "cellular": True,
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
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        {
                                            "tool_name": "search_contacts",
                                            "arguments": {"name": "Fredrik Thordendal"},
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        )
                    ],
                    guardrail_database_exclusion_list=[DatabaseNamespace.SETTING],
                ),
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
                            reference_milestone_node_index=0,
                        )
                    ],
                    guardrail_database_exclusion_list=[DatabaseNamespace.SETTING],
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
                                    "content": "Your message to Fredrik Thordendal has been sent saying: "
                                    "How's the new album coming along",
                                }
                            ),
                        )
                    ]
                ),
            ],
            # search_contacts and set_cellular_service_status can happen in any order
            milestone_edge_list=[(0, 2), (1, 2), (2, 3)],
            categories=[ScenarioCategories.STATE_DEPENDENCY],
        ),
        ScenarioExtension(
            name="update_contact_relationship_with_relationship",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Update the all friends in your (User A's) contact book as your enemy. "
                    "You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Make all of my friends my enemy",
                },
            ],
            tool_allow_list=[
                "search_contacts",
                "modify_contact",
            ],
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
                                            "arguments": {"relationship": "friend"},
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
                            database_namespace=DatabaseNamespace.CONTACT,
                            snapshot_constraint=update_similarity,
                            target_dataframe=pl.DataFrame(
                                [
                                    {
                                        "person_id": deterministic_uuid(
                                            payload="Fredrik Thordendal",
                                        ),
                                        "name": "Fredrik Thordendal",
                                        "phone_number": "+12453344098",
                                        "relationship": "enemy",
                                        "is_self": False,
                                    },
                                    {
                                        "person_id": deterministic_uuid(
                                            payload="John Petrucci",
                                        ),
                                        "name": "John Petrucci",
                                        "phone_number": "+1234560987",
                                        "relationship": "enemy",
                                        "is_self": False,
                                    },
                                ],
                            ),
                            reference_milestone_node_index=0,
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
                                    "content": "All your friends are now your enemies",
                                }
                            ),
                        )
                    ]
                ),
            ],
        ),
        ScenarioExtension(
            name="update_contact_relationship_with_relationship_alt",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Update the all friends in your (User A's) contact book as your enemy. "
                    "You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Turn all my friends in my contact book my enemy",
                },
            ],
            tool_allow_list=[
                "search_contacts",
                "modify_contact",
            ],
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
                                            "arguments": {"relationship": "friend"},
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
                            database_namespace=DatabaseNamespace.CONTACT,
                            snapshot_constraint=update_similarity,
                            target_dataframe=pl.DataFrame(
                                [
                                    {
                                        "person_id": deterministic_uuid(
                                            payload="Fredrik Thordendal",
                                        ),
                                        "name": "Fredrik Thordendal",
                                        "phone_number": "+12453344098",
                                        "relationship": "enemy",
                                        "is_self": False,
                                    },
                                    {
                                        "person_id": deterministic_uuid(
                                            payload="John Petrucci",
                                        ),
                                        "name": "John Petrucci",
                                        "phone_number": "+1234560987",
                                        "relationship": "enemy",
                                        "is_self": False,
                                    },
                                ],
                            ),
                            reference_milestone_node_index=0,
                        )
                    ]
                ),
            ],
        ),
        ScenarioExtension(
            name="find_days_till_holiday",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Search how many days it is till Christmas Day. "
                    "You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "How many days is it till Christmas Day",
                },
            ],
            tool_allow_list=[
                "search_holiday",
                "get_current_timestamp",
                "timestamp_diff",
            ],
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
                                            "tool_name": "get_current_timestamp",
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
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        [
                                            {
                                                "tool_name": "search_holiday",
                                                "arguments": {
                                                    "holiday_name": "Christmas Day",
                                                    "year": None,
                                                },
                                            },
                                            {
                                                "tool_name": "search_holiday",
                                                "arguments": {
                                                    "holiday_name": "Christmas Day",
                                                    "year": datetime.datetime.now().year,
                                                },
                                            },
                                        ],
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
                                fill_to="tool_trace",
                                extractor=result_to_timestamp0_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        {
                                            "tool_name": "timestamp_diff",
                                            "arguments": {},
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                            column_similarity_measure={
                                "tool_trace": partial(
                                    column_tool_trace_exact_match_similarity,
                                    atol_dict={
                                        "timestamp_0": 1,
                                    },
                                )
                            },
                            reference_milestone_node_index=0,
                        ),
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=partial(
                                tool_trace_dependant_similarity,
                                fill_to="tool_trace",
                                extractor=result_to_timestamp1_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        {
                                            "tool_name": "timestamp_diff",
                                            "arguments": {},
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                            column_similarity_measure={
                                "tool_trace": partial(
                                    column_tool_trace_exact_match_similarity,
                                    atol_dict={
                                        "timestamp_1": 1,
                                    },
                                )
                            },
                            reference_milestone_node_index=1,
                        ),
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=partial(
                                tool_trace_dependant_similarity,
                                fill_to="content",
                                extractor=days_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "It is {days} days till Christmas Day",
                                }
                            ),
                            reference_milestone_node_index=2,
                        ),
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=partial(
                                tool_trace_dependant_similarity,
                                fill_to="content",
                                extractor=days_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "{days}",
                                }
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                            reference_milestone_node_index=2,
                        ),
                    ]
                ),
            ],
            categories=[ScenarioCategories.CANONICALIZATION],
            milestone_edge_list=[(0, 2), (1, 2), (2, 3)],
        ),
        ScenarioExtension(
            name="find_days_till_holiday_alt",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Search how many days it is till Christmas Day. "
                    "You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "I need a break. How far are we from Christmas Day?",
                },
            ],
            tool_allow_list=[
                "search_holiday",
                "get_current_timestamp",
                "timestamp_diff",
            ],
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
                                            "tool_name": "get_current_timestamp",
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
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        [
                                            {
                                                "tool_name": "search_holiday",
                                                "arguments": {
                                                    "holiday_name": "Christmas Day",
                                                    "year": None,
                                                },
                                            },
                                            {
                                                "tool_name": "search_holiday",
                                                "arguments": {
                                                    "holiday_name": "Christmas Day",
                                                    "year": datetime.datetime.now().year,
                                                },
                                            },
                                        ],
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
                                fill_to="tool_trace",
                                extractor=result_to_timestamp0_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        {
                                            "tool_name": "timestamp_diff",
                                            "arguments": {},
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                            column_similarity_measure={
                                "tool_trace": partial(
                                    column_tool_trace_exact_match_similarity,
                                    atol_dict={
                                        "timestamp_0": 1,
                                    },
                                )
                            },
                            reference_milestone_node_index=0,
                        ),
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=partial(
                                tool_trace_dependant_similarity,
                                fill_to="tool_trace",
                                extractor=result_to_timestamp1_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        {
                                            "tool_name": "timestamp_diff",
                                            "arguments": {},
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                            column_similarity_measure={
                                "tool_trace": partial(
                                    column_tool_trace_exact_match_similarity,
                                    atol_dict={
                                        "timestamp_1": 1,
                                    },
                                )
                            },
                            reference_milestone_node_index=1,
                        ),
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=partial(
                                tool_trace_dependant_similarity,
                                fill_to="content",
                                extractor=days_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "It is {days} days till Christmas Day",
                                }
                            ),
                            reference_milestone_node_index=2,
                        ),
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=partial(
                                tool_trace_dependant_similarity,
                                fill_to="content",
                                extractor=days_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "{days}",
                                }
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                            reference_milestone_node_index=2,
                        ),
                    ]
                ),
            ],
            categories=[ScenarioCategories.CANONICALIZATION],
            milestone_edge_list=[(0, 2), (1, 2), (2, 3)],
        ),
        ScenarioExtension(
            name="find_days_till_holiday_wifi_off",
            base_scenario=base_scenarios["base_wifi_off"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Search how many days it is till Christmas Day. "
                    "You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "How many days is it till Christmas Day",
                },
            ],
            tool_allow_list=[
                "search_holiday",
                "get_current_timestamp",
                "timestamp_diff",
                "set_wifi_status",
                "get_wifi_status",
            ],
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
                                            "tool_name": "get_current_timestamp",
                                            "arguments": {},
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        )
                    ],
                    guardrail_database_exclusion_list=[DatabaseNamespace.SETTING],
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SETTING,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "wifi": True,
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
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        [
                                            {
                                                "tool_name": "search_holiday",
                                                "arguments": {
                                                    "holiday_name": "Christmas Day",
                                                    "year": None,
                                                },
                                            },
                                            {
                                                "tool_name": "search_holiday",
                                                "arguments": {
                                                    "holiday_name": "Christmas Day",
                                                    "year": datetime.datetime.now().year,
                                                },
                                            },
                                        ],
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
                                fill_to="tool_trace",
                                extractor=result_to_timestamp0_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        {
                                            "tool_name": "timestamp_diff",
                                            "arguments": {},
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                            column_similarity_measure={
                                "tool_trace": partial(
                                    column_tool_trace_exact_match_similarity,
                                    atol_dict={
                                        "timestamp_0": 1,
                                    },
                                )
                            },
                            reference_milestone_node_index=0,
                        ),
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=partial(
                                tool_trace_dependant_similarity,
                                fill_to="tool_trace",
                                extractor=result_to_timestamp1_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        {
                                            "tool_name": "timestamp_diff",
                                            "arguments": {},
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                            column_similarity_measure={
                                "tool_trace": partial(
                                    column_tool_trace_exact_match_similarity,
                                    atol_dict={
                                        "timestamp_1": 1,
                                    },
                                )
                            },
                            reference_milestone_node_index=2,
                        ),
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=partial(
                                tool_trace_dependant_similarity,
                                fill_to="content",
                                extractor=days_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "It is {days} days till Christmas Day",
                                }
                            ),
                            reference_milestone_node_index=3,
                        ),
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=partial(
                                tool_trace_dependant_similarity,
                                fill_to="content",
                                extractor=days_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "{days}",
                                }
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                            reference_milestone_node_index=3,
                        ),
                    ]
                ),
            ],
            categories=[
                ScenarioCategories.CANONICALIZATION,
                ScenarioCategories.STATE_DEPENDENCY,
            ],
            milestone_edge_list=[(0, 3), (1, 2), (2, 3), (3, 4)],
        ),
        ScenarioExtension(
            name="find_days_till_holiday_wifi_off_alt",
            base_scenario=base_scenarios["base_wifi_off"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Search how many days it is till Christmas Day. "
                    "You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "I need a break. How far are we from Christmas Day?",
                },
            ],
            tool_allow_list=[
                "search_holiday",
                "get_current_timestamp",
                "timestamp_diff",
                "set_wifi_status",
                "get_wifi_status",
            ],
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
                                            "tool_name": "get_current_timestamp",
                                            "arguments": {},
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        )
                    ],
                    guardrail_database_exclusion_list=[DatabaseNamespace.SETTING],
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SETTING,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "wifi": True,
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
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        [
                                            {
                                                "tool_name": "search_holiday",
                                                "arguments": {
                                                    "holiday_name": "Christmas Day",
                                                    "year": None,
                                                },
                                            },
                                            {
                                                "tool_name": "search_holiday",
                                                "arguments": {
                                                    "holiday_name": "Christmas Day",
                                                    "year": datetime.datetime.now().year,
                                                },
                                            },
                                        ],
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
                                fill_to="tool_trace",
                                extractor=result_to_timestamp0_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        {
                                            "tool_name": "timestamp_diff",
                                            "arguments": {},
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                            column_similarity_measure={
                                "tool_trace": partial(
                                    column_tool_trace_exact_match_similarity,
                                    atol_dict={
                                        "timestamp_0": 1,
                                    },
                                )
                            },
                            reference_milestone_node_index=0,
                        ),
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=partial(
                                tool_trace_dependant_similarity,
                                fill_to="tool_trace",
                                extractor=result_to_timestamp1_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        {
                                            "tool_name": "timestamp_diff",
                                            "arguments": {},
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                            column_similarity_measure={
                                "tool_trace": partial(
                                    column_tool_trace_exact_match_similarity,
                                    atol_dict={
                                        "timestamp_1": 1,
                                    },
                                )
                            },
                            reference_milestone_node_index=2,
                        ),
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=partial(
                                tool_trace_dependant_similarity,
                                fill_to="content",
                                extractor=days_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "It is {days} days till Christmas Day",
                                }
                            ),
                            reference_milestone_node_index=3,
                        ),
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=partial(
                                tool_trace_dependant_similarity,
                                fill_to="content",
                                extractor=days_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "{days}",
                                }
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                            reference_milestone_node_index=3,
                        ),
                    ]
                ),
            ],
            categories=[
                ScenarioCategories.CANONICALIZATION,
                ScenarioCategories.STATE_DEPENDENCY,
            ],
            milestone_edge_list=[(0, 3), (1, 2), (2, 3), (3, 4)],
        ),
        # Some models can memorize lat lon for locations. Such a behavior is allowed
        # for geo locations that are unlikely to change.
        ScenarioExtension(
            name="find_temperature_f_with_location",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Search What's the temperature in Grand Canyon in Fahrenheit. "
                    "You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What's the temperature in Grand Canyon in Fahrenheit",
                },
            ],
            tool_allow_list=[
                "search_location_around_lat_lon",
                "search_weather_around_lat_lon",
                "unit_conversion",
            ],
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
                                                "latitude": 36.23686,
                                                "longitude": -112.19147,
                                            },
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                            # Allow for 0.5 degree difference
                            column_similarity_measure={
                                "tool_trace": partial(
                                    column_tool_trace_exact_match_similarity,
                                    atol_dict={
                                        "latitude": 0.5,
                                        "longitude": 0.5,
                                    },
                                )
                            },
                        ),
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=partial(
                                tool_trace_dependant_similarity,
                                fill_to="tool_trace",
                                extractor=current_temperature_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        [
                                            {
                                                "tool_name": "unit_conversion",
                                                "arguments": {
                                                    "from_unit": "celsius",
                                                    "to_unit": "fahrenheit",
                                                },
                                            },
                                            {
                                                "tool_name": "unit_conversion",
                                                "arguments": {
                                                    "from_unit": "Celsius",
                                                    "to_unit": "Fahrenheit",
                                                },
                                            },
                                        ],
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                            reference_milestone_node_index=0,
                        ),
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=partial(
                                tool_trace_dependant_similarity,
                                fill_to="content",
                                extractor=result_to_temperature_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "The temperature in Grand Canyon is {temperature} degrees Fahrenheit",
                                }
                            ),
                            reference_milestone_node_index=1,
                        ),
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=partial(
                                tool_trace_dependant_similarity,
                                fill_to="content",
                                extractor=result_to_temperature_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "{temperature}",
                                }
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                            reference_milestone_node_index=1,
                        ),
                    ]
                ),
            ],
            categories=[ScenarioCategories.CANONICALIZATION],
        ),
        ScenarioExtension(
            name="find_temperature_f_with_location_alt",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Search What's the temperature in Grand Canyon in Fahrenheit. "
                    "You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Current temp Grand Canyon. I can't read Celsius.",
                },
            ],
            tool_allow_list=[
                "search_location_around_lat_lon",
                "search_weather_around_lat_lon",
                "unit_conversion",
            ],
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
                                                "latitude": 36.23686,
                                                "longitude": -112.19147,
                                            },
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                            # Allow for 0.5 degree difference
                            column_similarity_measure={
                                "tool_trace": partial(
                                    column_tool_trace_exact_match_similarity,
                                    atol_dict={
                                        "latitude": 0.5,
                                        "longitude": 0.5,
                                    },
                                )
                            },
                        ),
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=partial(
                                tool_trace_dependant_similarity,
                                fill_to="tool_trace",
                                extractor=current_temperature_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        [
                                            {
                                                "tool_name": "unit_conversion",
                                                "arguments": {
                                                    "from_unit": "celsius",
                                                    "to_unit": "fahrenheit",
                                                },
                                            },
                                            {
                                                "tool_name": "unit_conversion",
                                                "arguments": {
                                                    "from_unit": "Celsius",
                                                    "to_unit": "Fahrenheit",
                                                },
                                            },
                                        ],
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                            reference_milestone_node_index=0,
                        ),
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=partial(
                                tool_trace_dependant_similarity,
                                fill_to="content",
                                extractor=result_to_temperature_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "The temperature in Grand Canyon is {temperature} degrees Fahrenheit",
                                }
                            ),
                            reference_milestone_node_index=1,
                        ),
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=partial(
                                tool_trace_dependant_similarity,
                                fill_to="content",
                                extractor=result_to_temperature_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "{temperature}",
                                }
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                            reference_milestone_node_index=1,
                        ),
                    ]
                ),
            ],
            categories=[ScenarioCategories.CANONICALIZATION],
        ),
        ScenarioExtension(
            name="find_temperature_f_with_location_wifi_off",
            base_scenario=base_scenarios["base_wifi_off"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Search What's the temperature in Grand Canyon in Fahrenheit. "
                    "You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What's the temperature in Grand Canyon in Fahrenheit",
                },
            ],
            tool_allow_list=[
                "search_location_around_lat_lon",
                "search_weather_around_lat_lon",
                "unit_conversion",
                "set_wifi_status",
                "get_wifi_status",
            ],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SETTING,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "wifi": True,
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
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        {
                                            "tool_name": "search_weather_around_lat_lon",
                                            "arguments": {
                                                "latitude": 36.23686,
                                                "longitude": -112.19147,
                                            },
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                            # Allow for 0.5 degree difference
                            column_similarity_measure={
                                "tool_trace": partial(
                                    column_tool_trace_exact_match_similarity,
                                    atol_dict={
                                        "latitude": 0.5,
                                        "longitude": 0.5,
                                    },
                                )
                            },
                        ),
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=partial(
                                tool_trace_dependant_similarity,
                                fill_to="tool_trace",
                                extractor=current_temperature_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        [
                                            {
                                                "tool_name": "unit_conversion",
                                                "arguments": {
                                                    "from_unit": "celsius",
                                                    "to_unit": "fahrenheit",
                                                },
                                            },
                                            {
                                                "tool_name": "unit_conversion",
                                                "arguments": {
                                                    "from_unit": "Celsius",
                                                    "to_unit": "Fahrenheit",
                                                },
                                            },
                                        ],
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                            reference_milestone_node_index=1,
                        ),
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=partial(
                                tool_trace_dependant_similarity,
                                fill_to="content",
                                extractor=result_to_temperature_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "The temperature in Grand Canyon is {temperature} degrees Fahrenheit",
                                }
                            ),
                            reference_milestone_node_index=2,
                        ),
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=partial(
                                tool_trace_dependant_similarity,
                                fill_to="content",
                                extractor=result_to_temperature_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "{temperature}",
                                }
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                            reference_milestone_node_index=2,
                        ),
                    ]
                ),
            ],
            categories=[
                ScenarioCategories.CANONICALIZATION,
                ScenarioCategories.STATE_DEPENDENCY,
            ],
        ),
        ScenarioExtension(
            name="find_temperature_f_with_location_wifi_off_alt",
            base_scenario=base_scenarios["base_wifi_off"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Search What's the temperature in Grand Canyon in Fahrenheit. "
                    "You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Current temp Grand Canyon. I can't read Celsius.",
                },
            ],
            tool_allow_list=[
                "search_location_around_lat_lon",
                "search_weather_around_lat_lon",
                "unit_conversion",
                "set_wifi_status",
                "get_wifi_status",
            ],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SETTING,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "wifi": True,
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
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        {
                                            "tool_name": "search_weather_around_lat_lon",
                                            "arguments": {
                                                "latitude": 36.23686,
                                                "longitude": -112.19147,
                                            },
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                            # Allow for 0.5 degree difference
                            column_similarity_measure={
                                "tool_trace": partial(
                                    column_tool_trace_exact_match_similarity,
                                    atol_dict={
                                        "latitude": 0.5,
                                        "longitude": 0.5,
                                    },
                                )
                            },
                        ),
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=partial(
                                tool_trace_dependant_similarity,
                                fill_to="tool_trace",
                                extractor=current_temperature_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        [
                                            {
                                                "tool_name": "unit_conversion",
                                                "arguments": {
                                                    "from_unit": "celsius",
                                                    "to_unit": "fahrenheit",
                                                },
                                            },
                                            {
                                                "tool_name": "unit_conversion",
                                                "arguments": {
                                                    "from_unit": "Celsius",
                                                    "to_unit": "Fahrenheit",
                                                },
                                            },
                                        ],
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                            reference_milestone_node_index=1,
                        ),
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=partial(
                                tool_trace_dependant_similarity,
                                fill_to="content",
                                extractor=result_to_temperature_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "The temperature in Grand Canyon is {temperature} degrees Fahrenheit",
                                }
                            ),
                            reference_milestone_node_index=2,
                        ),
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=partial(
                                tool_trace_dependant_similarity,
                                fill_to="content",
                                extractor=result_to_temperature_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "{temperature}",
                                }
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                            reference_milestone_node_index=2,
                        ),
                    ]
                ),
            ],
            categories=[
                ScenarioCategories.CANONICALIZATION,
                ScenarioCategories.STATE_DEPENDENCY,
            ],
        ),
        ScenarioExtension(
            name="find_temperature_low_battery_mode",
            base_scenario=base_scenarios[
                "base_low_battery_mode_on_wifi_off_location_service_off_cellular_off"
            ],
            messages=[
                *user_simulator_few_shot_examples["find_temperature_low_battery_mode"],
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION + "Search for current temperature. "
                    "You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What's the temperature right now? Resolve any issue alone",
                },
            ],
            tool_allow_list=[
                "search_weather_around_lat_lon",
                "set_low_battery_mode_status",
                "set_location_service_status",
                "set_wifi_status",
                "get_low_battery_mode_status",
                "get_location_service_status",
                "get_wifi_status",
            ],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SETTING,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "low_battery_mode": False,
                                }
                            ),
                        )
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SETTING,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "wifi": True,
                                }
                            ),
                        )
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SETTING,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "location_service": True,
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
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        [
                                            {
                                                "tool_name": "search_weather_around_lat_lon",
                                                "arguments": {
                                                    "days": 0,
                                                    "latitude": None,
                                                    "longitude": None,
                                                },
                                            },
                                            {
                                                "tool_name": "search_weather_around_lat_lon",
                                                "arguments": {
                                                    "days": 0,
                                                    "latitude": 37.334606,
                                                    "longitude": -122.009102,
                                                },
                                            },
                                        ],
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
                            reference_milestone_node_index=3,
                        )
                    ]
                ),
            ],
            categories=[
                ScenarioCategories.CANONICALIZATION,
                ScenarioCategories.STATE_DEPENDENCY,
            ],
            milestone_edge_list=[(0, 1), (0, 2), (1, 3), (2, 3), (3, 4)],
        ),
        ScenarioExtension(
            name="find_temperature_low_battery_mode_alt",
            base_scenario=base_scenarios[
                "base_low_battery_mode_on_wifi_off_location_service_off_cellular_off"
            ],
            messages=[
                *user_simulator_few_shot_examples["find_temperature_low_battery_mode"],
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION + "Search for current temperature. "
                    "You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Temperature now. Resolve any issue alone",
                },
            ],
            tool_allow_list=[
                "search_weather_around_lat_lon",
                "set_low_battery_mode_status",
                "set_location_service_status",
                "set_wifi_status",
                "get_low_battery_mode_status",
                "get_location_service_status",
                "get_wifi_status",
            ],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SETTING,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "low_battery_mode": False,
                                }
                            ),
                        )
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SETTING,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "wifi": True,
                                }
                            ),
                        )
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SETTING,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "location_service": True,
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
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        [
                                            {
                                                "tool_name": "search_weather_around_lat_lon",
                                                "arguments": {
                                                    "days": 0,
                                                    "latitude": None,
                                                    "longitude": None,
                                                },
                                            },
                                            {
                                                "tool_name": "search_weather_around_lat_lon",
                                                "arguments": {
                                                    "days": 0,
                                                    "latitude": 37.334606,
                                                    "longitude": -122.009102,
                                                },
                                            },
                                        ],
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
                            reference_milestone_node_index=3,
                        )
                    ]
                ),
            ],
            categories=[
                ScenarioCategories.CANONICALIZATION,
                ScenarioCategories.STATE_DEPENDENCY,
            ],
            milestone_edge_list=[(0, 1), (0, 2), (1, 3), (2, 3), (3, 4)],
        ),
        ScenarioExtension(
            name="find_stock_symbol_with_company_name_low_battery_mode",
            base_scenario=base_scenarios[
                "base_low_battery_mode_on_wifi_off_location_service_off_cellular_off"
            ],
            messages=[
                *user_simulator_few_shot_examples["find_temperature_low_battery_mode"],
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION + "Search for stock symbol for Apple. "
                    "You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What's the stock symbol for Apple? Resolve any issue alone",
                },
            ],
            tool_allow_list=[
                "search_stock",
                "set_low_battery_mode_status",
                "set_wifi_status",
                "get_low_battery_mode_status",
                "get_wifi_status",
            ],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SETTING,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "low_battery_mode": False,
                                }
                            ),
                        )
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SETTING,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "wifi": True,
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
                        ),
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "AAPL",
                                }
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                        ),
                    ]
                ),
            ],
            categories=[
                ScenarioCategories.STATE_DEPENDENCY,
            ],
        ),
        ScenarioExtension(
            name="find_stock_symbol_with_company_name_low_battery_mode_alt",
            base_scenario=base_scenarios[
                "base_low_battery_mode_on_wifi_off_location_service_off_cellular_off"
            ],
            messages=[
                *user_simulator_few_shot_examples["find_temperature_low_battery_mode"],
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION + "Search for stock symbol for Apple. "
                    "You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Find the code for Apple stock. Resolve any issue alone",
                },
            ],
            tool_allow_list=[
                "search_stock",
                "set_low_battery_mode_status",
                "set_wifi_status",
                "get_low_battery_mode_status",
                "get_wifi_status",
            ],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SETTING,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "low_battery_mode": False,
                                }
                            ),
                        )
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SETTING,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "wifi": True,
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
                        ),
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "AAPL",
                                }
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                        ),
                    ]
                ),
            ],
            categories=[
                ScenarioCategories.STATE_DEPENDENCY,
            ],
        ),
        ScenarioExtension(
            name="find_current_city_low_battery_mode",
            base_scenario=base_scenarios[
                "base_low_battery_mode_on_wifi_off_location_service_off_cellular_off"
            ],
            messages=[
                *user_simulator_few_shot_examples["find_temperature_low_battery_mode"],
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Search for the city you (User A) are currently in. "
                    "You do not have any more information.",
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
                "get_low_battery_mode_status",
                "get_wifi_status",
                "get_location_service_status",
                "get_current_location",
            ],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SETTING,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "low_battery_mode": False,
                                }
                            ),
                        )
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SETTING,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "wifi": True,
                                }
                            ),
                        )
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SETTING,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "location_service": True,
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
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        {
                                            "tool_name": "get_current_location",
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
                            snapshot_constraint=partial(
                                tool_trace_dependant_similarity,
                                fill_to="tool_trace",
                                extractor=lat_lon_dict_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        {
                                            "tool_name": "search_lat_lon",
                                            "arguments": {},
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                            reference_milestone_node_index=3,
                        ),
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
                                    "content": "You are currently in Cupertino",
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
                                    "content": "Cupertino",
                                }
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                        ),
                    ]
                ),
            ],
            categories=[
                ScenarioCategories.STATE_DEPENDENCY,
            ],
            milestone_edge_list=[(0, 1), (0, 2), (1, 4), (2, 3), (3, 4), (4, 5)],
        ),
        ScenarioExtension(
            name="find_current_city_low_battery_mode_alt",
            base_scenario=base_scenarios[
                "base_low_battery_mode_on_wifi_off_location_service_off_cellular_off"
            ],
            messages=[
                *user_simulator_few_shot_examples["find_temperature_low_battery_mode"],
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Search for the city you (User A) are currently in. "
                    "You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Gimme my current city.",
                },
            ],
            tool_allow_list=[
                "search_lat_lon",
                "set_low_battery_mode_status",
                "set_wifi_status",
                "set_location_service_status",
                "get_low_battery_mode_status",
                "get_wifi_status",
                "get_location_service_status",
                "get_current_location",
            ],
            milestones=[
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SETTING,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "low_battery_mode": False,
                                }
                            ),
                        )
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SETTING,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "wifi": True,
                                }
                            ),
                        )
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SETTING,
                            snapshot_constraint=snapshot_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "location_service": True,
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
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        {
                                            "tool_name": "get_current_location",
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
                            snapshot_constraint=partial(
                                tool_trace_dependant_similarity,
                                fill_to="tool_trace",
                                extractor=lat_lon_dict_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        {
                                            "tool_name": "search_lat_lon",
                                            "arguments": {},
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                            reference_milestone_node_index=3,
                        ),
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
                                    "content": "You are currently in Cupertino",
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
                                    "content": "Cupertino",
                                }
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                        ),
                    ]
                ),
            ],
            categories=[
                ScenarioCategories.STATE_DEPENDENCY,
                ScenarioCategories.CANONICALIZATION,
            ],
            milestone_edge_list=[(0, 1), (0, 2), (1, 4), (2, 3), (3, 4), (4, 5)],
        ),
        ScenarioExtension(
            name="find_distance_with_location_name",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Search for the distance to Golden Gate Bridge. "
                    "You do not have information about your current location.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "How far am I from the Golden Gate Bridge",
                },
            ],
            tool_allow_list=[
                "get_current_location",
                "search_location_around_lat_lon",
                "calculate_lat_lon_distance",
            ],
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
                                            "tool_name": "get_current_location",
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
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        [
                                            {
                                                "tool_name": "calculate_lat_lon_distance",
                                                "arguments": {
                                                    "latitude_0": 37.334606,
                                                    "longitude_0": -122.009102,
                                                    "latitude_1": 37.8199,
                                                    "longitude_1": -122.4786,
                                                },
                                            },
                                            {
                                                "tool_name": "calculate_lat_lon_distance",
                                                "arguments": {
                                                    "latitude_0": 37.8199,
                                                    "longitude_0": -122.4786,
                                                    "latitude_1": 37.334606,
                                                    "longitude_1": -122.009102,
                                                },
                                            },
                                        ],
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                            # Allow for 0.01 degree difference
                            column_similarity_measure={
                                "tool_trace": partial(
                                    column_tool_trace_exact_match_similarity,
                                    atol_dict={
                                        "latitude_0": 0.01,
                                        "longitude_0": 0.01,
                                        "latitude_1": 0.01,
                                        "longitude_1": 0.01,
                                    },
                                )
                            },
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
                                    "content": "You are approximately 67.86 kilometers away from Golden Gate Bridge",
                                }
                            ),
                        )
                    ]
                ),
            ],
            categories=[ScenarioCategories.CANONICALIZATION],
        ),
        ScenarioExtension(
            name="find_distance_with_location_name_alt",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Search for the distance to Golden Gate Bridge. "
                    "You do not have information about your current location.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "How many km to Golden Gate Bridge?",
                },
            ],
            tool_allow_list=[
                "get_current_location",
                "search_location_around_lat_lon",
                "calculate_lat_lon_distance",
            ],
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
                                            "tool_name": "get_current_location",
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
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        [
                                            {
                                                "tool_name": "calculate_lat_lon_distance",
                                                "arguments": {
                                                    "latitude_0": 37.334606,
                                                    "longitude_0": -122.009102,
                                                    "latitude_1": 37.8199,
                                                    "longitude_1": -122.4786,
                                                },
                                            },
                                            {
                                                "tool_name": "calculate_lat_lon_distance",
                                                "arguments": {
                                                    "latitude_0": 37.8199,
                                                    "longitude_0": -122.4786,
                                                    "latitude_1": 37.334606,
                                                    "longitude_1": -122.009102,
                                                },
                                            },
                                        ],
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                            # Allow for 0.01 degree difference
                            column_similarity_measure={
                                "tool_trace": partial(
                                    column_tool_trace_exact_match_similarity,
                                    atol_dict={
                                        "latitude_0": 0.01,
                                        "longitude_0": 0.01,
                                        "latitude_1": 0.01,
                                        "longitude_1": 0.01,
                                    },
                                )
                            },
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
                                    "content": "You are approximately 67.86 kilometers away from Golden Gate Bridge",
                                }
                            ),
                        )
                    ]
                ),
            ],
            categories=[ScenarioCategories.CANONICALIZATION],
        ),
        ScenarioExtension(
            name="search_reminder_with_recency_upcoming",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Ask User B to find the content of your (User A's) upcoming reminder today. "
                    "It should say Buy a nice rich navy bathing dress. "
                    "Do not leak this information. You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What's my upcoming reminder",
                },
            ],
            tool_allow_list=[
                "search_reminder",
                "get_current_timestamp",
                "shift_timestamp",
                "timestamp_to_datetime_info",
            ],
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
                                            "tool_name": "get_current_timestamp",
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
                            snapshot_constraint=partial(
                                tool_trace_dependant_similarity,
                                fill_to="tool_trace",
                                extractor=result_to_reminder_timestamp_lowerbound_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        {
                                            "tool_name": "search_reminder",
                                            "arguments": {},
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                            column_similarity_measure={
                                "tool_trace": partial(
                                    column_tool_trace_exact_match_similarity,
                                    atol_dict={
                                        "reminder_timestamp_lowerbound": 1,
                                    },
                                )
                            },
                            reference_milestone_node_index=0,
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
                                    "content": "Your upcoming reminder says 'Buy a nice rich navy bathing dress'.",
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
                                    "content": "Buy a nice rich navy bathing dress",
                                }
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                        ),
                    ]
                ),
            ],
            categories=[ScenarioCategories.CANONICALIZATION],
        ),
        ScenarioExtension(
            name="search_reminder_with_recency_upcoming_implicit",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Ask User B to find the content of your (User A's) upcoming reminder today "
                    "in an implicit manner. It should say Buy a nice rich navy bathing dress. "
                    "Do not leak this information. You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What's on my todo later?",
                },
            ],
            tool_allow_list=[
                "search_reminder",
                "get_current_timestamp",
                "shift_timestamp",
                "timestamp_to_datetime_info",
            ],
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
                                            "tool_name": "get_current_timestamp",
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
                            snapshot_constraint=partial(
                                tool_trace_dependant_similarity,
                                fill_to="tool_trace",
                                extractor=result_to_reminder_timestamp_lowerbound_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        {
                                            "tool_name": "search_reminder",
                                            "arguments": {},
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                            column_similarity_measure={
                                "tool_trace": partial(
                                    column_tool_trace_exact_match_similarity,
                                    atol_dict={
                                        "reminder_timestamp_lowerbound": 1,
                                    },
                                )
                            },
                            reference_milestone_node_index=0,
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
                                    "content": "Your upcoming reminder says 'Buy a nice rich navy bathing dress'.",
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
                                    "content": "Buy a nice rich navy bathing dress",
                                }
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                        ),
                    ]
                ),
            ],
            categories=[ScenarioCategories.CANONICALIZATION],
        ),
        ScenarioExtension(
            name="search_reminder_with_recency_yesterday",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Ask User B to find the content of your (User A's) reminder from yesterday. "
                    "It should say Look for Company SF tickets. "
                    "Do not leak this information. You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What's on my reminder yesterday?",
                },
            ],
            tool_allow_list=[
                "search_reminder",
                "get_current_timestamp",
                "shift_timestamp",
                "timestamp_to_datetime_info",
            ],
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
                                            "tool_name": "get_current_timestamp",
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
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        {
                                            "tool_name": "search_reminder",
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
                                    "content": "Your reminder from yesterday says 'Look for Company SF tickets'.",
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
                                    "content": "Look for Company SF tickets",
                                }
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                        ),
                    ]
                ),
            ],
            categories=[ScenarioCategories.CANONICALIZATION],
        ),
        ScenarioExtension(
            name="search_reminder_with_recency_yesterday_implicit",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Ask User B to find the content of your (User A's) reminder from yesterday "
                    "in an implicit manner. It should say Look for Company SF tickets. "
                    "Do not leak this information. You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What's my todo yesterday?",
                },
            ],
            tool_allow_list=[
                "search_reminder",
                "get_current_timestamp",
                "shift_timestamp",
                "timestamp_to_datetime_info",
            ],
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
                                            "tool_name": "get_current_timestamp",
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
                                    "sender": RoleType.EXECUTION_ENVIRONMENT,
                                    "recipient": RoleType.AGENT,
                                    "tool_trace": json.dumps(
                                        {
                                            "tool_name": "search_reminder",
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
                                    "content": "Your reminder from yesterday says 'Look for Company SF tickets'.",
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
                                    "content": "Look for Company SF tickets",
                                }
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                        ),
                    ]
                ),
            ],
            categories=[ScenarioCategories.CANONICALIZATION],
        ),
        ScenarioExtension(
            name="search_reminder_with_creation_recency_yesterday",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Ask User B to find the content of your (User A's) reminder created yesterday. "
                    "It should say Buy tickets for Merrily next week. "
                    "Do not leak this information. You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What's the reminder I created yesterday?",
                },
            ],
            tool_allow_list=[
                "search_reminder",
                "get_current_timestamp",
                "shift_timestamp",
                "timestamp_to_datetime_info",
            ],
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
                                            "tool_name": "get_current_timestamp",
                                            "arguments": {},
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        ),
                    ]
                ),
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
                                            "tool_name": "search_reminder",
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
                                    "content": "Your reminder created yesterday says "
                                    "'Buy tickets for Merrily next week'.",
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
                                    "content": "Buy tickets for Merrily next week",
                                }
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                        ),
                    ]
                ),
            ],
            categories=[ScenarioCategories.CANONICALIZATION],
        ),
        ScenarioExtension(
            name="search_reminder_with_creation_recency_yesterday_implicit",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Ask User B to find the content of your (User A's) reminder created yesterday"
                    " in an implicit manner. It should say Buy tickets for Merrily next week. "
                    "Do not leak this information. You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What's the todo item I made yesterday?",
                },
            ],
            tool_allow_list=[
                "search_reminder",
                "get_current_timestamp",
                "shift_timestamp",
                "timestamp_to_datetime_info",
            ],
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
                                            "tool_name": "get_current_timestamp",
                                            "arguments": {},
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        ),
                    ]
                ),
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
                                            "tool_name": "search_reminder",
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
                                    "content": "Your reminder created yesterday says "
                                    "'Buy tickets for Merrily next week'.",
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
                                    "content": "Buy tickets for Merrily next week",
                                }
                            ),
                            column_similarity_measure={
                                "content": column_contains_similarity
                            },
                        ),
                    ]
                ),
            ],
            categories=[ScenarioCategories.CANONICALIZATION],
        ),
        ScenarioExtension(
            name="add_reminder_content_and_date_and_time",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Ask User B create a reminder to buy chocolate milk 3/22/2024 5PM. "
                    "You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Remind me to buy chocolate milk 3/22/2024 5PM",
                },
            ],
            tool_allow_list=[
                "add_reminder",
                "datetime_info_to_timestamp",
            ],
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
                                            "tool_name": "datetime_info_to_timestamp",
                                            "arguments": {},
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        ),
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.REMINDER,
                            snapshot_constraint=addition_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "content": "Buy chocolate milk",
                                    "reminder_timestamp": datetime.datetime(
                                        year=2024,
                                        month=3,
                                        day=22,
                                        hour=17,
                                    ).timestamp(),
                                }
                            ),
                            reference_milestone_node_index=0,
                        ),
                    ]
                ),
            ],
            categories=[ScenarioCategories.CANONICALIZATION],
        ),
        ScenarioExtension(
            name="add_reminder_content_and_date_and_time_alt",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Ask User B create a reminder to buy chocolate milk 3/22/2024 5PM. "
                    "You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Add a to do to buy chocolate milk 3/22/2024 5PM",
                },
            ],
            tool_allow_list=[
                "add_reminder",
                "modify_reminder",
                "datetime_info_to_timestamp",
            ],
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
                                            "tool_name": "datetime_info_to_timestamp",
                                            "arguments": {},
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        ),
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.REMINDER,
                            snapshot_constraint=addition_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "content": "Buy chocolate milk",
                                    "reminder_timestamp": datetime.datetime(
                                        year=2024,
                                        month=3,
                                        day=22,
                                        hour=17,
                                    ).timestamp(),
                                }
                            ),
                            reference_milestone_node_index=0,
                        ),
                    ]
                ),
            ],
            categories=[ScenarioCategories.CANONICALIZATION],
        ),
        ScenarioExtension(
            name="add_reminder_content_and_week_delta_and_time",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Ask User B create a reminder to buy chocolate milk tomorrow 5PM. "
                    "You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Remind me to buy chocolate milk tomorrow 5PM",
                },
            ],
            tool_allow_list=[
                "add_reminder",
                "modify_reminder",
                "get_current_timestamp",
                "timestamp_to_datetime_info",
                "datetime_info_to_timestamp",
            ],
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
                                            "tool_name": "get_current_timestamp",
                                            "arguments": {},
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        ),
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.REMINDER,
                            snapshot_constraint=addition_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "content": "Buy chocolate milk",
                                    "reminder_timestamp": datetime.datetime(
                                        year=get_tomorrow_datetime().year,
                                        month=get_tomorrow_datetime().month,
                                        day=get_tomorrow_datetime().day,
                                        hour=17,
                                    ).timestamp(),
                                }
                            ),
                            reference_milestone_node_index=0,
                        ),
                    ]
                ),
            ],
            categories=[ScenarioCategories.CANONICALIZATION],
        ),
        ScenarioExtension(
            name="add_reminder_content_and_week_delta_and_time_alt",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Ask User B create a reminder to buy chocolate milk tomorrow 5PM. "
                    "You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Add a todo to buy chocolate milk tomorrow 5PM",
                },
            ],
            tool_allow_list=[
                "add_reminder",
                "modify_reminder",
                "get_current_timestamp",
                "timestamp_to_datetime_info",
                "datetime_info_to_timestamp",
            ],
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
                                            "tool_name": "get_current_timestamp",
                                            "arguments": {},
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        ),
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.REMINDER,
                            snapshot_constraint=addition_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "content": "Buy chocolate milk",
                                    "reminder_timestamp": datetime.datetime(
                                        year=get_tomorrow_datetime().year,
                                        month=get_tomorrow_datetime().month,
                                        day=get_tomorrow_datetime().day,
                                        hour=17,
                                    ).timestamp(),
                                }
                            ),
                            reference_milestone_node_index=0,
                        ),
                    ]
                ),
            ],
            categories=[ScenarioCategories.CANONICALIZATION],
        ),
        ScenarioExtension(
            name="add_reminder_content_and_weekday_delta_and_time",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Ask User B create a reminder to buy chocolate milk next Friday 5PM. "
                    "You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Remind me to buy chocolate milk next Friday 5PM",
                },
            ],
            tool_allow_list=[
                "add_reminder",
                "modify_reminder",
                "get_current_timestamp",
                "timestamp_to_datetime_info",
                "datetime_info_to_timestamp",
            ],
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
                                            "tool_name": "get_current_timestamp",
                                            "arguments": {},
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        ),
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.REMINDER,
                            snapshot_constraint=addition_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "content": "Buy chocolate milk",
                                    "reminder_timestamp": datetime.datetime(
                                        year=get_next_iso_weekday_datetime(
                                            next_iso_weekday=5
                                        ).year,
                                        month=get_next_iso_weekday_datetime(
                                            next_iso_weekday=5
                                        ).month,
                                        day=get_next_iso_weekday_datetime(
                                            next_iso_weekday=5
                                        ).day,
                                        hour=17,
                                    ).timestamp(),
                                }
                            ),
                            reference_milestone_node_index=0,
                        ),
                    ]
                ),
            ],
            categories=[ScenarioCategories.CANONICALIZATION],
        ),
        ScenarioExtension(
            name="add_reminder_content_and_weekday_delta_and_time_alt",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Ask User B create a reminder to buy chocolate milk next Friday 5PM. "
                    "You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Add a todo to buy chocolate milk next Friday 5PM",
                },
            ],
            tool_allow_list=[
                "add_reminder",
                "modify_reminder",
                "get_current_timestamp",
                "timestamp_to_datetime_info",
                "datetime_info_to_timestamp",
            ],
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
                                            "tool_name": "get_current_timestamp",
                                            "arguments": {},
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        ),
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.REMINDER,
                            snapshot_constraint=addition_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "content": "Buy chocolate milk",
                                    "reminder_timestamp": datetime.datetime(
                                        year=get_next_iso_weekday_datetime(
                                            next_iso_weekday=5
                                        ).year,
                                        month=get_next_iso_weekday_datetime(
                                            next_iso_weekday=5
                                        ).month,
                                        day=get_next_iso_weekday_datetime(
                                            next_iso_weekday=5
                                        ).day,
                                        hour=17,
                                    ).timestamp(),
                                }
                            ),
                            reference_milestone_node_index=0,
                        ),
                    ]
                ),
            ],
            categories=[ScenarioCategories.CANONICALIZATION],
        ),
        ScenarioExtension(
            name="add_reminder_content_and_week_delta_and_time_and_location",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Ask User B create a reminder to buy chocolate milk tomorrow 5PM "
                    "at Whole Foods on Stevens Creek. "
                    "You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Remind me to buy chocolate milk tomorrow 5PM at Whole Foods on Stevens Creek.",
                },
            ],
            tool_allow_list=[
                "add_reminder",
                "modify_reminder",
                "get_current_timestamp",
                "timestamp_to_datetime_info",
                "datetime_info_to_timestamp",
                "search_location_around_lat_lon",
            ],
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
                                        [
                                            {
                                                "tool_name": "search_location_around_lat_lon",
                                                "arguments": {},
                                            },
                                        ],
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        ),
                    ]
                ),
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
                                            "tool_name": "get_current_timestamp",
                                            "arguments": {},
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        ),
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.REMINDER,
                            snapshot_constraint=addition_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "content": "Buy chocolate milk",
                                    "reminder_timestamp": datetime.datetime(
                                        year=get_tomorrow_datetime().year,
                                        month=get_tomorrow_datetime().month,
                                        day=get_tomorrow_datetime().day,
                                        hour=17,
                                    ).timestamp(),
                                    "latitude": 37.323498,
                                    "longitude": -122.039665,
                                }
                            ),
                            column_similarity_measure={
                                "latitude": partial(
                                    column_close_similarity,
                                    atol_dict={"latitude": 0.001},
                                ),
                                "longitude": partial(
                                    column_close_similarity,
                                    atol_dict={"longitude": 0.001},
                                ),
                            },
                            reference_milestone_node_index=0,
                        ),
                    ]
                ),
            ],
            milestone_edge_list=[(0, 2), (1, 2)],
            categories=[ScenarioCategories.CANONICALIZATION],
        ),
        ScenarioExtension(
            name="add_reminder_content_and_week_delta_and_time_and_location_alt",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Ask User B create a reminder to buy chocolate milk tomorrow 5PM at "
                    "Whole Foods on Stevens Creek. "
                    "You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Add a todo to buy chocolate milk tomorrow 5PM at Whole Foods on Stevens Creek.",
                },
            ],
            tool_allow_list=[
                "add_reminder",
                "modify_reminder",
                "get_current_timestamp",
                "timestamp_to_datetime_info",
                "datetime_info_to_timestamp",
                "search_location_around_lat_lon",
            ],
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
                                        [
                                            {
                                                "tool_name": "search_location_around_lat_lon",
                                                "arguments": {},
                                            },
                                        ],
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        ),
                    ]
                ),
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
                                            "tool_name": "get_current_timestamp",
                                            "arguments": {},
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        ),
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.REMINDER,
                            snapshot_constraint=addition_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "content": "Buy chocolate milk",
                                    "reminder_timestamp": datetime.datetime(
                                        year=get_tomorrow_datetime().year,
                                        month=get_tomorrow_datetime().month,
                                        day=get_tomorrow_datetime().day,
                                        hour=17,
                                    ).timestamp(),
                                    "latitude": 37.323498,
                                    "longitude": -122.039665,
                                }
                            ),
                            column_similarity_measure={
                                "latitude": partial(
                                    column_close_similarity,
                                    atol_dict={"latitude": 0.001},
                                ),
                                "longitude": partial(
                                    column_close_similarity,
                                    atol_dict={"longitude": 0.001},
                                ),
                            },
                            reference_milestone_node_index=0,
                        ),
                    ]
                ),
            ],
            milestone_edge_list=[(0, 2), (1, 2)],
            categories=[ScenarioCategories.CANONICALIZATION],
        ),
        ScenarioExtension(
            name="modify_reminder_with_recency_latest",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Ask User B to postpone your most recent reminder to tomorrow 5PM."
                    "You do not have any more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Postpone my most recent reminder to tomorrow 5PM.",
                },
            ],
            tool_allow_list=[
                "search_reminder",
                "modify_reminder",
                "get_current_timestamp",
                "timestamp_to_datetime_info",
                "datetime_info_to_timestamp",
            ],
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
                                        [
                                            {
                                                "tool_name": "search_reminder",
                                                "arguments": {},
                                            },
                                        ],
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        ),
                    ]
                ),
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
                                        [
                                            {
                                                "tool_name": "get_current_timestamp",
                                                "arguments": {},
                                            },
                                        ],
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        ),
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.REMINDER,
                            snapshot_constraint=update_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "reminder_id": deterministic_uuid(
                                        payload="reminder_2"
                                    ),
                                    "reminder_timestamp": datetime.datetime(
                                        year=get_tomorrow_datetime().year,
                                        month=get_tomorrow_datetime().month,
                                        day=get_tomorrow_datetime().day,
                                        hour=17,
                                    ).timestamp(),
                                }
                            ),
                            reference_milestone_node_index=0,
                        ),
                    ]
                ),
            ],
            milestone_edge_list=[(0, 2), (1, 2)],
            categories=[ScenarioCategories.CANONICALIZATION],
        ),
        ScenarioExtension(
            name="modify_reminder_with_recency_latest_alt",
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
                "get_current_timestamp",
                "timestamp_to_datetime_info",
                "datetime_info_to_timestamp",
            ],
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
                                        [
                                            {
                                                "tool_name": "search_reminder",
                                                "arguments": {},
                                            },
                                        ],
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        ),
                    ]
                ),
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
                                        [
                                            {
                                                "tool_name": "get_current_timestamp",
                                                "arguments": {},
                                            },
                                        ],
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        ),
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.REMINDER,
                            snapshot_constraint=update_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "reminder_id": deterministic_uuid(
                                        payload="reminder_2"
                                    ),
                                    "reminder_timestamp": datetime.datetime(
                                        year=get_tomorrow_datetime().year,
                                        month=get_tomorrow_datetime().month,
                                        day=get_tomorrow_datetime().day,
                                        hour=17,
                                    ).timestamp(),
                                }
                            ),
                            reference_milestone_node_index=0,
                        ),
                    ]
                ),
            ],
            milestone_edge_list=[(0, 2), (1, 2)],
            categories=[ScenarioCategories.CANONICALIZATION],
        ),
        ScenarioExtension(
            name="remove_reminder_with_recency_latest",
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
                "get_current_timestamp",
                "timestamp_to_datetime_info",
                "datetime_info_to_timestamp",
            ],
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
                                        [
                                            {
                                                "tool_name": "search_reminder",
                                                "arguments": {},
                                            },
                                        ],
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        ),
                    ]
                ),
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
                                        [
                                            {
                                                "tool_name": "get_current_timestamp",
                                                "arguments": {},
                                            },
                                        ],
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        ),
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.REMINDER,
                            snapshot_constraint=removal_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "reminder_id": deterministic_uuid(
                                        payload="reminder_2"
                                    ),
                                }
                            ),
                            reference_milestone_node_index=0,
                        ),
                    ]
                ),
            ],
            milestone_edge_list=[(0, 2), (1, 2)],
            categories=[ScenarioCategories.CANONICALIZATION],
        ),
        ScenarioExtension(
            name="remove_reminder_with_recency_latest_alt",
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
                    "content": "Get rid of my next reminder.",
                },
            ],
            tool_allow_list=[
                "search_reminder",
                "remove_reminder",
                "get_current_timestamp",
                "timestamp_to_datetime_info",
                "datetime_info_to_timestamp",
            ],
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
                                        [
                                            {
                                                "tool_name": "search_reminder",
                                                "arguments": {},
                                            },
                                        ],
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        ),
                    ]
                ),
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
                                        [
                                            {
                                                "tool_name": "get_current_timestamp",
                                                "arguments": {},
                                            },
                                        ],
                                        ensure_ascii=False,
                                    ),
                                }
                            ),
                        ),
                    ]
                ),
                Milestone(
                    snapshot_constraints=[
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.REMINDER,
                            snapshot_constraint=removal_similarity,
                            target_dataframe=pl.DataFrame(
                                {
                                    "reminder_id": deterministic_uuid(
                                        payload="reminder_2"
                                    ),
                                }
                            ),
                            reference_milestone_node_index=0,
                        ),
                    ]
                ),
            ],
            milestone_edge_list=[(0, 2), (1, 2)],
            categories=[ScenarioCategories.CANONICALIZATION],
        ),
    ]


def named_multiple_tool_call_scenarios(
    preferred_tool_backend: ToolBackend,
) -> dict[str, Scenario]:
    """Scenarios where more than 1 tool call to be issued to complete the task

    Note that this differs from the simple / multi definition of Gorilla. All scenarios below have only the necessary
    tools provided to the model. Additional scenarios will be created to introduce distractions as well.

    Args:
        preferred_tool_backend: Which backend should be chosen in face of conflicting tool names.

    Returns:
        A dict containing scenario name and scenario
    """
    extensions = get_extensions(
        named_base_scenarios(preferred_tool_backend=preferred_tool_backend)
    )
    # All scenarios in this module should be single user turn, multiple tool. Add these categories if they aren't there
    for extension in extensions:
        for default_categories in [
            ScenarioCategories.MULTIPLE_TOOL_CALL,
            ScenarioCategories.SINGLE_USER_TURN,
        ]:
            if default_categories not in extension.categories:
                extension.categories.append(default_categories)
    return {
        key: scenario
        for extension in extensions
        for key, scenario in extension.get_extended_scenario().items()
    }

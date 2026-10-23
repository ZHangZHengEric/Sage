# For licensing see accompanying LICENSE file.
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
"""Scenarios where multiple user turns are required to complete the task

A lot of wordy single user turn test cases can be transformed naturally

"""

import datetime
import json
from functools import partial
from typing import Any

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
    days_extractor,
    min_temperature_amount_extractor,
    min_temperature_extractor,
    result_to_timestamp0_extractor,
    result_to_timestamp1_extractor,
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
    user_simulator_few_shot_examples: dict[str, list[dict[str, Any]]] = (
        named_user_simulator_few_shot_examples()
    )
    return [
        ScenarioExtension(
            name="search_message_with_recency_latest_multiple_user_turn",
            base_scenario=base_scenarios["base"],
            messages=[
                *user_simulator_few_shot_examples[
                    "search_message_with_recency_latest_multiple_user_turn"
                ],
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Find the content of your (User A's) most recent message. "
                    "You do not have more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "I wanna find a message",
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
            name="search_message_with_recency_latest_multiple_user_turn_alt",
            base_scenario=base_scenarios["base"],
            messages=[
                *user_simulator_few_shot_examples[
                    "search_message_with_recency_latest_multiple_user_turn"
                ],
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Find the content of your (User A's) most recent message."
                    "You do not have more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "There's a text I want to find",
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
            name="search_message_with_recency_oldest_multiple_user_turn",
            base_scenario=base_scenarios["base"],
            messages=[
                *user_simulator_few_shot_examples[
                    "search_message_with_recency_latest_multiple_user_turn"
                ],
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Find the content of your (User A's) oldest message. "
                    "You do not have more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "I wanna find a message",
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
            name="search_message_with_recency_oldest_multiple_user_turn_alt",
            base_scenario=base_scenarios["base"],
            messages=[
                *user_simulator_few_shot_examples[
                    "search_message_with_recency_latest_multiple_user_turn"
                ],
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Find the content of your (User A's) oldest message. "
                    "You do not have more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "There's a text I want to find",
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
            name="modify_contact_with_message_recency_multiple_user_turn",
            base_scenario=base_scenarios["base"],
            messages=[
                *user_simulator_few_shot_examples[
                    "modify_contact_with_message_recency_multiple_user_turn"
                ],
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Update the phone number of the last person you (User A) sent a message to to +10293847563."
                    "You do not know who the person is.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Who did I talk to last",
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
                                    "content": "Homer S's phone number has been updated to +10293847563.",
                                }
                            ),
                        )
                    ]
                ),
            ],
            milestone_edge_list=[(0, 2), (1, 4), (2, 3), (3, 4)],
            categories=[ScenarioCategories.CANONICALIZATION],
        ),
        ScenarioExtension(
            name="modify_contact_with_message_recency_multiple_user_turn_alt",
            base_scenario=base_scenarios["base"],
            messages=[
                *user_simulator_few_shot_examples[
                    "modify_contact_with_message_recency_multiple_user_turn"
                ],
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Update the phone number of the last person you (User A) sent a message to to +10293847563. "
                    "You do not know who the person is.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "I need to change someone's phone number",
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
                                    "content": "Homer S's phone number has been updated to +10293847563.",
                                }
                            ),
                        )
                    ]
                ),
            ],
            milestone_edge_list=[(0, 2), (1, 4), (2, 3), (3, 4)],
            categories=[ScenarioCategories.CANONICALIZATION],
        ),
        ScenarioExtension(
            name="remove_contact_by_phone_multiple_user_turn",
            base_scenario=base_scenarios["base"],
            messages=[
                *user_simulator_few_shot_examples[
                    "remove_contact_by_phone_multiple_user_turn"
                ],
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Delete a contact by phone number +12453344098. "
                    "You do not have more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "I want to delete someone from my contact",
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
        ),
        ScenarioExtension(
            name="remove_contact_by_phone_multiple_user_turn_alt",
            base_scenario=base_scenarios["base"],
            messages=[
                *user_simulator_few_shot_examples[
                    "remove_contact_by_phone_multiple_user_turn"
                ],
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Ask User B to delete your (User A's) contact by phone number +12453344098. "
                    "You do not have more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Who's +12453344098 in my contact?",
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
                                    "content": "Fredrik Thordendal has been removed from your contact",
                                }
                            ),
                        )
                    ]
                ),
            ],
        ),
        ScenarioExtension(
            name="send_message_with_contact_content_cellular_off_multiple_user_turn",
            base_scenario=base_scenarios["base_cellular_off"],
            messages=[
                *user_simulator_few_shot_examples[
                    "send_message_with_contact_content_cellular_off_multiple_user_turn"
                ],
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Send a message to Fredrik Thordendal saying: How's the new album coming along. "
                    "You only know Fredrik Thordendal is in your contact. You don not have more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Send a message",
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
            name="send_message_with_contact_content_cellular_off_multiple_user_turn_alt",
            base_scenario=base_scenarios["base_cellular_off"],
            messages=[
                *user_simulator_few_shot_examples[
                    "send_message_with_contact_content_cellular_off_multiple_user_turn"
                ],
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Send a message to Fredrik Thordendal saying: How's the new album coming along. "
                    "You only know Fredrik Thordendal is in your contact. You don not have more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Text Fredrik Thordendal",
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
            name="update_contact_relationship_with_relationship_multiple_user_turn",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Ask User B to update the all friends in (User A's) contact book as (User A's) enemy. "
                    "You do not have more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Who are my friends?",
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
                                    "content": "Fredrik Thordendal and John Petrucci are now your enemies",
                                }
                            ),
                        )
                    ]
                ),
            ],
        ),
        ScenarioExtension(
            name="update_contact_relationship_with_relationship_twice_multiple_user_turn",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Ask User B to update the all friends in (User A's) contact book as (User A's) enemy. "
                    "After User B did so, ask User B to update them back to (User A's) friends. "
                    "You do not have more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Who are my friends?",
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
                                    "content": "Fredrik Thordendal and John Petrucci are now your enemies",
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
                                        "relationship": "friend",
                                        "is_self": False,
                                    },
                                    {
                                        "person_id": deterministic_uuid(
                                            payload="John Petrucci",
                                        ),
                                        "name": "John Petrucci",
                                        "phone_number": "+1234560987",
                                        "relationship": "friend",
                                        "is_self": False,
                                    },
                                ],
                            ),
                            reference_milestone_node_index=1,
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
                                    "content": "Fredrik Thordendal and John Petrucci are now your friends again.",
                                }
                            ),
                        )
                    ]
                ),
            ],
        ),
        ScenarioExtension(
            name="find_days_till_holiday_multiple_user_turn",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + f"Search how many days it is till Christmas Day. "
                    f"Christmas Day is 12/25/{datetime.datetime.now().year}. Do not leak this information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "When's Christmas Day?",
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
            name="find_days_till_holiday_wifi_off_multiple_user_turn",
            base_scenario=base_scenarios["base_wifi_off"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + f"Search how many days it is till Christmas Day. "
                    f"Christmas Day is 12/25/{datetime.datetime.now().year}. Do not leak this information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Christmas Day when?",
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
            name="find_temperature_f_with_location_and_time_diff_multiple_user_turn",
            base_scenario=base_scenarios["base"],
            messages=[
                *user_simulator_few_shot_examples[
                    "find_temperature_f_with_location_and_time_diff_multiple_user_turn"
                ],
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Search what's the lowest temperature in Grand Canyon today, then tomorrow in Fahrenheit. "
                    "You do not have more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What's the lowest temperature in Grand Canyon today",
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
                                                "days": 1,
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
                                extractor=min_temperature_amount_extractor,
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
                                extractor=min_temperature_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "The lowest temperature in Grand Canyon tomorrow "
                                    "is {min_temperature} degrees Fahrenheit",
                                }
                            ),
                            reference_milestone_node_index=1,
                        ),
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=partial(
                                tool_trace_dependant_similarity,
                                fill_to="content",
                                extractor=min_temperature_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "{min_temperature}",
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
            name="find_temperature_f_with_location_and_time_diff_wifi_off_multiple_user_turn",
            base_scenario=base_scenarios["base_wifi_off"],
            messages=[
                *user_simulator_few_shot_examples[
                    "find_temperature_f_with_location_and_time_diff_multiple_user_turn"
                ],
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Search what's the lowest temperature in Grand Canyon today, then tomorrow in Fahrenheit. "
                    "You do not have more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What's the lowest temperature in Grand Canyon today",
                },
            ],
            tool_allow_list=[
                "search_location_around_lat_lon",
                "search_weather_around_lat_lon",
                "unit_conversion",
                "get_wifi_status",
                "set_wifi_status",
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
                                                "days": 1,
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
                                extractor=min_temperature_amount_extractor,
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
                                extractor=min_temperature_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "The lowest temperature in Grand Canyon tomorrow "
                                    "is {min_temperature} degrees Fahrenheit",
                                }
                            ),
                            reference_milestone_node_index=2,
                        ),
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=partial(
                                tool_trace_dependant_similarity,
                                fill_to="content",
                                extractor=min_temperature_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "{min_temperature}",
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
            name="find_temperature_f_with_location_and_time_diff_low_battery_mode_multiple_user_turn",
            base_scenario=base_scenarios[
                "base_low_battery_mode_on_wifi_off_location_service_off_cellular_off"
            ],
            messages=[
                *user_simulator_few_shot_examples[
                    "find_temperature_f_with_location_and_time_diff_multiple_user_turn"
                ],
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Search what's the lowest temperature in Grand Canyon today, then tomorrow in Fahrenheit. "
                    "You do not have more information.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "What's the lowest temperature in Grand Canyon today",
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
                                                "days": 1,
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
                                extractor=min_temperature_amount_extractor,
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
                                extractor=min_temperature_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "The lowest temperature in Grand Canyon tomorrow "
                                    "is {min_temperature} degrees Fahrenheit",
                                }
                            ),
                            reference_milestone_node_index=3,
                        ),
                        SnapshotConstraint(
                            database_namespace=DatabaseNamespace.SANDBOX,
                            snapshot_constraint=partial(
                                tool_trace_dependant_similarity,
                                fill_to="content",
                                extractor=min_temperature_extractor,
                            ),
                            target_dataframe=pl.DataFrame(
                                {
                                    "sender": RoleType.AGENT,
                                    "recipient": RoleType.USER,
                                    "content": "{min_temperature}",
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
        ),
        ScenarioExtension(
            name="find_distance_with_location_name_multiple_user_turn",
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
                    "content": "Where's the Golden Gate Bridge",
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
            name="find_distance_with_location_name_low_battery_mode_multiple_user_turn",
            base_scenario=base_scenarios[
                "base_low_battery_mode_on_wifi_off_location_service_off_cellular_off"
            ],
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
                    "content": "Where's the Golden Gate Bridge",
                },
            ],
            tool_allow_list=[
                "get_current_location",
                "search_location_around_lat_lon",
                "calculate_lat_lon_distance",
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
            categories=[
                ScenarioCategories.CANONICALIZATION,
                ScenarioCategories.STATE_DEPENDENCY,
            ],
        ),
        ScenarioExtension(
            name="add_reminder_content_and_date_and_time_multiple_user_turn",
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
                    "content": "Remind me to buy chocolate milk",
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
            name="add_reminder_content_and_date_and_time_multiple_user_turn_alt",
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
                    "content": "Add a reminder at 3/22/2024 5PM",
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
            name="add_reminder_content_and_week_delta_and_time_multiple_user_turn",
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
                    "content": "Remind me to buy chocolate milk",
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
            name="add_reminder_content_and_week_delta_and_time_multiple_user_turn_alt",
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
                    "content": "Add a reminder for tomorrow 5PM",
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
            name="add_reminder_content_and_weekday_delta_and_time_multiple_user_turn",
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
                    "content": "Remind me to buy chocolate milk",
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
            name="add_reminder_content_and_weekday_delta_and_time_multiple_user_turn_alt",
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
                    "content": "Add a reminder next Friday 5PM",
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
            name="add_reminder_content_and_week_delta_and_time_and_location_multiple_user_turn",
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
                    "content": "Remind me to buy chocolate milk at Whole Foods on Stevens Creek.",
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
            name="add_reminder_content_and_week_delta_and_time_and_location_multiple_user_turn_alt",
            base_scenario=base_scenarios["base"],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Ask User B create a reminder to buy chocolate milk tomorrow 5PM at "
                    "Whole Foods on McKinley Ave. "
                    "You do not have any more information. Make sure it's right Whole Foods.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Add a reminder to buy chocolate milk tomorrow 5PM at Whole Foods.",
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
                                    "latitude": 37.3738083,
                                    "longitude": -122.03142249999999,
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
            name="add_reminder_content_and_week_delta_and_time_and_location_low_battery_mode_multiple_user_turn_alt",
            base_scenario=base_scenarios[
                "base_low_battery_mode_on_wifi_off_location_service_off_cellular_off"
            ],
            messages=[
                {
                    "sender": RoleType.SYSTEM,
                    "recipient": RoleType.USER,
                    "content": USER_INSTRUCTION
                    + "Ask User B create a reminder to buy chocolate milk tomorrow 5PM at "
                    "Whole Foods on McKinley Ave. "
                    "You do not have any more information. Make sure it's right Whole Foods.",
                },
                {
                    "sender": RoleType.USER,
                    "recipient": RoleType.AGENT,
                    "content": "Add a reminder to buy chocolate milk at Whole Foods.",
                },
            ],
            tool_allow_list=[
                "add_reminder",
                "modify_reminder",
                "get_current_timestamp",
                "timestamp_to_datetime_info",
                "datetime_info_to_timestamp",
                "search_location_around_lat_lon",
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
                                    "latitude": 37.3738083,
                                    "longitude": -122.03142249999999,
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
            milestone_edge_list=[(0, 1), (1, 2), (2, 4), (3, 4)],
            categories=[ScenarioCategories.CANONICALIZATION],
        ),
    ]


def named_multiple_user_turn_scenarios(
    preferred_tool_backend: ToolBackend,
) -> dict[str, Scenario]:
    """Scenarios where multiple user turns are required to complete the task

    Args:
        preferred_tool_backend: Which backend should be chosen in face of conflicting tool names.

    Returns:
        A dict containing scenario name and scenario
    """
    extensions = get_extensions(
        named_base_scenarios(preferred_tool_backend=preferred_tool_backend)
    )
    # All scenarios in this module should be multiple user turn, multiple tool.
    # Add these categories if they aren't there
    for extension in extensions:
        for default_categories in [
            ScenarioCategories.MULTIPLE_TOOL_CALL,
            ScenarioCategories.MULTIPLE_USER_TURN,
        ]:
            if default_categories not in extension.categories:
                extension.categories.append(default_categories)
    return {
        key: scenario
        for extension in extensions
        for key, scenario in extension.get_extended_scenario().items()
    }

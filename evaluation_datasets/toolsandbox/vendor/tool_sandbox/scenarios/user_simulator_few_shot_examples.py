# For licensing see accompanying LICENSE file.
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
"""Few shot examples for user simulator"""

from textwrap import dedent
from typing import Any

from tool_sandbox.common.execution_context import RoleType

# It looks like reversing the roles completely makes GPT-4 simulated user very confused.
# Referring to the other party as "the other user" seems to help

USER_INSTRUCTION = dedent(
    """
    You are no longer an assistant. From now on role play as a user (User A) talking to another user (User B).
    Make sure you follow these instructions:

    0. DO NOT act as if you (User A) are an assistant. ALWAYS treat yourself as a user (User A).
        Do not ask questions to the other user (User B).
    1. Answer any question User B asks you (User A) accurately. Use only the information provided.
        Do not make up false information.
    2.  Use natural, short, casual language.
    3.  If User B says it could not complete the task, either provide more information
        you (User A) posses, or ask it to use the tools it figure it out itself if you (User A)
        do not posses information that could help.
    4.  Allow User B to turn off low battery mode, turn on cellular service, wifi or location service
        in order to complete the task.
    5.  When User B completed the task, even if you (User A) don't have enough information to validate the
        correctness, break out of role playing and use the provided tool named `end_conversation` to stop
        the conversation.
    6.  When User B cannot complete the request after 5 tries, break out of role playing and
         use the provided tool named `end_conversation` to stop the conversation.

    Answer User B's questions given the following task you (User A) want User B to complete: """
).lstrip()


def named_user_simulator_few_shot_examples() -> dict[str, list[dict[str, Any]]]:
    """Instantiates example name and lists of example messages

    Even though not explicitly documented, we found that providing
    few-shot examples, each with their own system prompt works reasonably well
    for user simulator. This can help control user simulator behavior,
    making sure it rarely reverts back to assistant behavior, and closely follows
    few-shot examples.

    Returns:
        A dictionary of few-shot user simulator examples.
    """
    # At the moment, the keys mirror the scenarios they are applied to.
    # In the long run I'm hoping that we could have a few general purpose
    # prompts that works for all scenarios
    examples: dict[str, list[dict[str, Any]]] = {
        "search_message_with_recency_latest_multiple_user_turn": [
            {
                "sender": RoleType.SYSTEM,
                "recipient": RoleType.USER,
                "content": USER_INSTRUCTION
                + "Find the content of your (User A's) oldest message",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.USER,
                "recipient": RoleType.AGENT,
                "content": "Find a message for me",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.AGENT,
                "recipient": RoleType.USER,
                "content": "Sure I can help you with that, can you provide me with some details? For example:\n"
                "- The content of the message\n"
                "- The phone number of the sender or recipient\n"
                "- The unique id of the sender or recipient\n"
                "- A time range of when it was received.",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.USER,
                "recipient": RoleType.AGENT,
                "content": "Just get me the oldest one.",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.AGENT,
                "recipient": RoleType.USER,
                "content": 'Your oldest message says "Hey kid, you want some GPUs?"',
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.USER,
                "recipient": RoleType.EXECUTION_ENVIRONMENT,
                "content": "end_conversation()",
                "visible_to": [RoleType.USER],
            },
        ],
        "modify_contact_with_message_recency_multiple_user_turn": [
            {
                "sender": RoleType.SYSTEM,
                "recipient": RoleType.USER,
                "content": USER_INSTRUCTION
                + "Update the phone number of the last person you (User A) sent a message to to +17568390043.",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.USER,
                "recipient": RoleType.AGENT,
                "content": "I need to update a phone number.",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.AGENT,
                "recipient": RoleType.USER,
                "content": "Do you know the unique id of the contact you want to update?",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.USER,
                "recipient": RoleType.AGENT,
                "content": "No, who's the last person I talked to?",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.AGENT,
                "recipient": RoleType.USER,
                "content": "The last person you talked to was Bart.",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.USER,
                "recipient": RoleType.AGENT,
                "content": "Change his phone number to +17568390043",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.AGENT,
                "recipient": RoleType.USER,
                "content": "Bart's phone number has been updated to +17568390043.",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.USER,
                "recipient": RoleType.EXECUTION_ENVIRONMENT,
                "content": "end_conversation()",
                "visible_to": [RoleType.USER],
            },
        ],
        "remove_contact_by_phone_multiple_user_turn": [
            {
                "sender": RoleType.SYSTEM,
                "recipient": RoleType.USER,
                "content": USER_INSTRUCTION
                + "Delete a contact by phone number +13493028493.",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.USER,
                "recipient": RoleType.AGENT,
                "content": "I need to delete someone.",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.AGENT,
                "recipient": RoleType.USER,
                "content": "Sure, could you provide some detail about the contact you wish to delete? "
                "Information like the name and unique ID could be helpful.",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.USER,
                "recipient": RoleType.AGENT,
                "content": "I don't know either of these.",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.AGENT,
                "recipient": RoleType.USER,
                "content": "OK, let's try something else. What about phone number?",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.USER,
                "recipient": RoleType.AGENT,
                "content": "It is +12453344098",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.AGENT,
                "recipient": RoleType.USER,
                "content": "The contact with phone number +13493028493 has been successfully deleted.",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.USER,
                "recipient": RoleType.EXECUTION_ENVIRONMENT,
                "content": "end_conversation()",
                "visible_to": [RoleType.USER],
            },
        ],
        "send_message_with_contact_content_cellular_off_multiple_user_turn": [
            {
                "sender": RoleType.SYSTEM,
                "recipient": RoleType.USER,
                "content": USER_INSTRUCTION
                + "Send a message to Bart saying: Hey what's up.",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.USER,
                "recipient": RoleType.AGENT,
                "content": "I want to send a message to someone.",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.AGENT,
                "recipient": RoleType.USER,
                "content": "Certainly! I can help you with sending a message. "
                "Could you please provide the following details: "
                "1. The phone number of the recipient. "
                "2. The content of the message you'd like to send.",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.USER,
                "recipient": RoleType.AGENT,
                "content": "I don't know the phone number.",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.AGENT,
                "recipient": RoleType.USER,
                "content": "OK, could you provide some more information about "
                "the contact you'd like to send message to?",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.USER,
                "recipient": RoleType.AGENT,
                "content": "It's Bart",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.AGENT,
                "recipient": RoleType.USER,
                "content": "What would you like to say to Bart?",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.USER,
                "recipient": RoleType.AGENT,
                "content": "Hey what's up",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.AGENT,
                "recipient": RoleType.USER,
                "content": "I'm about to send a message saying 'Hey what's up.' to Bart. Does this look good?",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.USER,
                "recipient": RoleType.AGENT,
                "content": "Yep",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.AGENT,
                "recipient": RoleType.USER,
                "content": "Your message has been successfully sent.",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.USER,
                "recipient": RoleType.EXECUTION_ENVIRONMENT,
                "content": "end_conversation()",
                "visible_to": [RoleType.USER],
            },
        ],
        "find_temperature_f_with_location_and_time_diff_multiple_user_turn": [
            {
                "sender": RoleType.SYSTEM,
                "recipient": RoleType.USER,
                "content": USER_INSTRUCTION
                + "Search what's the wind speed in Cupertino today, and then next Monday in mph.",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.USER,
                "recipient": RoleType.AGENT,
                "content": "What's the wind speed in Cupertino today?",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.AGENT,
                "recipient": RoleType.USER,
                "content": "The wind is blowing at 6 km/h right now in Cupertino.",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.USER,
                "recipient": RoleType.AGENT,
                "content": "What about next Monday?",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.AGENT,
                "recipient": RoleType.USER,
                "content": "The wind speed next Monday in Cupertino is 7 km/h.",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.USER,
                "recipient": RoleType.AGENT,
                "content": "In mph",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.AGENT,
                "recipient": RoleType.USER,
                "content": "The wind speed next Monday in Cupertino is 4.4 mph.",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.USER,
                "recipient": RoleType.EXECUTION_ENVIRONMENT,
                "content": "end_conversation()",
                "visible_to": [RoleType.USER],
            },
        ],
        "find_temperature_low_battery_mode": [
            {
                "sender": RoleType.SYSTEM,
                "recipient": RoleType.USER,
                "content": USER_INSTRUCTION + "Search for current temperature.",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.USER,
                "recipient": RoleType.AGENT,
                "content": "What's the temperature right now?",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.AGENT,
                "recipient": RoleType.USER,
                "content": "I cannot complete the search due to service issues.",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.USER,
                "recipient": RoleType.AGENT,
                "content": "Try again with the tools you have.",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.AGENT,
                "recipient": RoleType.USER,
                "content": "I couldn't search for the temperature due to wifi being off. "
                "Would you like to turn on wifi?",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.USER,
                "recipient": RoleType.AGENT,
                "content": "Yes.",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.AGENT,
                "recipient": RoleType.USER,
                "content": "I couldn't turn on wifi due to low battery mode being on. "
                "Would you like to turn off low battery mode?",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.USER,
                "recipient": RoleType.AGENT,
                "content": "Yes",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.AGENT,
                "recipient": RoleType.USER,
                "content": "I'm still having trouble as location service is also not enabled. "
                "Would you like to turn it on?",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.USER,
                "recipient": RoleType.AGENT,
                "content": "Yes",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.AGENT,
                "recipient": RoleType.USER,
                "content": "The current temperature is 25 degree Celsius.",
                "visible_to": [RoleType.USER],
            },
            {
                "sender": RoleType.USER,
                "recipient": RoleType.EXECUTION_ENVIRONMENT,
                "content": "end_conversation()",
                "visible_to": [RoleType.USER],
            },
        ],
    }
    for example in examples.values():
        for message in example:
            assert message["visible_to"] == [RoleType.USER], (
                f"User simulator messages should only be visible to {[RoleType.USER]}. "
                f"Found {message['visible_to']}"
            )
    return examples

"""Upload this file separately from scorer.py for pinned τ² retail user behavior.

The official UserSimulator owns the system prompt and stop-token detection;
UserScenario and UserState own scenario formatting and conversation role flips.
Only generate() is replaced by Sage's run-scoped ModelProvider transport.
No RSI JSON-decision instructions are inserted into the official model prompt.
"""
from __future__ import annotations

import json

from evaluation_datasets.tau_bench.runtime import activate
from sagents.v2.contracts.items import TextBlock
from sagents.v2.model.contracts import ModelMessage
from sagents.v2.optimization.default_user_simulator import generate_user_text
from sagents.v2.optimization.user_simulator_runtime import get_model_provider

USER_SIMULATOR_CONTRACT = '''Pinned tau2 retail, text-only user simulation. Use the
vendored official default system prompt, str(UserScenario), UserState.flip_roles(),
and official UserSimulator.is_stop(). Generate exactly one natural-language user
message per model call, temperature=0, without tools or a JSON response schema.
Convert official STOP / TRANSFER / OUT-OF-SCOPE tokens to the Sage decision only
after generation. No grading references, business tool results or task answers
are visible to the user model. This adapter does not implement a tool-using or
voice user, nor claim an official standard-harness leaderboard score.'''


def official_messages(request):
    activate()
    from tau2.data_model.message import AssistantMessage, SystemMessage, UserMessage
    from tau2.data_model.tasks import UserScenario
    from tau2.user.user_simulator import UserSimulator
    from tau2.user.user_simulator_base import UserState
    scenario = UserScenario.model_validate(json.loads(request['case']['user_context']))
    simulator = UserSimulator(llm='sage-run-provider', instructions=str(scenario))
    history = []
    for message in request['conversation']:
        if not isinstance(message['content'], str):
            raise ValueError('tau retail text simulator requires text-only visible messages')
        kind = UserMessage if message['role'] == 'user' else AssistantMessage
        history.append(kind(role=message['role'], content=message['content']))
    state = UserState(system_messages=[SystemMessage(role='system', content=simulator.system_prompt)],
                      messages=history)
    official = [*state.system_messages, *state.flip_roles()]
    return tuple(ModelMessage(role=m.role, content=(TextBlock(text=m.content or ''),)) for m in official)


async def reply(request):
    # Do not ask for Sage's JSON structure: official tau generates plain user text.
    text = await generate_user_text(get_model_provider(), official_messages(request), temperature=0)
    from tau2.data_model.message import UserMessage
    from tau2.user.user_simulator import UserSimulator
    from tau2.user.user_simulator_base import STOP, TRANSFER, OUT_OF_SCOPE
    if UserSimulator.is_stop(UserMessage(role='user', content=text)):
        reason = ('transferred' if TRANSFER in text else 'out_of_scope' if OUT_OF_SCOPE in text else 'completed')
        return {'can_continue': False, 'message': '', 'stop_reason': reason,
                'rationale': 'Official tau user emitted ' + (TRANSFER if reason == 'transferred' else OUT_OF_SCOPE if reason == 'out_of_scope' else STOP)}
    return {'can_continue': True, 'message': text,
            'rationale': 'Official tau user generated the next scenario message.'}


_SCENARIO = {'persona': None, 'instructions': {'domain': 'retail',
    'reason_for_call': 'Return a delivered item.', 'known_info': 'Order #123.',
    'unknown_info': None, 'task_instructions': 'Ask to return the item; disclose order ID when asked.'}}
_REQUEST = {'case': {'id': 'tau-contract', 'split': 'training', 'input': 'Hello.',
    'user_context': json.dumps(_SCENARIO)}, 'conversation': [
        {'role': 'user', 'content': 'Hello.'}, {'role': 'assistant', 'content': 'How can I help?'}],
    'turns_remaining': 19}
USER_SIMULATOR_TEST_CASES = [
    {'request': _REQUEST, 'model_responses': [{'response_id': 'tau-fixture', 'text': text, 'finish_reason': 'stop'}],
     'expected_reply': expected}
    for text, expected in [
        ('I would like to return an item.', {'can_continue': True, 'message': 'I would like to return an item.',
            'rationale': 'Official tau user generated the next scenario message.'}),
        ('Thank you. ###STOP###', {'can_continue': False, 'message': '', 'stop_reason': 'completed',
            'rationale': 'Official tau user emitted ###STOP###'}),
        ('###TRANSFER###', {'can_continue': False, 'message': '', 'stop_reason': 'transferred',
            'rationale': 'Official tau user emitted ###TRANSFER###'}),
        ('###OUT-OF-SCOPE###', {'can_continue': False, 'message': '', 'stop_reason': 'out_of_scope',
            'rationale': 'Official tau user emitted ###OUT-OF-SCOPE###'}),
    ]
]

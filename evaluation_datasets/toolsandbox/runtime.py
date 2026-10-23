"""Pinned official ToolSandbox scenarios, tools and milestone evaluation."""
from __future__ import annotations

import copy
from functools import lru_cache
import json
from pathlib import Path

from evaluation_datasets._support import activate as activate_source
from evaluation_datasets.toolsandbox.clock import FROZEN_TIME, frozen_clock

ROOT = Path(__file__).resolve().parent


def activate():
    return activate_source(ROOT, 'vendor')


@lru_cache(maxsize=1)
def scenarios():
    activate()
    from tool_sandbox.common.tool_discovery import ToolBackend
    from tool_sandbox.scenarios import (
        named_single_tool_call_scenarios, named_multiple_tool_call_scenarios,
        named_multiple_user_turn_scenarios, named_insufficient_information_scenarios,
    )
    result = {}
    with frozen_clock():
        for factory in (named_single_tool_call_scenarios, named_multiple_tool_call_scenarios,
                        named_multiple_user_turn_scenarios, named_insufficient_information_scenarios):
            result.update(factory(preferred_tool_backend=ToolBackend.DEFAULT))
    # An explicitly offline base-scenario subset, not the full augmented benchmark.
    return {name: s for name, s in sorted(result.items()) if not any(
        '.rapid_api_search_tools' in f.__module__
        for f in s.starting_context.get_available_tools(scrambling_allowed=False).values())}


def scenario(name):
    if name not in scenarios():
        raise ValueError('Unknown or non-offline ToolSandbox scenario')
    return copy.deepcopy(scenarios()[name])


def _set_state(state):
    from tool_sandbox.common.execution_context import ExecutionContext, set_current_context
    context = ExecutionContext.from_dict(state)
    set_current_context(context)
    # Console code is never deserialized from the execution record or disk.
    context.interactive_console.locals.update(context.name_to_tool)
    context.interactive_console.locals['json'] = json
    return context


def tools(context=None):
    activate()
    from tool_sandbox.common.execution_context import RoleType, set_current_context
    from tool_sandbox.common.tool_conversion import convert_to_openai_tool
    selected = [scenario(context['scenario'])] if context else list(scenarios().values())
    result = {}
    for selected_scenario in selected:
        current = selected_scenario.starting_context
        set_current_context(current)
        for name, function in current.get_available_tools(scrambling_allowed=False).items():
            if RoleType.AGENT in function.visible_to:
                result[name] = convert_to_openai_tool(function)['function']
    return list(result.values())


def initial(context):
    return scenario(context['scenario']).starting_context.to_dict(serialize_console=False)


def execute(context, calls):
    """Use the official execution role, including parallel-call permutation checks."""
    from tool_sandbox.common.execution_context import RoleType, get_current_context
    from tool_sandbox.common.message_conversion import Message, openai_tool_call_to_python_code
    from tool_sandbox.roles.execution_environment import ExecutionEnvironment
    from openai.types.chat.chat_completion_message_tool_call import ChatCompletionMessageToolCall, Function
    allowed = {name for name, f in context.get_available_tools(scrambling_allowed=False).items()
               if RoleType.AGENT in f.visible_to}
    messages = []
    for index, (name, arguments) in enumerate(calls):
        call_id = f'call_{context.max_sandbox_message_index}_{index}'
        tool_call = ChatCompletionMessageToolCall(id=call_id, type='function',
            function=Function(name=name, arguments=json.dumps(arguments)))
        code = openai_tool_call_to_python_code(tool_call, allowed, None)
        messages.append(Message(sender=RoleType.AGENT, recipient=RoleType.EXECUTION_ENVIRONMENT,
                                content=code, openai_tool_call_id=call_id, openai_function_name=name))
    role = ExecutionEnvironment()
    role.add_messages(messages)
    with frozen_clock():
        role.respond()
    return get_current_context(), role.get_messages()[-len(calls):]


def call(case_context, state, name, arguments):
    current = _set_state(state)
    current, messages = execute(current, [(name, arguments)])
    result = messages[-1]
    return current.to_dict(serialize_console=False), result.content, result.tool_call_exception


def evaluate(name, events, names):
    from tool_sandbox.common.execution_context import RoleType, set_current_context, get_current_context
    from tool_sandbox.common.message_conversion import Message
    from tool_sandbox.roles.base_role import BaseRole
    from evaluation_datasets._support import message_text
    selected = scenario(name)
    current = _set_state(selected.starting_context.to_dict(serialize_console=False))
    pending = []
    results = {e['tool_call_id']: e for e in events if e.get('kind') == 'tool_result'}
    def flush():
        nonlocal current
        if pending:
            current, replies = execute(current, [(tool, args) for tool, args, _ in pending])
            if any((reply.tool_call_exception is not None) != failed
                   for reply, (_, _, failed) in zip(replies, pending, strict=True)):
                raise ValueError('Native tool outcome differs from official replay; invalid measurement')
            pending.clear()
    # The official starting context already contains the initial user message.
    initial_user = BaseRole.get_messages()[-1].content
    skipped_opening = False
    for event in events:
        if event.get('kind') == 'tool_call':
            tool = event.get('tool_name')
            if tool not in names:
                raise ValueError(f'Unexpected tool outside ToolSandbox: {tool}')
            pending.append((names[tool], event['arguments'], results[event['tool_call_id']].get('error') is not None))
        elif event.get('kind') == 'tool_result':
            flush()
        elif event.get('kind') == 'message' and event.get('role') in ('user', 'assistant'):
            flush()
            text = message_text(event)
            if event['role'] == 'user' and not skipped_opening and text == initial_user:
                skipped_opening = True
                continue
            sender = RoleType.USER if event['role'] == 'user' else RoleType.AGENT
            BaseRole.add_messages([Message(sender=sender,
                recipient=RoleType.AGENT if sender == RoleType.USER else RoleType.USER, content=text)])
    flush()
    set_current_context(current)
    with frozen_clock():
        result = selected.evaluation.evaluate(get_current_context(), max_turn_count=selected.max_messages)
    from attrs import asdict
    return asdict(result)


def preflight():
    manifest = activate()
    return {'commit': manifest['commit'], 'scenarios': len(scenarios()),
            'tools': len(tools()), 'scope': 'offline base scenarios', 'frozen_time': FROZEN_TIME}

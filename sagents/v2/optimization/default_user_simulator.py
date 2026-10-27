"""Built-in scenario user; no benchmark-specific behavior or grading access."""
from __future__ import annotations

import json
import re

from sagents.v2.contracts.items import TextBlock
from sagents.v2.model.contracts import ModelEventKind, ModelMessage, ModelRequest
from sagents.v2.optimization.principles import DIALOGUE_USER_PRINCIPLES
from sagents.v2.optimization.user_simulator import (
    UserSimulator, UserSimulatorDescriptor, UserSimulationReply,
)


async def generate_user_text(provider, messages, *, temperature=None):
    """One plain model request, with no agent, tools, grader or hidden references."""
    from sagents.v2.optimization.python_user_simulator import UserSimulationExecutionError
    request = ModelRequest(request_id='user-simulator', run_id='user-simulator',
        model_binding=provider.model_binding, messages=tuple(messages), temperature=temperature)
    response = None
    stream = provider.stream(request)
    try:
        async for event in stream:
            if event.kind == ModelEventKind.COMPLETED:
                response = event.response
    finally:
        close = getattr(stream, 'aclose', None)
        if close is not None:
            await close()
    if response is None or response.tool_calls or response.finish_reason in {'length', 'max_tokens', 'incomplete'}:
        raise UserSimulationExecutionError('User ModelProvider did not complete a text response')
    if not response.text.strip():
        raise UserSimulationExecutionError('User ModelProvider returned empty text')
    return response.text


class DefaultUserSimulator(UserSimulator):
    """Default RSI JSON decision policy, invoked with a run-scoped provider.

    provider_factory(request) is an async context manager yielding ModelProvider.
    A new local request/state is used for every case/trial; no conversations are
    kept on this shared instance. Custom instructions extend the same boundaries.
    """
    descriptor = UserSimulatorDescriptor(id='sage.rsi.default-user', name='RSI built-in user', version='1')

    def __init__(self, provider_factory, *, instructions=None):
        self.provider_factory = provider_factory
        self.instructions = instructions
        if instructions:
            import hashlib
            self.descriptor = self.descriptor.model_copy(update={
                'version': hashlib.sha256(instructions.encode()).hexdigest()})

    async def reply(self, request):
        system = DIALOGUE_USER_PRINCIPLES + '\nReturn one JSON object matching response_schema. '
        system += ('When continuing, provide a nonblank message and no stop_reason. When stopping, provide an empty message and stop_reason=completed, transferred or out_of_scope. Always provide a nonblank rationale.')
        if self.instructions:
            system += '\n\nUser simulation instructions:\n' + self.instructions
        payload = {'task': 'Continue this test as the user.', 'data': request.model_dump(mode='json'),
                   'response_schema': UserSimulationReply.model_json_schema()}
        messages = (ModelMessage(role='system', content=(TextBlock(text=system),)),
            ModelMessage(role='user', content=(TextBlock(text=json.dumps(payload, ensure_ascii=False)),)))
        from pydantic import ValidationError
        from sagents.v2.contracts.errors import SageV2Error
        from sagents.v2.optimization.python_user_simulator import UserSimulationExecutionError
        from sagents.v2.optimization.recovery import OptimizationTransientFailure
        async with self.provider_factory(request) as provider:
            for attempt in range(3):
                try:
                    text = await generate_user_text(provider, messages)
                except SageV2Error as error:
                    if error.info.retryable:
                        raise OptimizationTransientFailure('User ModelProvider transport interrupted') from error
                    raise UserSimulationExecutionError('User ModelProvider rejected the request') from error
                fenced = re.fullmatch(r'\s*```(?:json)?\s*\n?(.*?)\n?```\s*', text, re.DOTALL)
                try:
                    return UserSimulationReply.model_validate_json(fenced.group(1) if fenced else text, strict=True)
                except ValidationError:
                    if attempt == 2:
                        raise UserSimulationExecutionError('Built-in user returned invalid decisions after three attempts') from None
                    messages = (*messages,
                        ModelMessage(role='assistant', content=(TextBlock(text=text),)),
                        ModelMessage(role='user', content=(TextBlock(text='Invalid decision. Return valid JSON matching response_schema; provide a nonblank rationale, a nonblank message when continuing, or an empty message and explicit stop_reason when stopping.'),)))

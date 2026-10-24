"""Independent user simulation: visible dialogue in, one user decision out."""
from __future__ import annotations

from abc import ABC, abstractmethod
import json
from typing import Any, Literal

from pydantic import Field, model_validator

from sagents.v2.contracts.common import StrictModel, VerbatimText
from sagents.v2.optimization.contracts import OptimizationDialogueReply


class UserSimulatorDescriptor(StrictModel):
    protocol: Literal['sage.rsi.user-simulator/v1'] = 'sage.rsi.user-simulator/v1'
    id: str = Field(min_length=1, max_length=192)
    name: str = Field(min_length=1, max_length=255)
    version: str = Field(min_length=1, max_length=128)
    contract: str | None = Field(default=None, min_length=1, max_length=16000)


class UserSimulationCase(StrictModel):
    id: str
    split: Literal['training', 'validation', 'test', 'final']
    input: str
    user_context: str = ''


class UserVisibleMessage(StrictModel):
    role: Literal['user', 'assistant']
    content: Any
    timestamp: str | None = None


class UserSimulationRequest(StrictModel):
    protocol: Literal['sage.rsi.user-simulator/v1'] = 'sage.rsi.user-simulator/v1'
    case: UserSimulationCase
    conversation: tuple[UserVisibleMessage, ...] = ()
    turns_remaining: int = Field(ge=0, le=20)
    trial: int = Field(default=1, ge=1, le=10)
    state: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_dialogue(cls, case, data, trial=1):
        # Construct from an allowlist, never serializing the full benchmark case.
        return cls(case=UserSimulationCase(id=case.id, split=case.split,
            input=case.input, user_context=case.user_context),
            conversation=data['conversation'], turns_remaining=data['turns_remaining'],
            trial=trial, state=data.get('state', {}))


class UserSimulationReply(OptimizationDialogueReply):
    message: VerbatimText
    stop_reason: Literal['completed', 'transferred', 'out_of_scope'] | None = None
    state: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode='after')
    def validate_decision(self):
        if self.can_continue and self.stop_reason is not None:
            raise ValueError('continuing user cannot specify a stop reason')
        if not self.can_continue and self.message.strip():
            raise ValueError('stopping user must return an empty message')
        if not self.can_continue and self.stop_reason is None:
            raise ValueError('stopping user must specify a stop reason')
        if not self.rationale.strip():
            raise ValueError('user decision requires a rationale')
        if len(json.dumps(self.state, allow_nan=False).encode()) > 65536:
            raise ValueError('user simulator state exceeds 64 KiB')
        return self


class UserSimulator(ABC):
    """Host-owned simulator. It receives no rubric, reference or tool evidence.

    Implement reply(); use user_simulator_runtime.get_model_provider() inside an
    uploaded module to call the run-scoped RSI model. No provider is granted while
    import contract tests run, unless recorded model_responses are supplied.
    """
    descriptor: UserSimulatorDescriptor

    @abstractmethod
    async def reply(self, request: UserSimulationRequest) -> UserSimulationReply:
        raise NotImplementedError


def termination_reason(reply):
    return {'completed': 'user_finished', 'transferred': 'user_transferred',
        'out_of_scope': 'user_out_of_scope'}.get(getattr(reply, 'stop_reason', None), 'user_finished')

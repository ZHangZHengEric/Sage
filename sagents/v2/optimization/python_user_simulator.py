"""Frozen subprocess implementation of the independent user simulation contract."""
from sagents.v2.optimization.python_scorer import PythonExecutionScorer, ScorerExecutionError
from sagents.v2.optimization.user_simulator import UserSimulator, UserSimulatorDescriptor, UserSimulationReply


class UserSimulationExecutionError(RuntimeError):
    rsi_requires_feedback = True  # Invalid code/contracts require a human correction.


class PythonUserSimulator(PythonExecutionScorer, UserSimulator):
    descriptor_type = UserSimulatorDescriptor
    worker_module = 'sagents.v2.optimization.python_user_simulator_worker'

    async def _execute(self, *args, **kwargs):
        try:
            return await super()._execute(*args, **kwargs)
        except ScorerExecutionError as error:
            raise UserSimulationExecutionError(str(error).replace('scorer', 'user simulator')) from error

    async def validate(self):
        try:
            return await super().validate()
        except ScorerExecutionError as error:
            raise UserSimulationExecutionError(str(error).replace('scorer', 'user simulator')) from error

    async def reply(self, request):
        payload = request.model_dump_json().encode()
        if len(payload) > 32 * 1024 * 1024:
            raise UserSimulationExecutionError('user simulation request exceeds 32 MiB')
        if self.model_api_factory is not None:
            async with self.model_api_factory(request) as api:
                return UserSimulationReply.model_validate_json(await self._execute(payload, model_api=api), strict=True)
        return UserSimulationReply.model_validate_json(await self._execute(payload, model_api=self.model_api), strict=True)

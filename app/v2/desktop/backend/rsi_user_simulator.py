"""Owner-scoped immutable imports for host-side Python user simulation."""
import ast
import hashlib
import os
from pathlib import Path

from pydantic import Field, model_validator

from sagents.v2.contracts.common import StrictModel, utc_now
from sagents.v2.optimization.recovery import configuration_fingerprint
from sagents.v2.optimization.scorer_dependencies import dependency_binding, verify_dependencies
from sagents.v2.optimization.user_simulator import UserSimulatorDescriptor
from sagents.v2.optimization.python_user_simulator import PythonUserSimulator

PUBLIC = ('id', 'name', 'source_hash', 'descriptor', 'validation', 'created_at')


class UserSimulatorImport(StrictModel):
    name: str = Field(min_length=1, max_length=255)
    source: str = Field(min_length=1, max_length=1024 * 1024)

    @model_validator(mode='after')
    def valid_entry(self):
        try:
            tree = ast.parse(self.source)
        except SyntaxError as error:
            raise ValueError('user simulator must be valid Python source') from error
        function = any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == 'reply' for n in tree.body)
        instance = any((isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'USER_SIMULATOR'
            for t in n.targets)) or (isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
            and n.target.id == 'USER_SIMULATOR') for n in tree.body)
        if function == instance:
            raise ValueError('export either reply(request) or USER_SIMULATOR')
        return self


class DesktopUserSimulatorMixin:
    async def import_rsi_user_simulator(self, agent_id, module: UserSimulatorImport, user_id):
        await self._agent(agent_id, user_id)
        digest = hashlib.sha256(module.source.encode()).hexdigest()
        scope = hashlib.sha256(f'{user_id}\0{agent_id}'.encode()).hexdigest()
        directory = self.runtime_root / 'rsi-user-simulators' / scope / digest
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = directory / 'user_simulator.py'
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError('frozen user simulator source changed')
        else:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                stream.write(module.source)
        checker = PythonUserSimulator(path=path, source_hash=digest,
            descriptor=UserSimulatorDescriptor(id='validation', name=module.name, version=digest), timeout=10)
        try:
            validation = await checker.validate()
        except (RuntimeError, TimeoutError, ValueError) as error:
            raise ValueError(f'user simulator validation failed: {str(error) or "validation timeout"}') from error
        binding = dependency_binding(digest, checker.dependency_manifest)
        identity = 'rsi_user_' + configuration_fingerprint([user_id, agent_id, module.name, binding])[:24]
        descriptor = UserSimulatorDescriptor(id=identity, name=module.name, version=binding,
            contract=validation.get('user_simulator_contract'))
        try:
            value = self.rsi_store.get(identity, user_id, agent_id, 'user_simulator')
        except ValueError:
            value = dict(id=identity, name=module.name, path=str(path), source_hash=digest,
                descriptor=descriptor.model_dump(mode='json'), validation=validation,
                dependency_manifest=checker.dependency_manifest, binding_hash=binding,
                created_at=utc_now().isoformat())
            self.rsi_store.put(value, user_id, agent_id, 'user_simulator')
        return {key: value[key] for key in PUBLIC}

    def _rsi_user_simulator_selection(self, request, user_id, agent_id):
        if request.user_simulator_id is None:
            if request.user_simulator_binding_id is not None:
                raise ValueError('user simulator binding requires a selected module')
            return None
        if request.user_simulator_instructions is not None:
            raise ValueError('choose a Python user simulator or custom user instructions')
        stored = self.rsi_store.get(request.user_simulator_id, user_id, agent_id, 'user_simulator')
        if stored.get('validation', {}).get('status') != 'passed':
            raise ValueError('user simulator has not passed validation')
        digest = hashlib.sha256(Path(stored['path']).read_bytes()).hexdigest()
        if digest != stored['source_hash']:
            raise ValueError('frozen user simulator source changed')
        verify_dependencies(stored['dependency_manifest'])
        binding = dependency_binding(digest, stored['dependency_manifest'])
        if (binding != stored['binding_hash'] or stored['descriptor']['version'] != binding
                or request.user_simulator_binding_id not in {None, binding}):
            raise ValueError('user simulator binding changed since this experiment')
        return stored

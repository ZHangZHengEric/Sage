"""Offline trusted-source extension demo: python3.12 -m examples.sagents_v2_source_plugin.

Source extensions run with host Python privileges. This demo authorizes only its
exact fixed bundle; generated or user-supplied code needs a real host policy.
"""
from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from examples.sagents_v2_agent_management import step
from sagents.v2 import AgentManagementService, AgentPackageBundle, SAgentBuilder
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.package.presets import BuiltinPackageFactory
from sagents.v2.testing.plugins.scripted_model import ScriptedModelProvider

SOURCE = '''
from sagents.v2.flow import FlowNodeResult
from sagents.v2.runtime.extensions import (
    ExtensionRegistration, ExtensionDescriptor, CapabilityOffer, ExtensionScope,
)
class Calculate:
    async def run(self, context):
        return FlowNodeResult(output={"meters": 2 * 1000})
registration = ExtensionRegistration(
    descriptor=ExtensionDescriptor(
        plugin_id="demo.calculate", version="1.0.0", name="Unit conversion",
        provides=(CapabilityOffer(capability="flow.node", api_version="2", name="calculate"),),
        supported_scopes=frozenset({ExtensionScope.AGENT}),
    ),
    factory=lambda context, dependencies: Calculate(),
    start=lambda node, context, dependencies: {"flow.node:calculate": node},
)
'''


async def demo(root):
    manifest = BuiltinPackageFactory.create(
        'assistant', package_id='demo.source', model='scripted',
    ).model_dump(mode='json')
    manifest['agents']['assistant']['entrypoint'] = {'type': 'flow', 'flow': 'main'}
    manifest['plugins'] = [{'id': 'demo.calculate', 'version': '1.0.0'}]
    manifest['runtime']['capabilities'] = {
        'flow.node': {'plugin': 'demo.calculate', 'name': 'calculate'},
    }
    manifest['flows'] = {'main': {
        'version': '1', 'start': 'calculate',
        'nodes': [{'id': 'calculate', 'type': 'tool', 'tool': 'calculate'},
                  {'id': 'end', 'type': 'end'}],
        'edges': [{'from': 'calculate', 'to': 'end'}],
    }}
    bundle = AgentPackageBundle.model_validate({
        'manifest': manifest, 'files': {'extensions/demo.calculate.py': SOURCE},
    })
    context = RequestContext(actor=ActorRef(
        principal_id='demo', principal_type=PrincipalType.USER,
    ))

    async def authorize(action, package, ctx):
        if ctx.actor != context.actor or package != bundle:
            raise PermissionError('outside the fixed demo grant')

    def build(package, session_root, ctx):
        return (SAgentBuilder().with_defaults(session_root=session_root)
                .with_model_provider(ScriptedModelProvider((step('unused'),))))

    service = AgentManagementService(
        root, builder_factory=build, authorize=authorize, allow_source_plugins=True,
    )
    try:
        saved = await service.save(bundle, context)
        await service.run(saved['ref'], 'assistant', 'Convert 2 km', 'conversion', context)
        async with asyncio.timeout(10):
            while True:
                result = await service.status('conversion', context)
                if result['terminal'] or result['needs_attention']:
                    break
                await asyncio.sleep(.01)
        assert result['flow_results']['calculate']['meters'] == 2000
        print(json.dumps(result['flow_results'], indent=2))
    finally:
        await service.close()


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='sage-source-plugin-') as directory:
        asyncio.run(demo(Path(directory)))

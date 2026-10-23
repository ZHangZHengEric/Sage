"""Local test host: real Desktop API/optimizer/MCP, with a scripted inference model.

No production catalog or model credentials are used. The scoring fixture is not
an official benchmark score; it verifies the imported scorer transport contract.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
from uuid import uuid4


def scorer_server():
    from mcp.server.fastmcp import FastMCP
    from sagents.v2.optimization import ScoringRequest, ScoringResult
    from sagents.v2.optimization.contracts import OptimizationGrade
    server = FastMCP('ContractScorer')
    @server.tool()
    async def score(request: dict) -> dict:
        parsed = ScoringRequest.model_validate(request)
        correct = parsed.observation.output.strip() == '42'
        return ScoringResult(grade=OptimizationGrade(score=.8 if correct else 0,
            passed=correct, rationale='Contract fixture partial-credit score'),
            details={'reference_available': parsed.case.reference_answer is not None}).model_dump(mode='json')
    server.run(transport='stdio')


async def serve(data_root, ready):
    import pytest
    import uvicorn
    import app.v2.desktop.backend.app as app_module
    from tests.app.v2.desktop.test_rsi import RsiModel, setup_service
    from sagents.v2.model.contracts import ModelEventKind, ModelResponse, ModelStreamEvent
    class DiagnosisModel(RsiModel):
        async def _stream(self, request):
            text = ''.join(getattr(b, 'text', '') for m in request.messages if m.role == 'user' for b in m.content)
            if '<user_request>' in text:
                text = text.split('<user_request>')[-1].rsplit('</user_request>', 1)[0].strip()
            try:
                props = json.loads(text).get('response_schema', {}).get('properties', {})
            except ValueError:
                props = {}
            answer = None
            if 'coverage' in props:
                answer = {'summary': 'Checked actual execution', 'findings': [], 'strengths': ['Answers arithmetic'],
                    'uncertainties': [], 'coverage': 'Complete contract fixture execution'}
            elif 'priorities' in props:
                answer = {'summary': 'Retain correct arithmetic', 'priorities': [], 'uncertainties': []}
            if answer is not None:
                self.requests.append(request)
                yield ModelStreamEvent(kind=ModelEventKind.COMPLETED, response=ModelResponse(
                    response_id='diagnosis', text=json.dumps(answer), finish_reason='stop'))
                return
            async for event in super()._stream(request):
                yield event
    patch = pytest.MonkeyPatch()
    service, agent_id = await setup_service(data_root, patch, DiagnosisModel())
    app_module.get_desktop_user_id = lambda request: 'alice'
    token = uuid4().hex
    app = app_module.create_app(service=service, auth_token=token)
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=0, log_level='error'))
    task = asyncio.create_task(server.serve())
    try:
        while not server.started:
            if task.done():
                await task
                raise RuntimeError('test host did not start')
            await asyncio.sleep(.05)
        port = server.servers[0].sockets[0].getsockname()[1]
        ready.write_text(json.dumps({'url': f'http://127.0.0.1:{port}', 'auth_token': token,
            'agent_id': agent_id, 'data_root': str(data_root), 'pid': os.getpid()}))
        ready.chmod(0o600)
        print(json.dumps({'ready': True, 'port': port, 'agent_id': agent_id}), flush=True)
        await task
    finally:
        server.should_exit = True
        await service.close()
        patch.undo()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scorer', action='store_true')
    parser.add_argument('--data-root', type=Path)
    parser.add_argument('--ready', type=Path)
    args = parser.parse_args()
    if args.scorer:
        scorer_server()
    else:
        args.data_root.mkdir(parents=True, exist_ok=True)
        asyncio.run(serve(args.data_root, args.ready))


if __name__ == '__main__':
    main()

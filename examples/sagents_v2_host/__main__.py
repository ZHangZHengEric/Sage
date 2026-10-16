"""Run with python -m examples.sagents_v2_host --offline (no API key/network)."""

import argparse
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
from uuid import uuid4

from sagents.v2 import ActorRef, RequestContext, StartRun
from sagents.v2.contracts.commands import InputItem
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import PrincipalType
from sagents.v2.model.contracts import ModelEventKind, ModelResponse, ModelStreamEvent
from sagents.v2.testing.plugins.scripted_model import (
    ScriptedModelProvider,
    ScriptedModelStep,
)

from .bootstrap import HostSettings, build_application


def offline_model() -> ScriptedModelProvider:
    return ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(
                    ModelStreamEvent(
                        kind=ModelEventKind.COMPLETED,
                        response=ModelResponse(
                            response_id="offline-response",
                            text="Hello from SAgents!",
                            finish_reason="stop",
                        ),
                    ),
                )
            ),
        )
    )


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", type=Path, default=Path(__file__).with_name("sage.yaml")
    )
    parser.add_argument(
        "--runtime-root", type=Path, default=Path(".runtime/host-starter")
    )
    parser.add_argument("--environment", default=None)
    parser.add_argument(
        "--log-level", choices=("debug", "info", "warning", "error"), default="info"
    )
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--prompt", default="Say hello!")
    parser.add_argument("--idempotency-key", default=None)
    return parser.parse_args()


async def main(args) -> None:
    settings = HostSettings(
        args.manifest, args.runtime_root, args.log_level, args.environment
    )
    app = await build_application(
        settings, model=offline_model() if args.offline else None
    )
    try:
        if args.inspect:
            print(
                json.dumps(
                    {
                        "plan": asdict(app.resolved_plan),
                        "readiness": app.resource_readiness,
                    },
                    indent=2,
                )
            )
            return
        context = RequestContext(
            actor=ActorRef(
                principal_id="local-developer",
                principal_type=PrincipalType.USER,
            )
        )
        agent = app.loaded_agents[0]
        command = StartRun(
            agent_id=agent.id,
            input=(InputItem(role="user", content=(TextBlock(text=args.prompt),)),),
            resolved_spec_hash=agent.composition_hash,
            idempotency_key=args.idempotency_key or str(uuid4()),
        )
        stream = await app.entrypoint().run_stream(command, context, agent=agent)
        async for event in stream.events:
            print(event.model_dump_json())
        result = await stream.wait()
        print(json.dumps({"state": result.state.value}))
    finally:
        await app.close()


if __name__ == "__main__":
    asyncio.run(main(arguments()))

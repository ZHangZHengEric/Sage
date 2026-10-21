"""Opt-in real-provider self-check/repair probe, with explicit numeric fault injection.

Uses credentials in the existing Desktop catalog in memory only. Writes synthetic
request/response fixtures and an audit report to --output, never modifies settings.
The existing completion Judge is counted separately from deterministic self-check.
"""

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from sagents.v2.model.provider import ModelProvider
    from typing import Any

from importlib.machinery import ModuleSpec
from importlib.abc import Loader

# ruff: noqa: E402 -- standalone CLI bootstraps the repository import path
import argparse
import asyncio
import json
import sys
import importlib.util
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
import httpx
from app.v2.desktop.backend.service import DesktopV2Service
from app.v2.desktop.backend.catalog import (
    DesktopAgentRecord,
    DesktopModelProviderRecord,
)
from app.v2.desktop.backend.openui import OpenUiParser, openui_blocks
from app.v2.desktop.backend.openui_completion import OpenUiOutputChecker
from sagents.v2.agent.policy.output_self_check import OutputSelfCheckPolicy
from sagents.v2.agent.policy.plugins.judge import (
    LLMContinuationJudge,
    LLMJudgeContinuationPolicy,
)
from sagents.v2.model import ModelMessage, ModelEventKind
from sagents.v2.contracts.items import TextBlock

spec = cast(ModuleSpec, importlib.util.spec_from_file_location(
    "loop_tests", REPO / "tests/sagents/v2/test_agent_loop_matrix.py"
))
m = importlib.util.module_from_spec(spec)
cast(Loader, spec.loader).exec_module(m)
cli = argparse.ArgumentParser(description=__doc__)
cli.add_argument("--output", type=Path, required=True)
cli.add_argument(
    "--model", help="Existing configured model name; defaults to Sage primary"
)
cli.add_argument(
    "--catalog", type=Path, default=Path.home() / "sage/runtime/desktop-catalog.json"
)
args = cli.parse_args()
OUT = args.output.resolve()
OUT.mkdir(parents=True, exist_ok=True)
BAD = '```openui\nroot = Stack([NumberInput("cups", "Cups", 100, 1, 1000, 1), Computed("Revenue", "divide", ["cups", 0])])\n```'
TASK = "Create a native OpenUI revenue calculator. NumberInput name cups, initial 100, min 1, max 1000; price is fixed at 25. A Computed labelled Revenue must update locally as cups * 25. No submit button. Output one complete openui block."


async def main():
    data = json.loads(args.catalog.read_text())
    agent = DesktopAgentRecord.model_validate(
        next(x for x in data["agents"] if x["agent_id"] == "sage")
    )
    provider = DesktopModelProviderRecord.model_validate(
        next(
            x
            for x in data["model_providers"]
            if (
                x["model"] == args.model
                if args.model
                else x["id"] == agent.config["llm_provider_id"]
            )
        )
    )
    service = DesktopV2Service(root=OUT / "isolated")
    real = await service._model_provider(provider, agent)
    calls = []
    wire = []
    checks = []
    phase = {"check": False}
    original_send = httpx.AsyncClient.send

    async def send(client, request, *args, **kwargs):
        if phase["check"]:
            raise AssertionError("Network request during deterministic self check")
        wire.append({"method": request.method, "phase": "model_or_host"})
        return await original_send(client, request, *args, **kwargs)

    setattr(httpx.AsyncClient, "send", send)

    class Model:
        def __init__(self, role):
            self.role = role

        def __getattr__(self, k):
            return getattr(real, k)

        async def stream(self, request):
            assert not phase["check"]
            idx = sum(c["role"] == self.role for c in calls)
            calls.append(
                {
                    "role": self.role,
                    "index": idx + 1,
                    "purpose": request.metadata.get("purpose"),
                }
            )
            print("MODEL", self.role, idx + 1, flush=True)
            if self.role == "author":
                messages = [
                    ModelMessage(
                        role="system",
                        content=(
                            TextBlock(
                                text=(
                                    REPO / "app/skills/sage-openui/SKILL.md"
                                ).read_text()
                                + "\n"
                                + (
                                    REPO
                                    / "app/v2/desktop/backend/openui_runtime/prompt.txt"
                                ).read_text()
                            ),
                        ),
                    )
                ]
                for msg in request.messages:
                    if msg.role == "user" and any(
                        getattr(b, "text", "") == "do task" for b in msg.content
                    ):
                        msg = msg.model_copy(
                            update={"content": (TextBlock(text=TASK),)}
                        )
                    messages.append(msg)
                request = request.model_copy(
                    update={"messages": tuple(messages), "tools": ()}
                )
                (OUT / f"author-request-{idx + 1}.json").write_text(
                    json.dumps(
                        request.model_dump(mode="json"), ensure_ascii=False, indent=2
                    )
                )
            async for event in real.stream(request):
                if event.kind == ModelEventKind.COMPLETED and self.role == "author":
                    (OUT / f"author-response-{idx + 1}.txt").write_text(
                        cast("Any", event.response).text
                    )
                    if idx == 0:
                        # Explicit test fault at the author-response boundary; never touches production.
                        event = event.model_copy(
                            update={
                                "response": cast("Any", event.response).model_copy(
                                    update={"text": BAD}
                                )
                            }
                        )
                yield event

    class Checker:
        async def check(self, context):
            before = (len(calls), len(wire))
            phase["check"] = True
            start = time.monotonic()
            try:
                r = await OpenUiOutputChecker(parser).check(context)
            finally:
                phase["check"] = False
            assert before == (len(calls), len(wire))
            checks.append(
                {
                    "step": context.step_number,
                    "errors": r.errors if r else [],
                    "model_calls": len(calls) - before[0],
                    "http_calls": len(wire) - before[1],
                    "duration_ms": round((time.monotonic() - start) * 1000, 2),
                }
            )
            print("CHECK", checks[-1], flush=True)
            if r and not r.errors:
                block = openui_blocks(context.response.text)[0]
                tree = await parser.parse(block["code"], complete=True)
                (OUT / "surface.json").write_text(
                    json.dumps(
                        {"complete": True, "tree": tree}, ensure_ascii=False, indent=2
                    )
                )
            return r

    parser = OpenUiParser()
    try:
        policy = OutputSelfCheckPolicy(
            LLMJudgeContinuationPolicy(LLMContinuationJudge(cast('ModelProvider', Model("completion_judge")))),
            Checker(),
        )
        runtime, handle, loop, executor = await m.setup_loop(
            Model("author"), tools=(), max_steps=4, continuation_policy=policy
        )
        result = await loop.execute(handle.run_id, m.CONTEXT)
        report = {
            "model": provider.model,
            "state": result.state.value,
            "fault_injection": "divide by zero inserted after first real author response",
            "model_requests": calls,
            "http_requests": len(wire),
            "checks": checks,
            "tools": len(executor.calls),
        }
        (OUT / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2)
        )
        print(json.dumps(report), flush=True)
        if result.state.value != "completed":
            (OUT / "runtime-events.json").write_text(
                json.dumps(
                    [
                        e.model_dump(mode="json")
                        for e in await runtime.session_store.read_events(handle.run_id)
                    ],
                    ensure_ascii=False,
                    indent=2,
                )
            )
        assert result.state.value == "completed"
        assert len(checks) >= 2 and checks[0]["errors"] and not checks[-1]["errors"]
    finally:
        httpx.AsyncClient.send = original_send
        await parser.close()
        if hasattr(service, "close"):
            await service.close()


if __name__ == "__main__":
    asyncio.run(main())

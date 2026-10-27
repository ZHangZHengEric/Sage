"""User-review stdio MCP access to the Desktop-owned RSI runtime.

No optimizer, writer, or model credentials are duplicated in this process.
Start Desktop first; its durable jobs survive MCP client disconnection.
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import quote
from uuid import uuid4

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import Field

from app.v2.desktop.backend.rsi import RsiApply, RsiStart
from app.v2.cli.rsi_visibility import review_view
from sagents.v2.optimization.contracts import (
    OptimizationStoppingPolicy,
)
from app.v2.desktop.backend.runtime_protocol import SIDECAR_PROTOCOL, SIDECAR_REVISION


def segment(value: str) -> str:
    if not value or value in {".", ".."}:
        raise ValueError("A nonempty identifier is required")
    return quote(value, safe="")


class DesktopBridge:
    def __init__(self, data_root: Path, *, transport=None):
        self.registry = (
            data_root.expanduser().resolve() / "runtime/desktop-v2-sidecar.json"
        )
        self.client_id = f"rsi-mcp-{uuid4().hex}"
        self.http = httpx.AsyncClient(timeout=60, trust_env=False, transport=transport)
        self.lock = asyncio.Lock()
        self.endpoint: str | None = None
        self.token: str | None = None
        self.heartbeat: asyncio.Task | None = None

    async def request(self, method: str, path: str, **kwargs):
        await self.connect()
        return await self._send(method, path, **kwargs)

    async def _send(self, method: str, path: str, **kwargs):
        try:
            response = await self.http.request(
                method,
                f"{self.endpoint}{path}",
                headers={"Authorization": f"Bearer {self.token}"},
                **kwargs,
            )
        except httpx.TransportError:
            # Never replay a mutation with an unknown outcome.
            raise RuntimeError(
                "Desktop connection lost. Do not repeat a mutation blindly; "
                "reconnect and inspect RSI history using the same request_id."
            ) from None
        if response.is_error:
            raise RuntimeError(
                f"Desktop API {response.status_code}: request failed; inspect details in Desktop"
            )
        value = response.json()
        if value.get("code") != 0:
            raise RuntimeError("Desktop API rejected the request")
        return value["data"]

    async def connect(self):
        async with self.lock:
            if self.endpoint is not None:
                return
            try:
                registry = json.loads(self.registry.read_text())
            except (OSError, ValueError):
                raise RuntimeError("Start Sage Desktop before using RSI MCP.") from None
            if (
                registry.get("protocol") != SIDECAR_PROTOCOL
                or registry.get("revision") != SIDECAR_REVISION
            ):
                raise RuntimeError(
                    f"Desktop runtime protocol mismatch; start the matching Sage Desktop build (revision {SIDECAR_REVISION})."
                )
            host = registry.get("host", "")
            try:
                address = ipaddress.ip_address(host)
            except ValueError:
                raise RuntimeError("Invalid Desktop loopback registry") from None
            port = registry.get("port")
            token = registry.get("auth_token")
            if (
                not address.is_loopback
                or address.version != 4
                or type(port) is not int
                or not 0 < port < 65536
                or not isinstance(token, str)
                or not token
            ):
                raise RuntimeError("Invalid Desktop loopback registry")
            self.endpoint = f"http://{host}:{port}"
            self.token = token
            try:
                health = await self._send("GET", "/health")
                if (
                    health.get("protocol") != SIDECAR_PROTOCOL
                    or health.get("revision") != SIDECAR_REVISION
                    or health.get("build_id") != registry.get("build_id")
                ):
                    raise RuntimeError("Desktop identity changed; reconnect MCP.")
                lease = await self._send(
                    "PUT", f"/api/v2/runtime/clients/{self.client_id}"
                )
            except BaseException:
                self.endpoint = self.token = None
                raise
            self.heartbeat = asyncio.create_task(
                self._renew(lease["lease_ttl_seconds"])
            )

    async def _renew(self, ttl):
        try:
            while True:
                await asyncio.sleep(max(1, ttl / 3))
                await self._send("PUT", f"/api/v2/runtime/clients/{self.client_id}")
        except (RuntimeError, httpx.HTTPError):
            # Force a fresh registry handshake for the next call, without replay.
            self.endpoint = self.token = None

    async def close(self):
        if self.heartbeat:
            self.heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await self.heartbeat
        try:
            if self.endpoint:
                with suppress(Exception):
                    await self._send(
                        "DELETE", f"/api/v2/runtime/clients/{self.client_id}"
                    )
        finally:
            await self.http.aclose()


def _score_summary(result):
    report = result.get("report", {})

    def mean(evaluation, split):
        grades = [
            case.get("grade", {}).get("score") for case in evaluation.get("cases", [])
            if case.get("case", {}).get("split") == split
        ]
        grades = [score for score in grades if isinstance(score, (int, float))]
        return sum(grades) / len(grades) if grades else None

    return {
        "improved": report.get("improved"),
        "termination": report.get("termination"),
        "goal_verified": report.get("goal_verified"),
        "baseline_training": mean(report.get("baseline", {}), "training"),
        "selected_training": mean(report.get("selected", {}), "training"),
        "baseline_validation": mean(report.get("baseline", {}), "validation"),
        "selected_validation": mean(report.get("selected", {}), "validation"),
    }


def _compact(value):
    """Keep polling bounded; full package/evidence is an explicit version read."""
    if isinstance(value, list):
        return [_compact(item) for item in value]
    if not isinstance(value, dict):
        if isinstance(value, str) and len(value) > 4096:
            return (
                value[:4096] + "\n[truncated; use include_details=true or rsi_version]"
            )
        return value
    compact = {}
    for key, child in value.items():
        if key in {"evidence", "agent_calls", "internal_agents", "call", "tuner_call"}:
            compact[key] = {"omitted": True}
        elif (
            key.endswith("package") and isinstance(child, dict) and "manifest" in child
        ):
            manifest = child["manifest"]
            compact[key] = {
                "metadata": manifest.get("metadata"),
                "agents": {
                    name: {
                        "tools": agent.get("tools", []),
                        "skills": agent.get("skills", []),
                    }
                    for name, agent in manifest.get("agents", {}).items()
                },
            }
        elif key == "result" and isinstance(child, dict) and "report" in child:
            compact[key] = _score_summary(child)
        else:
            compact[key] = _compact(child)
    return compact


def create_server(data_root: Path, *, bridge: DesktopBridge | None = None) -> FastMCP:
    bridge = bridge or DesktopBridge(data_root)

    @asynccontextmanager
    async def lifespan(server):
        try:
            yield
        finally:
            await bridge.close()

    server = FastMCP(
        "Sage RSI",
        lifespan=lifespan,
        instructions=(
            "Optimize existing Sage Desktop agents with real evaluations. "
            "Start returns a durable run ID; poll incrementally with after_sequence. "
            "Reuse request_id for the same intent. Never claim an interim score "
            "is a final success. This is a user-review interface, not an internal tuner input: train/dev scores, executions and diagnoses are visible; "
            "test evidence is human-only and never returned by these tools, even with include_details. "
            "Applying a version requires explicit user approval."
        ),
    )

    def base(agent_id):
        return f"/api/v2/agents/{segment(agent_id)}/rsi"

    @server.tool()
    async def rsi_agents() -> dict:
        """List available agents, without returning their model credentials or config."""
        value = await bridge.request("GET", "/api/v2/agents")
        agents = value if isinstance(value, list) else value.get("agents", [])
        return {"agents": [{k: a[k] for k in ("id", "name") if k in a} for a in agents]}

    @server.tool()
    async def rsi_start(
        agent_id: str,
        goal: str,
        request_id: str,
        rounds: Annotated[int, Field(ge=1, le=100)] = 8,
        validation_case_count: Annotated[int, Field(ge=1, le=100)] = 24,
        max_concurrency: Annotated[int, Field(ge=1, le=16)] = 3,
        evaluation_repeats: Annotated[int, Field(ge=1, le=10)] = 1,
        evaluation_aggregation: Literal["minimum", "mean"] = "minimum",
        builtin_scoring: Literal["quality", "quality_cost", "quality_latency", "quality_tokens"] = "quality",
        refresh_incumbent: bool = False,
        human_test_count: Annotated[int, Field(ge=0, le=100)] = 12,
        optimization_scope: list[Literal["instructions", "skills", "tools"]]
        | None = None,
        model_provider_id: str | None = None,
        user_simulator_instructions: str | None = None,
        user_simulator_id: str | None = None,
        target_score: Annotated[float, Field(gt=0, le=1)] = 0.95,
        patience: Annotated[int, Field(ge=1, le=100)] = 3,
        stability_passes: Annotated[int, Field(ge=2, le=5)] = 2,
    ) -> dict:
        """Start a durable real RSI job. Same request_id deduplicates the same request.

        Costs model calls. Returns immediately. Does not apply the candidate to the agent.
        """
        request = RsiStart(
            goal=goal,
            request_id=request_id,
            human_test_count=human_test_count,
            rounds=rounds,
            validation_case_count=validation_case_count,
            max_concurrency=max_concurrency,
            evaluation_repeats=evaluation_repeats,
            evaluation_aggregation=evaluation_aggregation,
            builtin_scoring={"mode": builtin_scoring},
            refresh_incumbent=refresh_incumbent,
            optimization_scope=tuple(
                ["instructions"] if optimization_scope is None else optimization_scope
            ),
            model_provider_id=model_provider_id,
            user_simulator_instructions=user_simulator_instructions,
            user_simulator_id=user_simulator_id,
            stopping_policy=OptimizationStoppingPolicy(
                target_score=target_score,
                patience=patience,
                stability_passes=stability_passes,
            ),
        )
        return review_view(await bridge.request(
            "POST", base(agent_id), json=request.model_dump(mode="json")
        ))

    @server.tool()
    async def rsi_history(agent_id: str) -> dict:
        """Read durable runs, candidate versions and current configuration fingerprint."""
        return review_view(await bridge.request("GET", base(agent_id)))

    @server.tool()
    async def rsi_status(
        agent_id: str,
        run_id: str,
        after_sequence: Annotated[int, Field(ge=0)] = 0,
        limit: Annotated[int, Field(ge=1, le=200)] = 50,
        include_details: bool = False,
    ) -> dict:
        """Read real conversation/evaluation events. Advance using next_sequence.

        Defaults to 50 compact events; include_details returns train/dev evidence and packages.
        User review includes train/dev scores, executions and diagnoses, plus selection metrics.
        Test stays hidden in every mode; raw mixed-split calls are not returned.

        Status may already be terminal while older events still need pagination.
        """
        value = await bridge.request(
            "GET",
            f"{base(agent_id)}/runs/{segment(run_id)}",
            params={"after_sequence": after_sequence},
        )
        value["events"] = value.get("events", [])[:limit]
        value["next_sequence"] = max(
            [after_sequence] + [e["sequence"] for e in value["events"]]
        )
        value = review_view(value)
        if include_details:
            return value
        result = value.pop("result", None)
        value.pop("iterations", None)
        if result:
            value["scores"] = _score_summary(result)
        return _compact(value)

    @server.tool()
    async def rsi_questions(agent_id: str, run_id: str) -> dict:
        """Read train/dev questions for user review; all test data stays hidden."""
        cursor = 0
        cases = []
        suite = None
        validation_count = 0
        while True:
            page = await rsi_status(
                agent_id, run_id, cursor, limit=200, include_details=True
            )
            events = page.get("events", [])
            for event in events:
                data = event["data"]
                if event["event"] == "test_generation_batch_completed":
                    cases.extend(data.get("cases", []))
                    validation_count += data.get("validation_count", 0)
                elif event["event"] == "suite_fixed":
                    suite = data.get("suite")
                    validation_count = (suite or {}).get("validation_count", validation_count)
                elif event["event"] == "training_cases_added":
                    cases.extend(data.get("cases", []))
            if not events or len(events) < 200:
                break
            cursor = page["next_sequence"]
        combined = {c["id"]: c for c in ((suite or {}).get("cases", []) + cases)}
        return {
            "training": [c for c in combined.values() if c["split"] == "training"],
            "validation": {"total": validation_count, "questions_visible": True,
                           "cases": [c for c in combined.values() if c["split"] == "validation"]},
        }

    @server.tool()
    async def rsi_resume(agent_id: str, run_id: str) -> dict:
        """Resume the same interrupted local experiment with verified frozen settings and saved evidence."""
        return review_view(await bridge.request(
            "POST", f"{base(agent_id)}/runs/{segment(run_id)}/resume"
        ))

    @server.tool()
    async def rsi_cancel(agent_id: str, run_id: str) -> dict:
        """Cancel a specified job; queued cases stop and active conversations are drained."""
        return review_view(await bridge.request(
            "POST", f"{base(agent_id)}/runs/{segment(run_id)}/cancel"
        ))

    @server.tool()
    async def rsi_version(agent_id: str, version_id: str) -> dict:
        """Review a package, train/dev evidence, diagnoses and retention status before applying."""
        return review_view(await bridge.request(
            "GET", f"{base(agent_id)}/versions/{segment(version_id)}"
        ))

    @server.tool()
    async def rsi_apply(
        agent_id: str,
        version_id: str,
        expected_fingerprint: str,
        confirmed: Literal[True],
    ) -> dict:
        """Apply a reviewed version only with explicit user approval and current fingerprint.

        A stale fingerprint fails instead of overwriting a changed agent.
        """
        request = RsiApply(
            confirmed=confirmed, expected_fingerprint=expected_fingerprint
        )
        return review_view(await bridge.request(
            "POST",
            f"{base(agent_id)}/versions/{segment(version_id)}/apply",
            json=request.model_dump(mode="json"),
        ))

    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path.home() / "sage")
    args = parser.parse_args(argv)
    create_server(args.data_root).run(transport="stdio")


if __name__ == "__main__":
    main()

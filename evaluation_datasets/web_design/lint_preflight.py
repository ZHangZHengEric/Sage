"""Validate native lint tools inside the same policy as an RSI target; no models."""

import asyncio
import hashlib
import json
from pathlib import Path
import tempfile

from app.v2.desktop.backend.rsi_lint import default_lint_environment, lint_binding
from sagents.v2.contracts.principals import ActorRef, RequestContext
from sagents.v2.runtime.execution.sandbox import (
    FileOperation,
    FileSystemPolicy,
    LocalWorkspaceSandboxProvider,
    NetworkPolicy,
    ProcessPolicy,
    ResolvedSandboxSpec,
    ResourceLimits,
    SandboxGrantIssuer,
)
from sagents.v2.tool import ToolCall
from sagents.v2.tool.official import OfficialToolRuntime
from sagents.v2.tool.plugins.official import OfficialToolPlugin


async def main():
    root = Path(__file__).resolve().parent
    env = default_lint_environment()
    fingerprint = env.fingerprint()
    config, process = lint_binding(env, target=True, tools=["read_lints"])
    issuer = SandboxGrantIssuer()
    provider = LocalWorkspaceSandboxProvider(issuer.verification_key, **config)
    context = RequestContext(
        actor=ActorRef(principal_id="preflight", principal_type="user")
    )
    with tempfile.TemporaryDirectory(prefix="sage-lint-preflight-") as name:
        workspace = Path(name)
        (workspace / "index.html").write_text(
            "<!doctype html><title>Test</title><p>OK</p>"
        )
        (workspace / "style.css").write_text("body{color:red}")
        (workspace / "app.js").write_text(
            "const twice = (x) => x * 2; console.log(twice(2));"
        )
        digest = "sha256:" + hashlib.sha256(name.encode()).hexdigest()
        handle = await provider.provision(
            ResolvedSandboxSpec(
                resources=ResourceLimits(require_hard_limits=False),
                spec_hash=digest,
                architecture="native",
                filesystem=FileSystemPolicy(
                    allowed_operations=frozenset(FileOperation)
                ),
                process=ProcessPolicy.model_validate(process),
                network=NetworkPolicy(),
                policy_hash=digest,
                metadata={"host_workspace": name},
            ),
            context,
            run_id="lint-preflight",
        )
        plugin = OfficialToolPlugin(OfficialToolRuntime(handle, issuer))

        async def check(index):
            result = await plugin.executor.execute(
                ToolCall(
                    tool_call_id=f"lint-{index}",
                    tool_name="read_lints",
                    operation_id=f"op-{index}",
                    idempotency_key=f"lint-{index}",
                    owner_run_id="lint-preflight",
                    arguments={"paths": ["index.html", "style.css", "app.js"]},
                ),
                context,
            )
            if result.error:
                raise RuntimeError(result.error.message)
            return result.content[0].value

        try:
            valid = await check(1)
            if valid["passed"] is not True:
                task_id = valid["linters"].get("eslint", {}).get("task_id")
                detail = await plugin.runtime._job_output(task_id) if task_id else ""
                raise RuntimeError(
                    "Valid fixtures did not pass: " + json.dumps(valid) + " " + detail
                )
            (workspace / "app.js").write_text("const broken = ;")
            (workspace / "style.css").write_text("body { color:red;")
            (workspace / "index.html").write_text(
                "<!doctype html><title>Test</title><div><span>x</div>"
            )
            invalid = await check(2)
            assert invalid["passed"] is False and invalid["status"] == "completed"
            assert {d["source"] for d in invalid["diagnostics"]} >= {
                "eslint",
                "html5",
                "css-syntax",
            }
        finally:
            await plugin.executor.release_run("lint-preflight")
            await handle.destroy()
    runtime = root / ".runtime"
    runtime.mkdir(exist_ok=True)
    settings = json.loads((root / "experiment.settings.json").read_text())
    settings["lint_environment"] = env.model_dump()
    (runtime / "experiment.settings.local.json").write_text(
        json.dumps(settings, indent=2) + "\n"
    )
    report = {
        "ready": True,
        "model_calls": 0,
        "network": "none",
        "valid": valid,
        "invalid": invalid,
        "lint_environment": env.model_dump(),
        "fingerprint": fingerprint,
    }
    (runtime / "lint-preflight.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "ready": True,
                "valid_passed": valid["passed"],
                "invalid_passed": invalid["passed"],
                "checked": ["JavaScript", "HTML", "CSS"],
                "model_calls": 0,
                "settings": str(runtime / "experiment.settings.local.json"),
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())

"""Offline acceptance through registered plugins and standard SDK execution.

Run in the candidate image: python deploy/images/frontend-test/acceptance.py
Nonzero exit means acceptance failed, including a Chromium policy rejection.
Artifacts are retained under the printed temporary workspace for inspection.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
import shlex

from app.v2.server.runtime.sdk_plugins import SERVER_PROCESS_DEFAULTS
from sagents.v2 import SAgentBuilder
from sagents.v2.package.presets import BuiltinPackageFactory
from sagents.v2.testing.plugins.scripted_model import ScriptedModelProvider
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.agent.policy import ApprovalStrategy, DefaultToolPolicy
from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.items import TextBlock
from sagents.v2.model.contracts import ModelResponse, ModelStreamEvent, ModelToolCall
from sagents.v2.runtime.extensions import CapabilityOffer, ExtensionDescriptor, ExtensionRegistration, ExtensionScope
from sagents.v2.testing.plugins.scripted_model import ScriptedModelStep

PAGE = """<!doctype html><meta charset="utf-8">
<style>body{font:32px 'Noto Sans CJK SC',sans-serif;background:white;color:black}</style>
<h1>中文页面测试</h1><input aria-label="姓名"><button>确认</button><p id="result">待操作</p>
<script>document.querySelector('button').onclick=()=>{
 document.querySelector('#result').textContent='你好，'+document.querySelector('input').value;
};</script>"""
JSDOM = """module.exports = async ({JSDOM, assert, require, workspace}) => {
 const dom = new JSDOM(require('node:fs').readFileSync(workspace+'/.sage-tests/page.html','utf8'), {runScripts:'dangerously'});
 try {
  dom.window.document.querySelector('input').value='沙箱';
  dom.window.document.querySelector('button').click();
  assert.equal(dom.window.document.querySelector('#result').textContent,'你好，沙箱');
 } finally { dom.window.close(); }
};"""
PLAYWRIGHT = """module.exports = async ({launch, assert, artifacts, pathToFileURL, workspace}) => {
 const browser = await launch();
 const page = await browser.newPage();
 await page.goto(pathToFileURL(workspace+'/.sage-tests/page.html').href);
 await page.getByLabel('姓名').fill('沙箱');
 await page.getByRole('button', {name:'确认'}).click();
 assert.equal(await page.locator('#result').textContent(),'你好，沙箱');
 await page.evaluate(() => document.fonts.ready);
 await page.screenshot({path:artifacts+'/chinese.png', fullPage:true});
};"""
# Numeric IPs avoid treating a missing DNS configuration as proof of isolation.
OFFLINE = """import socket, ctypes, errno
for family, address in [(socket.AF_INET, ('1.1.1.1',443)),
                        (socket.AF_INET6, ('2606:4700:4700::1111',443,0,0))]:
 try:
  with socket.socket(family, socket.SOCK_STREAM) as s:
   s.settimeout(2)
   s.connect(address)
 except OSError as e:
  print(f'{family}: denied: {e}')
 else:
  raise AssertionError('External network unexpectedly available')
libc = ctypes.CDLL(None, use_errno=True)
assert libc.unshare(0x10000000) == -1
assert ctypes.get_errno() == errno.EPERM
print('CLONE_NEWUSER: denied: EPERM')
"""

RUNTIME = """const fs=require('node:fs'), assert=require('node:assert/strict');
const {execFileSync}=require('node:child_process');
assert.notEqual(process.getuid(),0);
const ignoredStdio=require('node:child_process').spawnSync(process.execPath,['-e',''],{stdio:'ignore'});
assert.ifError(ignoredStdio.error);
assert.equal(ignoredStdio.status,0);
const browser=require('playwright').chromium.executablePath();
fs.accessSync(browser,fs.constants.R_OK|fs.constants.X_OK);
fs.accessSync(process.env.FONTCONFIG_FILE,fs.constants.R_OK);
const font=execFileSync('fc-match',['-f','%{family}','Noto Sans CJK SC'],{encoding:'utf8'});
assert.match(font,/Noto Sans CJK SC/);
console.log(JSON.stringify({uid:process.getuid(), node:process.version,
 npm:require('/usr/local/lib/node_modules/npm/package.json').version,
 jsdom:require('jsdom/package.json').version, playwright:require('playwright/package.json').version,
 browser, fonts:font, NODE_PATH:process.env.NODE_PATH,
 PLAYWRIGHT_BROWSERS_PATH:process.env.PLAYWRIGHT_BROWSERS_PATH,
 FONTCONFIG_FILE:process.env.FONTCONFIG_FILE,
 isolation:fs.readFileSync('/proc/self/status','utf8').split('\\n').filter(line=>/^(Uid|Gid|CapEff|NoNewPrivs|Seccomp):/.test(line)),
 namespaces:{net:fs.readlinkSync('/proc/self/ns/net'),pid:fs.readlinkSync('/proc/self/ns/pid')}
}));
"""


async def main():
    parent = Path(tempfile.mkdtemp(prefix="sage-frontend-acceptance-"))
    parent.chmod(0o755)
    workspace = parent / "workspace"
    workspace.mkdir()
    uid = int(os.environ.get("SAGE_SERVER_LINUX_EXECUTION_UID", os.geteuid()))
    gid = int(os.environ.get("SAGE_SERVER_LINUX_EXECUTION_GID", os.getegid()))
    if os.geteuid() == 0:
        os.chown(workspace, uid, gid)
    operations = [
        ("fixture-" + name, "file_write", {"file_path": ".sage-tests/" + name, "content": content})
        for name, content in {"page.html": PAGE, "dom.cjs": JSDOM, "browser.cjs": PLAYWRIGHT}.items()
    ]
    # /tmp is workspace-owned scratch storage on Linux, so it is not an escape.
    operations.append(("file_api_boundary", "file_write", {"file_path": "/etc/sage-frontend-outside.txt", "content": "forbidden"}))
    for name, argv in {
        "runtime": ("node", "-e", RUNTIME),
        "offline": ("python", "-c", OFFLINE),
        "jsdom": ("sage-frontend-test", "jsdom", ".sage-tests/dom.cjs"),
        "playwright": ("sage-frontend-test", "playwright", ".sage-tests/browser.cjs"),
    }.items():
        operations.append((name, "execute_shell_command", {
            "command": shlex.join(argv), "block_until_ms": 120000,
        }))
    steps = tuple(ScriptedModelStep(events=(ModelStreamEvent(kind="completed", response=ModelResponse(
        response_id="response-" + name, finish_reason="tool_calls",
        tool_calls=(ModelToolCall(tool_call_id=name, name=tool, arguments=arguments),),
    )),)) for name, tool, arguments in operations)
    model = ScriptedModelProvider((*steps, ScriptedModelStep(events=(ModelStreamEvent(
        kind="completed", response=ModelResponse(response_id="done", text="Finished", finish_reason="stop")),))))

    def registration(plugin, capability, value):
        return ExtensionRegistration(descriptor=ExtensionDescriptor(
            plugin_id=plugin, name=plugin, version="1",
            provides=(CapabilityOffer(capability=capability, api_version="2"),),
            supported_scopes=frozenset({ExtensionScope.AGENT}),
            config_schema={"type": "object", "additionalProperties": False},
        ), factory=lambda context, dependencies: value, ownership="borrowed")

    builder = SAgentBuilder()
    builder.register(registration("acceptance.model", "model.provider", model))
    builder.register(registration("acceptance.policy", "agent.tool-policy", DefaultToolPolicy(approval_strategy=ApprovalStrategy.AUTO_APPROVE)))
    application = await builder.build(runtime={
        "state_root": str(parent / "runtime"),
        "capabilities": {
            "session.store": {"plugin": "sage.session.filesystem", "config": {"root": str(parent / "sessions")}},
            "model.provider": {"plugin": "acceptance.model"},
            "agent.tool-policy": {"plugin": "acceptance.policy"},
            "agent.continuation-policy": {"plugin": "sage.agent.continuation.deterministic"},
            "tool.selection-policy": {"plugin": "sage.tool-selection.direct"},
            "tool.catalog": {"plugin": "sage.tool.official"},
            "execution.binding": {"plugin": "sage.execution.binding.local-workspace", "config": {
                "workspace": str(workspace), "workspace_alias": "/workspace",
                "linux_execution_uid": uid, "linux_execution_gid": gid,
                "policy": {"process": {**SERVER_PROCESS_DEFAULTS, "max_wall_time_seconds": 60}},
            }},
        },
    }, models={"models": {"primary": {"provider": "openai-chat-completions", "model": "offline"}}})
    context = RequestContext(actor=ActorRef(principal_id="frontend_acceptance", principal_type=PrincipalType.USER))
    summary = {"workspace": str(workspace), "network": "none", "checks": {}}
    try:
        package = BuiltinPackageFactory.create("assistant", package_id="frontend.acceptance")
        agent_id = package.entrypoint.agent
        definition = package.agents[agent_id]
        package = package.model_copy(update={"agents": {agent_id: definition.model_copy(update={
            "tools": ("file_write", "execute_shell_command"),
        })}})
        agent = await application.load_agent(package)
        stream = await application.entrypoint().run_stream(StartRun(
            agent_id=agent.id, resolved_spec_hash=agent.composition_hash,
            input=(InputItem(role="user", content=(TextBlock(text="Run offline frontend checks"),)),),
            idempotency_key="frontend-acceptance",
        ), context, agent=agent)
        receipts = {}
        async for event in stream.events:
            item = getattr(event.data, "item", None)
            if event.type == "item.completed" and item is not None and item.data.kind == "tool_result":
                receipts[item.data.tool_call_id] = item.data.model_dump(mode="json")
        run = await stream.wait()
        summary["run_id"] = run.run_id
        summary["state"] = run.state.value
        summary["diagnostics"] = await application.execution_diagnostics(run.run_id, context)
        for name, _, _ in operations:
            receipt = receipts.get(name)
            if name.startswith("fixture-"):
                if not receipt or receipt.get("error"):
                    raise RuntimeError(f"fixture failed: {name}: {receipt}")
                continue
            if name == "file_api_boundary":
                summary["checks"][name] = {"passed": bool(receipt and (receipt.get("error") or {}).get("code") == "sandbox.permission_denied"), "receipt": receipt}
            else:
                payload = {}
                if receipt:
                    for block in receipt.get("content", []):
                        if block.get("kind") == "json":
                            payload = block["value"]
                summary["checks"][name] = {
                    "passed": bool(receipt and not receipt.get("error") and payload.get("success")
                                   and payload.get("exit_code") == 0), "result": payload, "receipt": receipt,
                }
        if run.state.value != "completed":
            raise RuntimeError(f"acceptance Run did not complete: {run.state.value}")
    except Exception as error:
        summary["error"] = f"{type(error).__name__}: {error}"
    finally:
        await application.close()
    (parent / "acceptance.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2)
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return (
        0
        if "error" not in summary and len(summary["checks"]) == 5
        and all(c["passed"] for c in summary["checks"].values())
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

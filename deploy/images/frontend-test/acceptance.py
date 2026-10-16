"""Offline acceptance through the Server v2 provisioning and signed-grant path.

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
from types import SimpleNamespace

from app.v2.server.runtime.official import install_sandbox, provision_workspace
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.runtime.execution.sandbox import OperationIntent, ProcessRequest

PAGE = """<!doctype html><meta charset="utf-8">
<style>body{font:32px 'Noto Sans CJK SC',sans-serif;background:white;color:black}</style>
<h1>中文页面测试</h1><input aria-label="姓名"><button>确认</button><p id="result">待操作</p>
<script>document.querySelector('button').onclick=()=>{
 document.querySelector('#result').textContent='你好，'+document.querySelector('input').value;
};</script>"""
JSDOM = """module.exports = async ({JSDOM, assert, require}) => {
 const dom = new JSDOM(require('node:fs').readFileSync('/workspace/.sage-tests/page.html','utf8'), {runScripts:'dangerously'});
 try {
  dom.window.document.querySelector('input').value='沙箱';
  dom.window.document.querySelector('button').click();
  assert.equal(dom.window.document.querySelector('#result').textContent,'你好，沙箱');
 } finally { dom.window.close(); }
};"""
PLAYWRIGHT = """module.exports = async ({launch, assert, artifacts, pathToFileURL}) => {
 const browser = await launch();
 const page = await browser.newPage();
 await page.goto(pathToFileURL('/workspace/.sage-tests/page.html').href);
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
    execution = SimpleNamespace(sandbox_grant_issuer=None)
    install_sandbox(
        execution, SimpleNamespace(linux_execution_uid=uid, linux_execution_gid=gid)
    )
    context = RequestContext(
        actor=ActorRef(
            principal_id="frontend_acceptance", principal_type=PrincipalType.USER
        )
    )
    summary = {"workspace": str(workspace), "network": "none", "checks": {}}
    handle = None
    try:
        handle = await provision_workspace(
            execution, workspace, context, run_id="frontend_acceptance"
        )

        def authorize(operation, **fields):
            intent = OperationIntent(
                operation=operation,
                run_id="frontend_acceptance",
                tool_call_id="acceptance",
                sandbox_id=handle.ref.sandbox_id,
                **fields,
            )
            grant = execution.sandbox_grant_issuer.issue(
                ref=handle.ref, intent=intent, allowed_operations=frozenset({operation})
            )
            return intent, grant

        for name, content in {
            "page.html": PAGE,
            "dom.cjs": JSDOM,
            "browser.cjs": PLAYWRIGHT,
        }.items():
            target = f"/workspace/.sage-tests/{name}"
            intent, grant = authorize("create", path=target)
            await handle.filesystem.write_bytes(
                target, content.encode(), intent=intent, grant=grant
            )
        # A negative file API check ensures the runner's /tmp is not exposed to file tools.
        try:
            intent, grant = authorize("write", path="/tmp/outside.txt")
            await handle.filesystem.write_bytes(
                "/tmp/outside.txt", b"forbidden", intent=intent, grant=grant
            )
        except (ValueError, PermissionError) as error:
            summary["checks"]["file_api_boundary"] = {
                "passed": True,
                "error": str(error),
            }
        else:
            summary["checks"]["file_api_boundary"] = {"passed": False}

        for name, argv in {
            "runtime": ("node", "-e", RUNTIME),
            "offline": ("python", "-c", OFFLINE),
            "jsdom": ("sage-frontend-test", "jsdom", "/workspace/.sage-tests/dom.cjs"),
            "playwright": (
                "sage-frontend-test",
                "playwright",
                "/workspace/.sage-tests/browser.cjs",
            ),
        }.items():
            request = ProcessRequest(argv=argv, cwd="/workspace", timeout_seconds=60)
            intent, grant = authorize(
                "process.run",
                executable=argv[0],
                argv=argv,
                path=request.cwd,
                metadata={"process_request_digest": request.digest()},
            )
            result = await handle.process.run(request, intent=intent, grant=grant)
            summary["checks"][name] = {
                "passed": result.exit_code == 0
                and not result.timed_out
                and not result.truncated,
                "exit_code": result.exit_code,
                "stdout": result.stdout.decode(errors="replace"),
                "stderr": result.stderr.decode(errors="replace"),
            }
    except Exception as error:
        summary["error"] = f"{type(error).__name__}: {error}"
    finally:
        if handle is not None:
            await handle.destroy()
    (parent / "acceptance.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2)
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return (
        0
        if len(summary["checks"]) == 5
        and all(c["passed"] for c in summary["checks"].values())
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

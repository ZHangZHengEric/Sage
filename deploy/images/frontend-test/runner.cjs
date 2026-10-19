#!/usr/bin/env node
'use strict';
// A script exports async ({ require, assert, JSDOM?, launch?, artifacts, tmp }) => {}.
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const assert = require('node:assert/strict');

function inside(root, value) {
  const relative = path.relative(root, value);
  return relative !== '' && relative !== '..' && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative);
}

function workspacePath(root, value) {
  const resolved = fs.realpathSync(path.resolve(root, value));
  if (!inside(root, resolved)) throw new Error(`Test paths must be inside ${root}`);
  return resolved;
}

async function main() {
  const [mode, script] = process.argv.slice(2);
  if (!['jsdom', 'playwright'].includes(mode) || !script || process.argv.length !== 4) {
    throw new Error('Usage: sage-frontend-test jsdom|playwright .sage-tests/name.cjs (relative to SAGE_WORKSPACE_ROOT)');
  }
  // Sage supplies the process-visible root, independent of a tool's workdir.
  // Standalone callers without Sage must launch from their workspace root.
  const configuredRoot = process.env.SAGE_WORKSPACE_ROOT || process.cwd();
  if (!path.isAbsolute(configuredRoot)) throw new Error('SAGE_WORKSPACE_ROOT must be absolute');
  const workspace = fs.realpathSync(configuredRoot);
  const testRoot = path.join(workspace, '.sage-tests');
  if (workspacePath(workspace, testRoot) !== testRoot) throw new Error('Test directory must not be a symlink');
  const source = workspacePath(workspace, script);
  if (!inside(testRoot, source) || !source.endsWith('.cjs')) throw new Error(`Use a .cjs script in ${testRoot} exporting an async function`);
  const artifactRoot = path.join(testRoot, 'artifacts');
  fs.mkdirSync(artifactRoot, { recursive: true });
  if (workspacePath(workspace, artifactRoot) !== artifactRoot) throw new Error('Artifact directory must not be a symlink');
  const artifacts = fs.mkdtempSync(path.join(artifactRoot, `${mode}-`));
  const tmp = fs.mkdtempSync('/tmp/sage-frontend-');
  const browsers = [];
  const started = Date.now();
  let failure;
  let failed = false;
  try {
    process.env.TMPDIR = tmp;
    process.env.HOME = tmp;
    process.env.XDG_CACHE_HOME = path.join(tmp, 'cache');
    process.chdir(path.dirname(source));
    const context = { require, assert, workspace, artifacts, tmp, pathToFileURL };
    if (mode === 'jsdom') context.JSDOM = require('jsdom').JSDOM;
    else context.launch = async () => {
      // Keep Chromium's sandbox enabled. Never retry with --no-sandbox or
      // --single-process when the provider denies namespaces or sockets.
      const browser = await require('playwright').chromium.launch({
        headless: true, chromiumSandbox: true, timeout: 20000,
        args: ['--disable-dev-shm-usage'],
      });
      browsers.push(browser);
      return browser;
    };
    const run = require(source);
    if (typeof run !== 'function') throw new Error('Test must export a function');
    await run(context);
  } catch (error) {
    failed = true;
    failure = error;
  } finally {
    await Promise.allSettled(browsers.map(browser => browser.close()));
    fs.rmSync(tmp, { recursive: true, force: true });
    const report = { mode, workspace, script: source, status: failed ? 'failed' : 'passed',
      durationMs: Date.now() - started, artifacts, error: failed ? (failure?.stack ?? String(failure)) : undefined };
    fs.writeFileSync(path.join(artifacts, 'report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report));
  }
  if (failed) process.exitCode = 1;
}
main().catch(error => {
  console.error(JSON.stringify({ status: 'failed', error: error.stack ?? String(error) }));
  process.exitCode = 1;
});

---
layout: default
title: Cube workspace and execution
parent: Architecture
nav_order: 16
lang: en
ref: v2-cube-workspace
---

{% include lang_switcher.html %}

# Cube workspace and execution

Server can explicitly select `sage.sandbox.cube-volume` for remote workspace files
and tool execution. Local execution remains the default. This mode supports one
Sage Server: scheduling, JobRuntime, model calls, sessions, memory indexes, Skill
sources and configuration retain their existing backends.

## Enable

```bash
python -m pip install '.[server,cube]'
```

Add these settings to the existing Server environment:

```dotenv
SAGE_SERVER_SANDBOX_PLUGIN=sage.sandbox.cube-volume
SAGE_SERVER_CUBE_API_URL=http://cube-api:3000
SAGE_SERVER_CUBE_TEMPLATE_ID=your-linux-python-template
SAGE_SERVER_CUBE_PROXY_NODE_IP=cube-proxy
SAGE_SERVER_CUBE_API_KEY=
SAGE_SERVER_CUBE_VOLUME_DRIVER=your-persistent-volume-driver
```

For Docker, also set `SAGE_INSTALL_CUBE=true` and rebuild with
`deploy/compose_v2.sh up -d --build`. The default image does not install Cube SDK.
Cube endpoints must be reachable from Sage. The Linux template must contain
Python 3, Shell and required tools; local browser, Node and font assets are not
copied to the remote template.

Use `cubesandbox>=0.7.3,<1` and a Cube platform supporting persistent Volumes and
read-only mounts. The Volume driver determines persistence and file consistency.
This release requires `sage.scheduler.ephemeral` and rejects distributed scheduling.

## Resource lifecycle

A tenant and Agent have a stable Volume across Sessions. Each Run owns separate
VM compute; completion releases compute and retains the Volume. Children normally
share files while owning separate compute. Private children use separate Volumes;
read-only policies use read-only mounts.

File tools, Shell, web browsing, downloads, external imports and deletion use the
same Volume. File management without an active Run provisions temporary compute
and releases it afterward. Initialization creates missing seed files, and Skills
materialize through the sandbox interface. Full Skill sync stages a replacement
directory and retains the old remote directory under `skills/.sage-backup-*`.
Tenant files are not mirrored to Sage; temporary downloads and seed rendering
remain local.

Local JobRuntime invokes remote `process.run`. A supervisor bounds output and
wall time. Cancellation requests process-group termination and confirms exit
before removing temporary state. Network failures preventing confirmation fail
explicitly; the remote wall-time limit remains active.

## Boundaries

- Switching backends does not migrate files or fall back to local execution.
- Accepted Runs freeze their backend, template, workspace identity and policy.
- New Runs after Sage restart reuse the Volume. Old unfinished Runs are bound to
  the original process instance and fail recovery explicitly rather than replaying
  remote commands. Submit a new Run; in-flight Shell adoption is unsupported.
- No VM memory snapshots, interactive stdio, sandbox stdio MCP or workspace self-configuration.
- File tools allow 8 MiB per file. External import limits remain 4 MiB per file and
  16 MiB per request. The binary upload endpoint accepts up to 64 MiB, staging
  bounded chunks before publication and validating idempotent retries. Downloads
  support bounded reads, directory ZIP archives and top-level entry exclusions.
- Process networking supports `none` and `unrestricted`; allowlists, proxies and
  private-address filtering are unsupported. The sandbox `network.request` HTTP
  interface is not provided by this plugin.
- CPU, memory and aggregate disk hard limits depend on the Cube deployment and
  template. Requests requiring limits the plugin cannot enforce are rejected.

## Verification

```bash
python -m pytest tests/sagents/v2/test_cube_volume_sandbox.py tests/sagents/v2/test_cube_process.py tests/sagents/v2/test_cube_execution_binding.py
python -m pytest tests/app/v2/server/test_cube_configuration.py tests/app/v2/server/test_cube_workspaces.py tests/app/v2/server/test_cube_execution.py
```

Tests execute the file bridge and supervisor scripts and use a Cube simulator
for HTTP flows, isolation, cleanup and persistence after restart. They do not
replace acceptance testing against a real Cube deployment.

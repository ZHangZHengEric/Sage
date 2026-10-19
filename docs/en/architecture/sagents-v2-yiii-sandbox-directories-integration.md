---
layout: default
title: yiii Sandbox Integration
parent: Architecture
nav_order: 16
lang: en
ref: v2-detail-sagents-v2-yiii-sandbox-directories-integration
---

{% include lang_switcher.html %}

<a id="yiii-通过标准-builder-接入沙箱目录与-team-共享实例"></a>

# Integrating yiii sandbox directories and shared Teams through Builder

This change is confined to Sage. Builder's public API is unchanged; the local plugin supplies shared Run leases. yiii should use standard Builder composition rather than provisioning child sandboxes, constructing loops or managing leases itself.

<a id="工作区与目录"></a>

## Workspace and directories

The host workspace is the Agent working directory, not OS root. In the inspected yiii native_runtime.py, workspace_root and host_workspace use the same absolute host path; Project is separate context. Extra /workspace string substitution is unnecessary.

The local plugin creates temporary, Home, cache, config, data and state directories and supplies TMPDIR/TMP/TEMP/HOME/XDG_* variables. File tools accept those prefixes and ~/ and return canonical paths usable by Shell: real workspace paths on macOS, mounted /tmp, /var/tmp and /home/agent paths on Linux. All storage counts toward workspace quota.

Standard Builder projects handle.describe_environment() into <sandbox_environment>, including OS, directories, path rules, limits, sandbox_id, lease_owner_run_id and shared_instance. yiii need not inject an environment provider or hardcode internal directory names.

<a id="team-的默认共享行为"></a>

## Default Team sharing

For mode: team with default shared_parent, Builder acquires independent Run leases from the parent environment:

- Members share sandbox_id, workspace, Home, temporary/cache directories, process slots and resource supervision.
- owner_run_id, signatures, Sessions, tool results, tasks and process ownership remain independent; child grants cannot operate as the parent.
- Completing, cancelling or closing a member revokes only its lease and cleans its running/queued tasks.
- Children/siblings survive parent release while leases remain; the last lease terminates the environment.
- Explicit private_child/read_only_parent policies retain separate host bindings.
- Plugins lacking shared leases fail explicitly rather than creating another sandbox silently.

Shared plugin resources do not imply shared chat or tool permissions. Quotas apply to the whole instance; genuine instance-wide faults propagate to affected members.

<a id="显式嵌套-team标准行为无额外参数"></a>

## Explicit nested Teams with standard APIs

root(team) → director(team) → maker(simple) uses the same public API with per-layer bindings:

```python
maker = await app.load_agent(maker_package)
director = await app.load_agent(director_package, subagents={"maker": maker})
root = await app.load_agent(root_package, subagents={"director": director})
# root_package: mode=team, subagents=("director",)
# director_package: mode=team, subagents=("maker",)
# maker_package: mode=simple
# 照常使用 app.entrypoint().run_stream(command, context, agent=root)。
```

Builder recursively composes the frozen graph's models and components, retaining each layer's tools, Skills, preload and models. Root sees director only; director sees local alias maker, persisted as director.maker. Neither may bypass the other's roster. Ordinary delegated leaves do not gain recursive delegation.

Every explicit Team has its own controller. Deep interactions propagate to the root. Unordered scope sets are sorted in recovery fingerprints to avoid false changes across Python processes. Recover old Runs with await app.agent_for_run(run_id, context), reply through public Interaction APIs and continue_run(..., agent=restored). Never substitute the latest loaded/updated handle.

shared_parent obtains a lease from the **actual immediate parent environment**, retaining inherited private/read-only boundaries. Releasing an intermediate lease preserves others. Teams awaiting children yield execution slots so intermediate layers cannot permanently starve leaf tasks.

If yiii already uses this public path, upgrading Sage is sufficient; nested Teams require no extra parameters or custom loop/provision/lease logic.

Recorded verification on 2026-10-19 reran yiii verify_builder_nested_team.py with verify(False)/verify(True): two/three layers completed with artifacts; the three-layer case had one sandbox_id and three lease_owner_run_id values. Sage regressions also covered forbidden rosters, independent models/preload, parallel nesting, lease release, private/read-only boundaries and cross-process resume. yiii scripts and the original report were unchanged.

<a id="goal--plan-完成门与宿主-continuation-插件"></a>

## Goal / Plan gates and host continuation plugins

Builder accepts host policies through public agent.continuation-policy without custom yiii loops or new gate extension points.

While Goal is incomplete or Plan unsubmitted, existing CONTINUE_STEP, FAIL and REQUEST_INTERACTION decisions pass through with reason_code, reason, metadata and usage intact. Premature COMPLETE_RUN/COMPLETE_TURN/HANDOFF becomes continuation while preserving metadata and usage. goal_complete, user-approved Plan submission and final explanation remain required.

Host recovery markers such as metadata.yiii_autonomous_replan persist in continuation.decided.data.details, while usage goes to usage.recorded. Count recoveries from canonical Run events so context reduction/restarts do not reset them. Existing judge.continue guidance enters the next inference normally.

Public Builder regressions cover real goal_submit, three consecutive autonomous recoveries, Goal/Plan counters across Python restarts and gates rejecting premature completion before finishing normally.

<a id="yiii-需要迁移的装配路径"></a>

## yiii composition paths requiring migration

The inspected python/yiii_agent_runtime/native_runtime.py creates App with Builder but compose_loop still manually provisions sandboxes and constructs OfficialToolRuntime, ModeAwareAgentLoopFactory and AgentCompositionFactory.create_loop. That custom path does not automatically gain Builder Team sharing; upgrading the package alone is insufficient.

Return this custom assembly to the existing build()/load_agent()/run_stream() API:

```python
from sagents.v2 import SAgentBuilder
from sagents.v2.runtime.execution import LocalWorkspaceExecutionBindingProvider

# SDK 提供通用的本地绑定适配器，无需导入 Desktop application。
# resources、network、issuer、sandbox_provider 等仍按宿主已有配置传入。
bindings = LocalWorkspaceExecutionBindingProvider(
    workspace_root,
    resources=resource_limits,
    network=network_policy,
)

app = await (
    SAgentBuilder()
    .with_models(model_catalog)
    .with_session_store(session_store)
    .with_model_provider_factory(model_provider_factory)
    .with_execution_binding_provider(bindings)  # 已有 Builder API
    .with_additional_tools(mcp_catalog, mcp_executor)  # 已有 Builder API
    .build(runtime=runtime_config)
)

# 先加载成员，再把成员 handle 绑定到 Team 包声明的别名。
worker = await app.load_agent(worker_package)
team = await app.load_agent(team_package, subagents={"worker": worker})
# 使用已有 app.entrypoint().run_stream(command, context, agent=team)。
# command.agent_id=team.id，resolved_spec_hash=team.composition_hash。
```

Team Packages use mode: team and declare subagents. Official tools remain selected through tool.catalog: sage.tool.official. Models, MCP, Skills and policies use existing Builder/runtime/plugin hooks; variables above come from host settings. Preserve persisted revisions, model/tool bindings and recovery configuration rather than substituting current Project settings.

If an existing yiii capability cannot be expressed publicly, add the required Sage configuration/plugin support with Builder regressions. Do not restore custom loops. After closing App, the host closes bindings according to ownership; child tasks must not destroy the shared sandbox.

<a id="更新-agent-提示"></a>

## Agent prompt updates

Update storage guidance in python/yiii_agent_runtime/sage_chat_sections/project_context.py:

- Describe the workspace as the default working directory, distinct from OS root and Project.
- Use <sandbox_environment> as directory facts: tempfile/$TMPDIR for temporary files, $HOME for Home and XDG variables for cache/config.
- Equal host/sandbox paths apply only to the current identity workspace, not every platform/path.
- After tool errors, inspect raw causes, usage/limits, recovery results and available capabilities. Interrupted commands may leave artifacts; inspect before retrying.

<a id="哪些路径转换可以删除"></a>

## Redundant path conversions

| Scenario | Handling |
| --- | --- |
| Host directory equals workspace_root | No conversion; retain workspace and allowed roots for authorization/isolation |
| macOS canonical file-tool path | Pass directly to Shell; no /workspace replacement |
| Home/tmp/cache interoperation | Use plugin variables/canonical paths without yiii maps |
| Linux virtual path differs from host | Resolve explicitly when passing to host MCP |
| Project paths, attachments, previews and downloads | Retain their path resolution and authorization; these are distinct boundaries |

Do not globally replace /tmp, ~ or /workspace inside Shell strings. Convert explicit path fields only where crossing a real boundary.

<a id="本机能力与环境变量"></a>

## Host capabilities and environment variables

HOME/TMPDIR/XDG change default storage without revoking host grants. Access still depends on the execution plugin, filesystem/network policies, allowed read-only runtimes and MCP/computer-control grants. File tools remain workspace-scoped; Shell accesses system paths only as permitted. Authorize actual host configuration paths explicitly instead of restoring host HOME to widen access implicitly.

<a id="验收"></a>

## Acceptance

1. Execute real Team delegation through Builder: equal sandbox_id and initial workspace, distinct lease_owner_run_id values.
2. Parent read/write survives child completion; closing one concurrent member leaves others' processes alive.
3. Closing a queued member prevents its command from executing; the last lease closes the instance.
4. Shell/file tools interoperate in Home/TMPDIR/cache while rejecting escape and symlinks.
5. Independent root tasks do not share an instance merely because Project paths match; sharing follows explicit Team ancestry.
